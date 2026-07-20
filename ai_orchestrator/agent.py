"""Agent system for AI orchestration"""

import asyncio
import json
import logging
import uuid
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Set, Union
from collections import deque
from contextlib import asynccontextmanager

from .providers import AIProvider, Message, ToolCall, ToolDefinition, CompletionOptions, CompletionResult, CompletionChunk, ProviderFactory
from .config import Config, AgentConfig, AgentConfig as AgentCfg, AIProviderConfig

logger = logging.getLogger(__name__)


class MessageRole(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    AGENT = "agent"
    SYSTEM_INTERNAL = "system_internal"


class AgentState(Enum):
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING_TOOL = "executing_tool"
    WAITING_USER = "waiting_user"
    ERROR = "error"
    COMPLETED = "completed"


@dataclass
class AgentMessage:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    role: MessageRole = MessageRole.USER
    content: str = ""
    timestamp: float = field(default_factory=time.time)
    agent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    result: Any
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentContext:
    agent_id: str
    session_id: str
    messages: List[AgentMessage] = field(default_factory=list)
    tools: Dict[str, 'Tool'] = field(default_factory=dict)
    state: AgentState = AgentState.IDLE
    current_task: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    parent_agent_id: Optional[str] = None
    child_agents: List[str] = field(default_factory=list)


class Tool(ABC):
    """Base class for tools"""

    def __init__(self, name: str, description: str, parameters: Dict[str, Any]):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.definition = ToolDefinition(name=name, description=description, parameters=parameters)

    @abstractmethod
    async def execute(self, arguments: Dict[str, Any], context: AgentContext) -> ToolResult:
        pass

    def validate_arguments(self, arguments: Dict[str, Any]) -> bool:
        """Validate tool arguments against schema"""
        required = self.parameters.get('required', [])
        for req in required:
            if req not in arguments:
                return False
        return True


class ToolRegistry:
    """Registry for managing tools"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._categories: Dict[str, List[str]] = {}

    def register(self, tool: Tool, category: str = "general"):
        self._tools[tool.name] = tool
        if category not in self._categories:
            self._categories[category] = []
        self._categories[category].append(tool.name)

    def unregister(self, name: str):
        if name in self._tools:
            tool = self._tools.pop(name)
            for cat, tools in self._categories.items():
                if name in tools:
                    tools.remove(name)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def get_all(self) -> List[Tool]:
        return list(self._tools.values())

    def get_by_category(self, category: str) -> List[Tool]:
        names = self._categories.get(category, [])
        return [self._tools[n] for n in names if n in self._tools]

    def get_definitions(self) -> List[ToolDefinition]:
        return [t.definition for t in self._tools.values()]

    def has(self, name: str) -> bool:
        return name in self._tools


class ToolExecutor:
    """Execute tools with timeout and error handling"""

    def __init__(self, default_timeout: float = 30.0):
        self.default_timeout = default_timeout
        self.registry = ToolRegistry()

    async def execute(self, tool_call: ToolCall, context: AgentContext) -> ToolResult:
        tool = self.registry.get(tool_call.name)
        if not tool:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=None,
                error=f"Tool not found: {tool_call.name}"
            )

        try:
            if not tool.validate_arguments(tool_call.arguments):
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    result=None,
                    error=f"Invalid arguments for {tool_call.name}"
                )

            result = await asyncio.wait_for(
                tool.execute(tool_call.arguments, context),
                timeout=self.default_timeout
            )
            return result

        except asyncio.TimeoutError:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=None,
                error=f"Tool execution timeout ({self.default_timeout}s)"
            )
        except Exception as e:
            logger.error(f"Tool {tool_call.name} execution error: {e}")
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=None,
                error=str(e)
            )

    async def execute_batch(self, tool_calls: List[ToolCall], context: AgentContext) -> List[ToolResult]:
        tasks = [self.execute(tc, context) for tc in tool_calls]
        return await asyncio.gather(*tasks)


class BaseAgent(ABC):
    """Base agent class"""

    def __init__(
        self,
        agent_id: str,
        config: AgentConfig,
        provider: AIProvider,
        tool_executor: ToolExecutor,
        system_prompt: str = "",
        parent_context: Optional[AgentContext] = None
    ):
        self.agent_id = agent_id
        self.config = config
        self.provider = provider
        self.tool_executor = tool_executor
        self.system_prompt = system_prompt or config.system_prompt
        self.context = AgentContext(
            agent_id=agent_id,
            session_id=parent_context.session_id if parent_context else str(uuid.uuid4())[:8],
            parent_agent_id=parent_context.agent_id if parent_context else None
        )
        self.state = AgentState.IDLE
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._callbacks: Dict[str, List[Callable]] = {}

    @abstractmethod
    async def process(self, message: AgentMessage) -> AsyncGenerator[AgentMessage, None]:
        """Process a message and yield responses"""
        pass

    async def add_message(self, message: AgentMessage):
        self.context.messages.append(message)
        self.context.updated_at = time.time()
        await self._trigger_callback('message', message)

    def on(self, event: str, callback: Callable):
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    async def _trigger_callback(self, event: str, *args):
        for cb in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(*args)
                else:
                    cb(*args)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def get_messages_for_provider(self, max_tokens: int = None) -> List[Message]:
        """Convert agent messages to provider format with token management"""
        messages = []
        if self.system_prompt:
            messages.append(Message(role="system", content=self.system_prompt))

        total_tokens = 0
        max_t = max_tokens or self.config.max_context_tokens

        for msg in reversed(self.context.messages):
            provider_msg = Message(
                role=msg.role.value,
                content=msg.content,
                tool_calls=msg.tool_calls,
                tool_call_id=msg.tool_call_id
            )
            est_tokens = self.provider.estimate_tokens(msg.content)
            if total_tokens + est_tokens > max_t and len(messages) > 1:
                break
            messages.insert(1, provider_msg)  # Insert after system
            total_tokens += est_tokens

        return messages

    async def complete(self, options: CompletionOptions = None) -> CompletionResult:
        """Get completion from provider"""
        if options is None:
            options = CompletionOptions(model=self.config.model)

        messages = self.get_messages_for_provider()
        tools = self.tool_executor.registry.get_definitions() if self.config.enable_tools else []

        if tools:
            options.tools = tools

        return await self.provider.complete(messages, options)

    async def stream_complete(self, options: CompletionOptions = None) -> AsyncGenerator[CompletionChunk, None]:
        """Stream completion from provider"""
        if options is None:
            options = CompletionOptions(model=self.config.model)

        messages = self.get_messages_for_provider()
        tools = self.tool_executor.registry.get_definitions() if self.config.enable_tools else []

        if tools:
            options.tools = tools

        async for chunk in self.provider.stream_complete(messages, options):
            yield chunk

    async def execute_tools(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        return await self.tool_executor.execute_batch(tool_calls, self.context)


class ChatAgent(BaseAgent):
    """General purpose chat agent with tool support"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tool_loop_limit = self.config.max_tool_iterations

    async def process(self, message: AgentMessage) -> AsyncGenerator[AgentMessage, None]:
        """Process user message and yield responses"""
        await self.add_message(message)
        self.state = AgentState.THINKING

        tool_iterations = 0

        while tool_iterations < self._tool_loop_limit:
            messages_buffer = []
            collected_tool_calls = []

            # Get completion
            async for chunk in self.stream_complete():
                if chunk.content:
                    messages_buffer.append(chunk.content)
                    yield AgentMessage(
                        role=MessageRole.ASSISTANT,
                        content=chunk.content,
                        agent_id=self.agent_id,
                        metadata={"streaming": True, "chunk_id": chunk.chunk_id}
                    )
                if chunk.tool_calls:
                    collected_tool_calls.extend(chunk.tool_calls)

            # Save assistant message to context
            full_content = "".join(messages_buffer)
            assistant_msg = AgentMessage(
                role=MessageRole.ASSISTANT,
                content=full_content,
                agent_id=self.agent_id,
                tool_calls=collected_tool_calls or None
            )
            await self.add_message(assistant_msg)

            # Check for tool calls
            tool_calls = []
            for msg in self.context.messages:
                if msg.role == MessageRole.ASSISTANT and msg.tool_calls:
                    tool_calls.extend(msg.tool_calls)

            if not tool_calls:
                break

            self.state = AgentState.EXECUTING_TOOL
            tool_iterations += 1

            # Execute tools
            tool_results = await self.execute_tools(tool_calls)

            for result in tool_results:
                content = json.dumps(result.result, ensure_ascii=False) if result.result else ""
                tool_msg = AgentMessage(
                    role=MessageRole.TOOL,
                    content=content,
                    tool_call_id=result.tool_call_id,
                    agent_id=self.agent_id,
                    metadata={"tool_name": result.name, "error": result.error}
                )
                await self.add_message(tool_msg)
                yield tool_msg

        self.state = AgentState.COMPLETED


class AgentOrchestrator:
    """Orchestrates multiple agents and manages sessions"""

    def __init__(self, config: Config):
        self.config = config
        self.providers: Dict[str, AIProvider] = {}
        self._pending_providers: Dict[str, Any] = {}
        self.agents: Dict[str, BaseAgent] = {}
        self.tool_executor = ToolExecutor()
        self.sessions: Dict[str, AgentContext] = {}
        self.active_agent_id: Optional[str] = None
        self._running = False
        self._callbacks: Dict[str, List[Callable]] = {}

    async def initialize(self):
        """Initialize only the active provider (lazy load others on demand)"""
        active_name = self.config.active_provider or ""

        for name, provider_config in self.config.providers.items():
            if not provider_config.enabled:
                continue
            if name != active_name:
                # Store config for lazy loading, skip init
                self._pending_providers[name] = provider_config
                continue
            try:
                provider = ProviderFactory.create(provider_config)
                success = await provider.initialize()
                if success:
                    self.providers[name] = provider
                    logger.info(f"Initialized provider: {name}")
                else:
                    logger.warning(f"Provider {name} initialization failed")
                    await provider.close()
            except Exception as e:
                logger.error(f"Failed to initialize provider {name}: {e}")

        # Set default provider
        if self.config.active_provider and self.config.active_provider in self.providers:
            self.active_provider_name = self.config.active_provider
        elif self.providers:
            sorted_providers = sorted(
                self.providers.items(),
                key=lambda x: x[1].config.priority,
                reverse=True
            )
            self.active_provider_name = sorted_providers[0][0]
        else:
            self.active_provider_name = None
            self.active_provider = None
            logger.warning("No providers available at startup")

        if self.active_provider_name:
            self.active_provider = self.providers[self.active_provider_name]

    async def _lazy_load_provider(self, name: str) -> bool:
        """Initialize a provider on demand"""
        if name in self.providers:
            return True
        provider_config = self._pending_providers.pop(name, None)
        if not provider_config:
            # Check config for disabled providers too
            provider_config = self.config.providers.get(name)
            if not provider_config or not provider_config.enabled:
                return False
        try:
            provider = ProviderFactory.create(provider_config)
            success = await provider.initialize()
            if success:
                self.providers[name] = provider
                logger.info(f"Lazy-loaded provider: {name}")
                return True
            await provider.close()
        except Exception as e:
            logger.error(f"Failed to lazy-load provider {name}: {e}")
        return False
        self._register_builtin_tools()

    def _register_builtin_tools(self):
        """Register built-in tools"""
        from .tools import register_builtin_tools
        register_builtin_tools(self.tool_executor.registry)

    def get_provider(self, name: str = None) -> AIProvider:
        name = name or self.active_provider_name
        return self.providers.get(name)

    async def create_agent(
        self,
        agent_type: str = "chat",
        config: AgentConfig = None,
        system_prompt: str = "",
        provider_name: str = None,
        parent_context: AgentContext = None
    ) -> BaseAgent:
        """Create a new agent"""
        provider = self.get_provider(provider_name)
        if not provider:
            raise ValueError(f"Provider not found: {provider_name}")

        agent_config = config or self.config.agent_config

        if agent_type == "chat":
            agent = ChatAgent(
                agent_id=str(uuid.uuid4())[:8],
                config=agent_config,
                provider=provider,
                tool_executor=self.tool_executor,
                system_prompt=system_prompt or agent_config.system_prompt,
                parent_context=parent_context
            )
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")

        self.agents[agent.agent_id] = agent
        if parent_context:
            parent_context.child_agents.append(agent.agent_id)
        self.sessions[agent.context.session_id] = agent.context

        return agent

    async def send_message(self, agent_id: str, message: AgentMessage) -> AsyncGenerator[AgentMessage, None]:
        """Send message to agent and stream responses"""
        agent = self.agents.get(agent_id)
        if not agent:
            raise ValueError(f"Agent not found: {agent_id}")

        self.active_agent_id = agent_id
        async for response in agent.process(message):
            yield response

    async def switch_provider(self, provider_name: str):
        """Switch active provider, lazy-load if needed"""
        if provider_name not in self.providers:
            ok = await self._lazy_load_provider(provider_name)
            if not ok:
                raise ValueError(f"Provider not found or failed to load: {provider_name}")

        old_provider = self.active_provider
        self.active_provider = self.providers[provider_name]
        self.active_provider_name = provider_name
        self.config.active_provider = provider_name

        # Update all agents
        for agent in self.agents.values():
            agent.provider = self.active_provider

        logger.info(f"Switched provider: {old_provider.name if old_provider else 'none'} -> {self.active_provider.name}")

    async def list_models(self, provider_name: str = None) -> List[str]:
        provider = self.get_provider(provider_name)
        if provider:
            return await provider.list_models()
        return []

    async def health_check_all(self) -> Dict[str, bool]:
        results = {}
        for name, provider in self.providers.items():
            results[name] = await provider.health_check()
        return results

    def register_tool(self, tool: Tool, category: str = "custom"):
        self.tool_executor.registry.register(tool, category)

    def on(self, event: str, callback: Callable):
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    async def _trigger_callback(self, event: str, *args):
        for cb in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(*args)
                else:
                    cb(*args)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    async def shutdown(self):
        """Shutdown all providers and agents"""
        self._running = False
        for agent in self.agents.values():
            # Cleanup agent if needed
            pass
        for provider in self.providers.values():
            await provider.close()
        self.providers.clear()
        self.agents.clear()