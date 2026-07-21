"""AI Orchestrator - Local AI agent orchestration with free models"""

from .config import Config, load_config, get_default_config_path
from .orchestrator import AIOrchestrator
from .agent import (
    AgentOrchestrator,
    ChatAgent,
    AgentConfig,
    AgentContext,
    AgentMessage,
    MessageRole,
    AgentState,
    Tool,
    ToolResult,
    ToolExecutor,
    ToolRegistry
)
from .providers import (
    AIProvider,
    ProviderFactory,
    OllamaProvider,
    OpenAICompatibleProvider,
    Message,
    ToolCall,
    ToolDefinition,
    CompletionOptions,
    CompletionResult,
    CompletionChunk
)
from .history import HistoryManager, VirtualScrollManager, HistoryEntry, SessionSummary
from .tools import register_builtin_tools
from .checkpoint_system import Checkpoint

__version__ = "1.0.0"
__all__ = [
    "Config",
    "load_config",
    "get_default_config_path",
    "AIOrchestrator",
    "AgentOrchestrator",
    "ChatAgent",
    "AgentConfig",
    "AgentContext",
    "AgentMessage",
    "MessageRole",
    "AgentState",
    "Tool",
    "ToolResult",
    "ToolExecutor",
    "ToolRegistry",
    "AIProvider",
    "ProviderFactory",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "Message",
    "ToolCall",
    "ToolDefinition",
    "CompletionOptions",
    "CompletionResult",
    "CompletionChunk",
    "HistoryManager",
    "VirtualScrollManager",
    "HistoryEntry",
    "SessionSummary",
    "register_builtin_tools",
    "Checkpoint",
]