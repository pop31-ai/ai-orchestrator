"""History management with JSON file-based storage and retrieval"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    """Manages conversation history using JSON files"""

    def __init__(self, config: HistoryConfig, data_dir: Path):
        self.config = config
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._sessions_index_path = self.data_dir / "sessions_index.json"
        self._lock = asyncio.Lock()
        self._init_index()

    def _init_index(self):
        if not self._sessions_index_path.exists():
            self._write_index({})
        else:
            try:
                data = json.loads(self._sessions_index_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    self._write_index({})
            except (json.JSONDecodeError, ValueError):
                self._write_index({})

    def _read_index(self) -> dict:
        try:
            return json.loads(self._sessions_index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_index(self, data: dict):
        tmp = self._sessions_index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._sessions_index_path)

    def _session_path(self, session_id: str) -> Path:
        return self.data_dir / f"session_{session_id}.json"

    def _read_session_file(self, session_id: str) -> Optional[dict]:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            logger.warning(f"Corrupted session file: {path}")
            return None

    def _write_session_file(self, session_id: str, data: dict):
        path = self._session_path(session_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    async def add_message(self, session_id: str, message: AgentMessage):
        async with self._lock:
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

            session_data = self._read_session_file(session_id)
            if session_data is None:
                session_data = {
                    "session_id": session_id,
                    "messages": [],
                    "started_at": message.timestamp,
                    "message_count": 0,
                    "total_tokens": 0
                }

            session_data["messages"].append(asdict(entry))
            session_data["message_count"] += 1
            session_data["total_tokens"] += entry.tokens
            self._write_session_file(session_id, session_data)

            index = self._read_index()
            now = message.timestamp
            index[session_id] = {
                "session_id": session_id,
                "message_count": session_data["message_count"],
                "total_tokens": session_data["total_tokens"],
                "started_at": session_data.get("started_at", now),
                "last_activity": now,
                "summary": index.get(session_id, {}).get("summary", ""),
                "tags": index.get(session_id, {}).get("tags", [])
            }
            self._write_index(index)

    async def get_messages(
        self,
        session_id: str,
        limit: int = None,
        offset: int = 0,
        before_timestamp: float = None,
        after_timestamp: float = None,
        roles: List[str] = None
    ) -> List[HistoryEntry]:
        limit = limit or self.config.page_size
        session_data = self._read_session_file(session_id)
        if session_data is None:
            return []

        msgs = session_data.get("messages", [])
        filtered = []
        for m in msgs:
            if before_timestamp and m["timestamp"] >= before_timestamp:
                continue
            if after_timestamp and m["timestamp"] <= after_timestamp:
                continue
            if roles and m["role"] not in roles:
                continue
            filtered.append(m)

        filtered.sort(key=lambda x: x["timestamp"], reverse=True)
        page = filtered[offset:offset + limit]
        page.reverse()

        entries = []
        for m in page:
            entries.append(HistoryEntry(**m))
        return entries

    async def get_messages_for_context(
        self,
        session_id: str,
        max_tokens: int = None
    ) -> List[HistoryEntry]:
        max_tokens = max_tokens or self.config.max_total_tokens
        session_data = self._read_session_file(session_id)
        if session_data is None:
            return []

        msgs = session_data.get("messages", [])
        msgs.sort(key=lambda x: x["timestamp"])

        entries = []
        total_tokens = 0
        for m in msgs:
            if total_tokens + m["tokens"] > max_tokens and len(entries) > 0:
                break
            entries.append(HistoryEntry(**m))
            total_tokens += m["tokens"]
        return entries

    async def search_messages(
        self,
        session_id: str,
        query: str,
        limit: int = 20
    ) -> List[HistoryEntry]:
        session_data = self._read_session_file(session_id)
        if session_data is None:
            return []

        msgs = session_data.get("messages", [])
        results = [m for m in msgs if query.lower() in m["content"].lower()]
        results.sort(key=lambda x: x["timestamp"], reverse=True)
        results = results[:limit]
        results.reverse()

        return [HistoryEntry(**m) for m in results]

    async def list_sessions(self, limit: int = 50) -> List[SessionSummary]:
        index = self._read_index()
        sessions = sorted(index.values(), key=lambda x: x.get("last_activity", 0), reverse=True)
        sessions = sessions[:limit]

        result = []
        for s in sessions:
            result.append(SessionSummary(
                session_id=s["session_id"],
                message_count=s["message_count"],
                total_tokens=s["total_tokens"],
                started_at=s.get("started_at", s.get("last_activity", 0)),
                last_activity=s.get("last_activity", 0),
                summary=s.get("summary", ""),
                tags=s.get("tags", [])
            ))
        return result

    async def get_session(self, session_id: str) -> Optional[SessionSummary]:
        index = self._read_index()
        s = index.get(session_id)
        if s is None:
            session_data = self._read_session_file(session_id)
            if session_data is None:
                return None
            return SessionSummary(
                session_id=session_id,
                message_count=session_data.get("message_count", 0),
                total_tokens=session_data.get("total_tokens", 0),
                started_at=session_data.get("started_at", 0),
                last_activity=session_data.get("last_activity", 0)
            )
        return SessionSummary(
            session_id=s["session_id"],
            message_count=s["message_count"],
            total_tokens=s["total_tokens"],
            started_at=s.get("started_at", s.get("last_activity", 0)),
            last_activity=s.get("last_activity", 0),
            summary=s.get("summary", ""),
            tags=s.get("tags", [])
        )

    async def delete_session(self, session_id: str):
        async with self._lock:
            path = self._session_path(session_id)
            if path.exists():
                path.unlink()
            index = self._read_index()
            index.pop(session_id, None)
            self._write_index(index)

    async def export_session(self, session_id: str, format: str = "json") -> str:
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
                time_str = datetime.fromtimestamp(msg.timestamp).strftime("%H:%M:%S")
                lines.append(f"## {role} ({time_str})")
                lines.append(msg.content)
                lines.append("")
            return "\n".join(lines)
        else:
            return json.dumps(data, ensure_ascii=False)

    async def import_session(self, data: str, format: str = "json") -> str:
        if format == "json":
            obj = json.loads(data)
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
        self.current_session_id = session_id
        self._message_heights.clear()
        self._cached_messages.clear()
        self._cache_start = 0
        self._cache_end = 0
        self._total_count = await self._get_total_count(session_id)

    async def _get_total_count(self, session_id: str) -> int:
        session = await self.history_manager.get_session(session_id)
        if session:
            return session.message_count
        return 0

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
        if not self.current_session_id:
            return []

        item_height = self.item_height
        start_idx = max(0, scroll_top // item_height)
        end_idx = min(self._total_count, (scroll_top + viewport_height) // item_height + 1)

        buffer = self.config.render_buffer
        start_idx = max(0, start_idx - buffer)
        end_idx = min(self._total_count, end_idx + buffer)

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
        if not messages:
            return []

        recent = messages[-preserve_recent:] if len(messages) > preserve_recent else messages
        older = messages[:-preserve_recent] if len(messages) > preserve_recent else []

        current_tokens = sum(m.tokens for m in messages)
        if current_tokens <= target_tokens:
            return messages

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

        truncated = older[-(target_tokens // 100):]
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
        if not self.provider:
            return self._simple_summarize(messages)

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
