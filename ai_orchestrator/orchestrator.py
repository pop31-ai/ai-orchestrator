"""Main AI Orchestrator Application"""

import asyncio
import logging
import signal
import sys
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Callable

from .config import Config, load_config, get_default_config_path, AIProviderConfig
from .providers import AIProvider, ProviderFactory, Message, CompletionOptions, CompletionChunk, CompletionResult
from .agent import AgentOrchestrator, ChatAgent, AgentConfig, AgentContext, AgentMessage, MessageRole, ToolExecutor
from .history import HistoryManager, VirtualScrollManager, HistoryCompressor
from .tools import register_builtin_tools

logger = logging.getLogger(__name__)


class AIOrchestrator:
    """Main orchestrator class"""

    def __init__(self, config: Config = None, config_path: str = None):
        self.config = config or load_config(config_path or get_default_config_path())
        self.orchestrator: Optional[AgentOrchestrator] = None
        self.history_manager: Optional[HistoryManager] = None
        self.scroll_manager: Optional[VirtualScrollManager] = None
        self.compressor: Optional[HistoryCompressor] = None
        self.current_session_id: Optional[str] = None
        self.active_agent_id: Optional[str] = None
        self._running = False
        self._callbacks: Dict[str, List[Callable]] = {}
        self._shutdown_event = asyncio.Event()

    async def initialize(self):
        """Initialize all components"""
        logger.info("Initializing AI Orchestrator...")

        # Create orchestrator
        self.orchestrator = AgentOrchestrator(self.config)
        await self.orchestrator.initialize()

        # Setup history
        data_dir = Path(self.config.data_dir)
        self.history_manager = HistoryManager(self.config.history, data_dir)
        self.scroll_manager = VirtualScrollManager(
            self.history_manager,
            self.config.history
        )
        # Compressor will be initialized when provider is available
        self.compressor = None

        # Register built-in tools
        register_builtin_tools(self.orchestrator.tool_executor.registry)

        # Setup signal handlers
        self._setup_signals()

        self._running = True
        logger.info("AI Orchestrator initialized successfully")

    @property
    def active_provider(self) -> AIProvider:
        return self.orchestrator.active_provider if self.orchestrator else None

    @property
    def active_provider_name(self) -> str:
        return self.orchestrator.active_provider_name if self.orchestrator else ""

    def _setup_signals(self):
        """Setup signal handlers for graceful shutdown"""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down AI Orchestrator...")
        self._running = False

        # Close providers
        if self.orchestrator:
            for provider in self.orchestrator.providers.values():
                await provider.close()

        self._shutdown_event.set()
        logger.info("Shutdown complete")

    async def wait_for_shutdown(self):
        await self._shutdown_event.wait()

    def on(self, event: str, callback: Callable):
        """Register event callback"""
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    async def _emit(self, event: str, *args):
        for cb in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(*args)
                else:
                    cb(*args)
            except Exception as e:
                logger.error(f"Callback error for {event}: {e}")

    # Session management
    async def create_session(self, session_id: str = None) -> str:
        """Create new session"""
        session_id = session_id or str(uuid.uuid4())[:8]
        self.current_session_id = session_id
        await self.scroll_manager.set_session(session_id)
        await self._emit("session_created", session_id)
        return session_id

    async def switch_session(self, session_id: str):
        """Switch to existing session"""
        self.current_session_id = session_id
        await self.scroll_manager.set_session(session_id)
        await self._emit("session_switched", session_id)

    async def list_sessions(self, limit: int = 50) -> List[Dict]:
        """List available sessions"""
        summaries = await self.history_manager.list_sessions(limit=limit)
        return [s.__dict__ for s in summaries]

    async def delete_session(self, session_id: str):
        """Delete a session"""
        await self.history_manager.delete_session(session_id)
        if self.current_session_id == session_id:
            self.current_session_id = None
        await self._emit("session_deleted", session_id)

    # Provider management
    def list_providers(self) -> List[Dict]:
        """List available providers"""
        return [
            {
                "name": name,
                "display_name": provider.config.name,
                "type": provider.type,
                "enabled": provider.config.enabled,
                "model": provider.config.model,
                "models": provider.config.models,
                "priority": provider.config.priority,
                "healthy": True  # Could add health check
            }
            for name, provider in self.orchestrator.providers.items()
        ]

    async def switch_provider(self, provider_name: str) -> bool:
        """Switch active provider with lazy loading"""
        if provider_name not in self.orchestrator.providers:
            ok = await self.orchestrator._lazy_load_provider(provider_name)
            if not ok:
                return False

        self.orchestrator.active_provider_name = provider_name
        self.orchestrator.active_provider = self.orchestrator.providers[provider_name]
        self.config.active_provider = provider_name
        await self._emit("provider_switched", provider_name)
        return True

    async def list_models(self, provider_name: str = None) -> List[str]:
        """List models for provider"""
        provider_name = provider_name or self.active_provider_name
        provider = self.orchestrator.providers.get(provider_name)
        if provider:
            return await provider.list_models()
        return []

    async def switch_model(self, model: str, provider_name: str = None) -> bool:
        """Switch model for provider"""
        provider_name = provider_name or self.active_provider_name
        provider = self.orchestrator.providers.get(provider_name)
        if not provider:
            return False

        models = await provider.list_models()
        if model not in models and model not in provider.config.models:
            # Try to use it anyway (might be a new model)
            pass

        provider.config.model = model
        self.config.default_model = model
        await self._emit("model_switched", {"provider": provider_name, "model": model})
        return True

    # Agent management
    async def create_agent(
        self,
        agent_type: str = "chat",
        system_prompt: str = "",
        agent_config: Dict = None
    ) -> ChatAgent:
        """Create a new agent"""
        agent_id = str(uuid.uuid4())[:8]

        # Create agent config
        cfg = AgentConfig(
            **(agent_config or {})
        )
        cfg.system_prompt = system_prompt or cfg.system_prompt

        # Create agent
        if agent_type == "chat":
            agent = ChatAgent(
                agent_id=agent_id,
                config=cfg,
                provider=self.active_provider,
                tool_executor=self.orchestrator.tool_executor,
                system_prompt=system_prompt
            )
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")

        self.orchestrator.agents[agent_id] = agent
        self.active_agent_id = agent_id

        # Setup callbacks
        agent.on("message", lambda msg: asyncio.create_task(self._on_agent_message(agent_id, msg)))

        await self._emit("agent_created", {"agent_id": agent_id, "type": agent_type})
        return agent

    async def _on_agent_message(self, agent_id: str, message: AgentMessage):
        """Handle agent message for history"""
        if self.current_session_id:
            await self.history_manager.add_message(self.current_session_id, message)
        await self._emit("message", {"agent_id": agent_id, "message": message})

    async def send_message(
        self,
        content: str,
        agent_id: str = None,
        role: MessageRole = MessageRole.USER
    ) -> AsyncGenerator[AgentMessage, None]:
        """Send message to agent and stream response"""
        agent_id = agent_id or self.active_agent_id
        agent = self.orchestrator.agents.get(agent_id)

        if not agent:
            raise ValueError(f"Agent not found: {agent_id}")

        message = AgentMessage(
            role=role,
            content=content,
            agent_id=agent_id
        )

        async for response in agent.process(message):
            yield response

    # History and scrolling
    async def get_history_page(
        self,
        session_id: str = None,
        page: int = 0,
        page_size: int = None
    ) -> List[Dict]:
        """Get paginated history"""
        session_id = session_id or self.current_session_id
        page_size = page_size or self.config.history.page_size
        offset = page * page_size

        entries = await self.history_manager.get_messages(
            session_id,
            limit=page_size,
            offset=offset
        )
        return [e.__dict__ for e in entries]

    async def get_messages_for_context(
        self,
        session_id: str = None,
        max_tokens: int = None
    ) -> List[Dict]:
        """Get messages optimized for context"""
        session_id = session_id or self.current_session_id
        entries = await self.history_manager.get_messages_for_context(
            session_id,
            max_tokens=max_tokens
        )
        return [e.__dict__ for e in entries]

    async def search_history(
        self,
        query: str,
        session_id: str = None,
        limit: int = 20
    ) -> List[Dict]:
        """Search history"""
        session_id = session_id or self.current_session_id
        entries = await self.history_manager.search_messages(session_id, query, limit)
        return [e.__dict__ for e in entries]

    async def get_virtual_scroll_messages(
        self,
        scroll_top: int,
        viewport_height: int
    ) -> List[Dict]:
        """Get messages for virtual scrolling"""
        messages = await self.scroll_manager.get_messages_for_viewport(scroll_top, viewport_height)
        return [{"index": idx, **msg.__dict__} for idx, msg in messages]

    def get_scroll_info(self) -> Dict:
        """Get scroll information"""
        return {
            "total_count": self.scroll_manager.total_count,
            "total_height": self.scroll_manager.get_total_height(),
            "visible_range": self.scroll_manager.visible_range,
            "item_height": self.scroll_manager.item_height
        }

    # Export/Import
    async def export_session(self, session_id: str = None, format: str = "json") -> str:
        """Export session"""
        session_id = session_id or self.current_session_id
        return await self.history_manager.export_session(session_id, format)

    async def import_session(self, data: str, format: str = "json") -> str:
        """Import session"""
        return await self.history_manager.import_session(data, format)

    # Configuration
    def get_config(self) -> Dict:
        """Get current configuration"""
        return {
            "active_provider": self.active_provider_name,
            "default_model": self.config.default_model,
            "providers": {name: {
                "name": p.config.name,
                "type": p.config.type,
                "model": p.config.model,
                "models": p.config.models,
                "enabled": p.config.enabled,
                "base_url": p.config.base_url,
                "priority": p.config.priority
            } for name, p in self.orchestrator.providers.items()},
            "agent": self.config.agent_config.__dict__,
            "history": self.config.history.__dict__,
            "ui": self.config.ui.__dict__
        }

    async def update_config(self, updates: Dict):
        """Update configuration"""
        # Update provider configs
        if "providers" in updates:
            for name, provider_updates in updates["providers"].items():
                if name in self.orchestrator.providers:
                    provider = self.orchestrator.providers[name]
                    for key, value in provider_updates.items():
                        if hasattr(provider.config, key):
                            setattr(provider.config, key, value)

        # Update other configs
        for key in ["agent_config", "history", "ui", "active_provider", "default_model"]:
            if key in updates:
                if key == "agent_config":
                    for k, v in updates[key].items():
                        if hasattr(self.config.agent_config, k):
                            setattr(self.config.agent_config, k, v)
                elif key == "history":
                    for k, v in updates[key].items():
                        if hasattr(self.config.history, k):
                            setattr(self.config.history, k, v)
                elif key == "ui":
                    for k, v in updates[key].items():
                        if hasattr(self.config.ui, k):
                            setattr(self.config.ui, k, v)
                else:
                    setattr(self.config, key, updates[key])

        # Persist
        from .config import save_config
        save_config(self.config, get_default_config_path())

    # Utility
    async def health_check(self) -> Dict[str, bool]:
        """Check health of all providers"""
        results = {}
        for name, provider in self.orchestrator.providers.items():
            results[name] = await provider.health_check()
        return results


async def create_orchestrator(config_path: str = None) -> AIOrchestrator:
    """Factory function to create and initialize orchestrator"""
    orchestrator = AIOrchestrator(config_path=config_path)
    await orchestrator.initialize()
    return orchestrator


def main():
    """Main entry point for CLI"""
    import argparse

    parser = argparse.ArgumentParser(description="AI Orchestrator")
    parser.add_argument("--config", help="Config file path")
    parser.add_argument("--provider", help="Initial provider")
    parser.add_argument("--model", help="Initial model")
    parser.add_argument("--session", help="Session ID to load")
    parser.add_argument("--debug", action="store_true", help="Debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    async def run():
        orchestrator = await create_orchestrator(args.config)

        if args.provider:
            await orchestrator.switch_provider(args.provider)

        if args.model:
            await orchestrator.switch_model(args.model)

        if args.session:
            await orchestrator.switch_session(args.session)
        else:
            await orchestrator.create_session()

        # Interactive loop
        print(f"AI Orchestrator v{__version__}")
        print(f"Provider: {orchestrator.active_provider_name}")
        print(f"Model: {orchestrator.config.default_model}")
        print(f"Session: {orchestrator.current_session_id}")
        print("Type 'exit' to quit, '/help' for commands\n")

        while orchestrator._running:
            try:
                user_input = input("> ").strip()
                if not user_input:
                    continue

                if user_input.lower() in ("exit", "quit"):
                    break

                if user_input.startswith("/"):
                    await handle_command(orchestrator, user_input)
                    continue

                # Send message
                async for response in orchestrator.send_message(user_input):
                    if response.content:
                        print(response.content, end="", flush=True)
                print()

            except KeyboardInterrupt:
                break
            except EOFError:
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                print(f"Error: {e}")

        await orchestrator.shutdown()

    asyncio.run(run())


async def handle_command(orchestrator: AIOrchestrator, command: str):
    """Handle CLI commands"""
    parts = command[1:].split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd == "help":
        print("Commands:")
        print("  /help - Show this help")
        print("  /providers - List providers")
        print("  /switch <provider> - Switch provider")
        print("  /models - List models")
        print("  /model <name> - Switch model")
        print("  /sessions - List sessions")
        print("  /session <id> - Switch session")
        print("  /new-session - Create new session")
        print("  /history [page] - Show history")
        print("  /search <query> - Search history")
        print("  /export [format] - Export session")
        print("  /config - Show config")
        print("  /health - Health check")
        print("  /agent <type> [prompt] - Create agent")

    elif cmd == "providers":
        for p in orchestrator.list_providers():
            active = " *" if p["name"] == orchestrator.active_provider_name else ""
            print(f"  {p['name']}{active}: {p['display_name']} ({p['type']}) - {p['model']}")

    elif cmd == "switch" and args:
        if await orchestrator.switch_provider(args[0]):
            print(f"Switched to {args[0]}")
        else:
            print(f"Provider not found: {args[0]}")

    elif cmd == "models":
        models = await orchestrator.list_models()
        for m in models:
            active = " *" if m == orchestrator.config.default_model else ""
            print(f"  {m}{active}")

    elif cmd == "model" and args:
        if await orchestrator.switch_model(args[0]):
            print(f"Switched to model: {args[0]}")
        else:
            print(f"Model not available: {args[0]}")

    elif cmd == "sessions":
        sessions = await orchestrator.list_sessions()
        for s in sessions:
            active = " *" if s["session_id"] == orchestrator.current_session_id else ""
            print(f"  {s['session_id']}{active}: {s['message_count']} msgs, {s['total_tokens']} tokens")

    elif cmd == "session" and args:
        await orchestrator.switch_session(args[0])
        print(f"Switched to session: {args[0]}")

    elif cmd == "new-session":
        sid = await orchestrator.create_session()
        print(f"Created session: {sid}")

    elif cmd == "history":
        page = int(args[0]) if args else 0
        entries = await orchestrator.get_history_page(page=page)
        for e in entries:
            print(f"  [{e['role']}] {e['content'][:100]}...")

    elif cmd == "search" and args:
        query = " ".join(args)
        results = await orchestrator.search_history(query)
        for r in results:
            print(f"  [{r['role']}] {r['content'][:150]}...")

    elif cmd == "export":
        fmt = args[0] if args else "json"
        data = await orchestrator.export_session(format=fmt)
        print(data)

    elif cmd == "config":
        import json
        print(json.dumps(orchestrator.get_config(), indent=2))

    elif cmd == "health":
        results = await orchestrator.health_check()
        for name, healthy in results.items():
            status = "OK" if healthy else "FAIL"
            print(f"  {name}: {status}")

    elif cmd == "agent" and args:
        agent_type = args[0]
        prompt = " ".join(args[1:]) if len(args) > 1 else ""
        agent_id = await orchestrator.create_agent(agent_type, prompt)
        print(f"Created agent: {agent_id}")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()