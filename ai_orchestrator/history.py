"""History management with efficient storage and retrieval"""

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager

from .agent import AgentMessage, MessageRole
from .config import HistoryConfig

logger = logging.getLogger(__name__)


@dataclass
class HistoryEntry:
    id: str
    session_id: str
    role: str
    content: str
    agent_id: Optional[str]
    timestamp: float
    tokens: int
    metadata: Dict[str, Any]
    tool_calls: List[Dict] = None
    tool_call_id: Optional[str] = None

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []


@dataclass
class SessionSummary:
    session_id: str
    message_count: int
    total_tokens: int
    started_at: float
    last_activity: float
    summary: str = ""
    tags: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class HistoryManager:
    """Manages conversation history with efficient storage and retrieval"""

    def __init__(self, config: HistoryConfig, data_dir: Path):
        self.config = config
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "history.db"
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    agent_id TEXT,
                    timestamp REAL NOT NULL,
                    tokens INTEGER DEFAULT 0,
                    metadata TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_timestamp
                ON messages(session_id, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_id
                ON messages(session_id)
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    message_count INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    started_at REAL NOT NULL,
                    last_activity REAL NOT NULL,
                    summary TEXT,
                    tags TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    message_id TEXT PRIMARY KEY,
                    embedding BLOB NOT NULL,
                    model TEXT NOT NULL,
                    FOREIGN KEY(message_id) REFERENCES messages(id)
                )
            """)

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    async def add_message(self, session_id: str, message: AgentMessage):
        """Add message to history"""
        entry = HistoryEntry(
            id=message.id,
            session_id=session_id,
            role=message.role.value,
            content=message.content,
            agent_id=message.agent_id,
            timestamp=message.timestamp,
            tokens=self._estimate_tokens(message.content),
            metadata=message.metadata,
            tool_calls=[tc.__dict__ for tc in message.tool_calls] if message.tool_calls else [],
            tool_call_id=message.tool_call_id
        )

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO messages (id, session_id, role, content, agent_id, timestamp, tokens, metadata, tool_calls, tool_call_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.id, entry.session_id, entry.role, entry.content,
                entry.agent_id, entry.timestamp, entry.tokens,
                json.dumps(entry.metadata), json.dumps(entry.tool_calls),
                entry.tool_call_id
            ))

            # Update session
            conn.execute("""
                INSERT INTO sessions (session_id, message_count, total_tokens, started_at, last_activity)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    message_count = message_count + 1,
                    total_tokens = total_tokens + ?,
                    last_activity = ?
            """, (session_id, entry.tokens, entry.timestamp, entry.timestamp, entry.tokens, entry.timestamp))

    async def get_messages(
        self,
        session_id: str,
        limit: int = None,
        offset: int = 0,
        before_timestamp: float = None,
        after_timestamp: float = None,
        roles: List[str] = None
    ) -> List[HistoryEntry]:
        """Get messages with pagination"""
        limit = limit or self.config.page_size

        query = "SELECT * FROM messages WHERE session_id = ?"
        params = [session_id]

        if before_timestamp:
            query += " AND timestamp < ?"
            params.append(before_timestamp)
        if after_timestamp:
            query += " AND timestamp > ?"
            params.append(after_timestamp)
        if roles:
            placeholders = ",".join(["?"] * len(roles))
            query += f" AND role IN ({placeholders})"
            params.extend(roles)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()

        entries = []
        for row in reversed(rows):  # Reverse to get chronological order
            entries.append(HistoryEntry(
                id=row['id'],
                session_id=row['session_id'],
                role=row['role'],
                content=row['content'],
                agent_id=row['agent_id'],
                timestamp=row['timestamp'],
                tokens=row['tokens'],
                metadata=json.loads(row['metadata']) if row['metadata'] else {},
                tool_calls=json.loads(row['tool_calls']) if row['tool_calls'] else [],
                tool_call_id=row['tool_call_id']
            ))

        return entries

    async def get_messages_for_context(
        self,
        session_id: str,
        max_tokens: int = None
    ) -> List[HistoryEntry]:
        """Get messages optimized for context window"""
        max_tokens = max_tokens or self.config.max_total_tokens

        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM messages
                WHERE session_id = ?
                ORDER BY timestamp DESC
            """, (session_id,)).fetchall()

        entries = []
        total_tokens = 0
        max_t = max_tokens

        for row in reversed(rows):
            entry = HistoryEntry(
                id=row['id'],
                session_id=row['session_id'],
                role=row['role'],
                content=row['content'],
                agent_id=row['agent_id'],
                timestamp=row['timestamp'],
                tokens=row['tokens'],
                metadata=json.loads(row['metadata']) if row['metadata'] else {},
                tool_calls=json.loads(row['tool_calls']) if row['tool_calls'] else [],
                tool_call_id=row['tool_call_id']
            )

            if total_tokens + entry.tokens > max_t and len(entries) > 0:
                break

            entries.append(entry)
            total_tokens += entry.tokens

        return entries

    async def search_messages(
        self,
        session_id: str,
        query: str,
        limit: int = 20
    ) -> List[HistoryEntry]:
        """Search messages by content"""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM messages
                WHERE session_id = ? AND content LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (session_id, f"%{query}%", limit)).fetchall()

        entries = []
        for row in reversed(rows):
            entries.append(HistoryEntry(
                id=row['id'],
                session_id=row['session_id'],
                role=row['role'],
                content=row['content'],
                agent_id=row['agent_id'],
                timestamp=row['timestamp'],
                tokens=row['tokens'],
                metadata=json.loads(row['metadata']) if row['metadata'] else {},
                tool_calls=json.loads(row['tool_calls']) if row['tool_calls'] else [],
                tool_call_id=row['tool_call_id']
            ))

        return entries

    async def list_sessions(self, limit: int = 50) -> List[SessionSummary]:
        """List all sessions"""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM sessions
                ORDER BY last_activity DESC
                LIMIT ?
            """, (limit,)).fetchall()

        summaries = []
        for row in rows:
            summaries.append(SessionSummary(
                session_id=row['session_id'],
                message_count=row['message_count'],
                total_tokens=row['total_tokens'],
                started_at=row['started_at'],
                last_activity=row['last_activity'],
                summary=row['summary'] or "",
                tags=json.loads(row['tags']) if row['tags'] else []
            ))

        return summaries

    async def get_session(self, session_id: str) -> Optional[SessionSummary]:
        """Get session summary"""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if not row:
                return None

            return SessionSummary(
                session_id=row['session_id'],
                message_count=row['message_count'],
                total_tokens=row['total_tokens'],
                started_at=row['started_at'],
                last_activity=row['last_activity'],
                summary=row['summary'] or "",
                tags=json.loads(row['tags']) if row['tags'] else []
            )

    async def delete_session(self, session_id: str):
        """Delete a session and all its messages"""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    async def export_session(self, session_id: str, format: str = "json") -> str:
        """Export session to string"""
        messages = await self.get_messages(session_id, limit=10000)
        session = await self.get_session(session_id)

        data = {
            "session": session.__dict__ if session else None,
            "messages": [e.__dict__ for e in messages]
        }

        if format == "json":
            return json.dumps(data, indent=2, ensure_ascii=False)
        elif format == "markdown":
            lines = [f"# Session {session_id}\n"]
            if session:
                lines.append(f"Messages: {session.message_count}, Tokens: {session.total_tokens}")
                lines.append(f"Started: {datetime.fromtimestamp(session.started_at)}")
                lines.append(f"Last activity: {datetime.fromtimestamp(session.last_activity)}")
                lines.append("")

            for msg in messages:
                role = msg.role.upper()
                time = datetime.fromtimestamp(msg.timestamp).strftime("%H:%M:%S")
                lines.append(f"## {role} ({time})")
                lines.append(msg.content)
                lines.append("")
            return "\n".join(lines)
        else:
            return json.dumps(data, ensure_ascii=False)

    async def import_session(self, data: str, format: str = "json") -> str:
        """Import session from string"""
        if format == "json":
            obj = json.loads(data)
            session_data = obj.get("session")
            messages_data = obj.get("messages", [])

            session_id = str(uuid.uuid4())[:8]

            for msg_data in messages_data:
                message = AgentMessage(
                    id=msg_data['id'],
                    role=MessageRole(msg_data['role']),
                    content=msg_data['content'],
                    agent_id=msg_data.get('agent_id'),
                    timestamp=msg_data['timestamp'],
                    metadata=msg_data.get('metadata', {}),
                    tool_calls=msg_data.get('tool_calls', []),
                    tool_call_id=msg_data.get('tool_call_id')
                )
                await self.add_message(session_id, message)

            return session_id

        raise ValueError(f"Unsupported format: {format}")


class VirtualScrollManager:
    """Manages virtual scrolling for large message histories"""

    def __init__(self, history_manager: HistoryManager, config: HistoryConfig):
        self.history_manager = history_manager
        self.config = config
        self.current_session_id: Optional[str] = None
        self._message_heights: Dict[str, int] = {}
        self._total_count = 0
        self._cached_messages: List[HistoryEntry] = []
        self._cache_start = 0
        self._cache_end = 0

    async def set_session(self, session_id: str):
        """Set current session for scrolling"""
        self.current_session_id = session_id
        self._message_heights.clear()
        self._cached_messages.clear()
        self._cache_start = 0
        self._cache_end = 0
        self._total_count = await self._get_total_count(session_id)

    async def _get_total_count(self, session_id: str) -> int:
        with self.history_manager._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?", (session_id,)).fetchone()
            return row['cnt'] if row else 0

    @property
    def total_count(self) -> int:
        return self._total_count

    @property
    def item_height(self) -> int:
        return self.config.virtual_item_height

    def get_total_height(self) -> int:
        return self._total_count * self.item_height

    @property
    def visible_range(self) -> Tuple[int, int]:
        return (self._cache_start, self._cache_end)

    async def get_messages_for_viewport(
        self,
        scroll_top: int,
        viewport_height: int
    ) -> List[Tuple[int, HistoryEntry]]:
        """Get messages visible in viewport with their indices"""
        if not self.current_session_id:
            return []

        item_height = self.item_height
        start_idx = max(0, scroll_top // item_height)
        end_idx = min(self._total_count, (scroll_top + viewport_height) // item_height + 1)

        # Add buffer
        buffer = self.config.render_buffer
        start_idx = max(0, start_idx - buffer)
        end_idx = min(self._total_count, end_idx + buffer)

        # Check if we need to fetch new data
        if start_idx < self._cache_start or end_idx > self._cache_end or not self._cached_messages:
            limit = end_idx - start_idx
            offset = start_idx
            messages = await self.history_manager.get_messages(
                self.current_session_id,
                limit=limit,
                offset=offset
            )
            self._cached_messages = messages
            self._cache_start = start_idx
            self._cache_end = end_idx

        # Return visible subset with indices
        result = []
        for i, msg in enumerate(self._cached_messages):
            idx = start_idx + i
            if start_idx <= idx < end_idx:
                result.append((idx, msg))

        return result


class HistoryCompressor:
    """Compresses history to fit token budgets"""

    def __init__(self, config: HistoryConfig, provider=None):
        self.config = config
        self.provider = provider

    async def compress_messages(
        self,
        messages: List[HistoryEntry],
        target_tokens: int,
        preserve_recent: int = 10
    ) -> List[HistoryEntry]:
        """Compress messages to fit token budget"""
        if not messages:
            return []

        # Always preserve recent messages
        recent = messages[-preserve_recent:] if len(messages) > preserve_recent else messages
        older = messages[:-preserve_recent] if len(messages) > preserve_recent else []

        current_tokens = sum(m.tokens for m in messages)
        if current_tokens <= target_tokens:
            return messages

        # If we have a provider, use it to summarize
        if self.provider and older:
            summary = await self._summarize_with_llm(older)
            summary_entry = HistoryEntry(
                id=str(uuid.uuid4())[:8],
                session_id=older[0].session_id if older else "",
                role="system",
                content=f"[Summary of {len(older)} previous messages]: {summary}",
                agent_id=None,
                timestamp=time.time(),
                tokens=self._estimate_tokens(summary),
                metadata={"compressed": True, "original_count": len(older)}
            )
            return [summary_entry] + recent

        # Fallback: simple truncation with indicator
        truncated = older[-(target_tokens // 100):]  # Rough estimate
        indicator = HistoryEntry(
            id=str(uuid.uuid4())[:8],
            session_id=older[0].session_id if older else "",
            role="system",
            content=f"[{len(older) - len(truncated)} messages omitted for token budget]",
            agent_id=None,
            timestamp=time.time(),
            tokens=20,
            metadata={"truncated": True}
        )
        return [indicator] + truncated + recent

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    async def _summarize_with_llm(self, messages: List[HistoryEntry]) -> str:
        """Use LLM to summarize messages"""
        if not self.provider:
            return self._simple_summarize(messages)

        # Build conversation for summarization
        conv = []
        for m in messages:
            conv.append({"role": m.role, "content": m.content})

        prompt = """Summarize the following conversation concisely, preserving key facts, decisions, and context needed for continuation. Focus on technical details, code references, and action items."""

        try:
            from .providers import Message, CompletionOptions
            messages_for_llm = [
                Message(role="system", content=prompt),
                Message(role="user", content=json.dumps(conv, ensure_ascii=False))
            ]
            result = await self.provider.complete(
                messages_for_llm,
                CompletionOptions(model="", max_tokens=500, temperature=0.3)
            )
            return result.content.strip()
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            return self._simple_summarize(messages)

    def _simple_summarize(self, messages: List[HistoryEntry]) -> str:
        """Simple extractive summarization"""
        user_msgs = [m for m in messages if m.role == "user"]
        assistant_msgs = [m for m in messages if m.role == "assistant"]

        parts = []
        if user_msgs:
            parts.append(f"User asked {len(user_msgs)} questions")
        if assistant_msgs:
            parts.append(f"Assistant responded {len(assistant_msgs)} times")

        if user_msgs:
            parts.append(f"First topic: {user_msgs[0].content[:100]}")
            parts.append(f"Last topic: {user_msgs[-1].content[:100]}")

        return ". ".join(parts)