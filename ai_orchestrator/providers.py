"""AI Provider abstraction and implementations"""

import asyncio
import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
from pathlib import Path
import aiohttp
import logging

logger = logging.getLogger(__name__)


@dataclass
class Message:
    role: str  # system, user, assistant, tool
    content: str
    name: Optional[str] = None
    tool_calls: List[Dict] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    tokens: int = 0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass
class CompletionOptions:
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    stop: List[str] = field(default_factory=list)
    stream: bool = True
    tools: List[ToolDefinition] = field(default_factory=list)
    tool_choice: str = "auto"
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompletionChunk:
    content: str
    finish_reason: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Optional[Dict[str, int]] = None
    model: str = ""
    provider: str = ""
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class CompletionResult:
    content: str
    finish_reason: str = "stop"
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Optional[Dict[str, int]] = None
    model: str = ""
    provider: str = ""
    chunks: List[CompletionChunk] = field(default_factory=list)
    error: Optional[str] = None
    latency_ms: float = 0


class AIProvider(ABC):
    """Abstract base class for AI providers"""

    def __init__(self, config: 'AIProviderConfig'):
        self.config = config
        self.name = config.name
        self.type = config.type
        self.session: Optional[aiohttp.ClientSession] = None
        self._available_models: List[str] = []
        self._models_fetched = False

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the provider"""
        pass

    @abstractmethod
    async def complete(self, messages: List[Message], options: CompletionOptions) -> CompletionResult:
        """Complete a chat conversation"""
        pass

    @abstractmethod
    async def stream_complete(self, messages: List[Message], options: CompletionOptions) -> AsyncGenerator[CompletionChunk, None]:
        """Stream completion chunks"""
        pass

    @abstractmethod
    async def list_models(self) -> List[str]:
        """List available models"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if provider is healthy"""
        pass

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation"""
        return len(text) // 4


class OllamaProvider(AIProvider):
    """Ollama local/remote provider"""

    def __init__(self, config: 'AIProviderConfig'):
        super().__init__(config)
        self.base_url = config.base_url.rstrip('/')
        self._models_cache: Dict[str, Dict] = {}

    async def initialize(self) -> bool:
        try:
            await self._fetch_models()
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Ollama provider: {e}")
            return False

    async def _fetch_models(self):
        session = self._get_session()
        async with session.get(f"{self.base_url}/api/tags") as resp:
            if resp.status == 200:
                data = await resp.json()
                self._available_models = [m['name'] for m in data.get('models', [])]
                self._models_cache = {m['name']: m for m in data.get('models', [])}
                self._models_fetched = True
            else:
                raise Exception(f"Failed to fetch models: {resp.status}")

    async def list_models(self) -> List[str]:
        if not self._models_fetched:
            await self._fetch_models()
        return self._available_models

    async def health_check(self) -> bool:
        try:
            session = self._get_session()
            async with session.get(f"{self.base_url}/api/version") as resp:
                return resp.status == 200
        except Exception:
            return False

    def _format_messages(self, messages: List[Message]) -> List[Dict]:
        formatted = []
        for msg in messages:
            if msg.role == "tool":
                formatted.append({
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id
                })
            elif msg.role == "assistant" and msg.tool_calls:
                formatted.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": msg.tool_calls
                })
            else:
                formatted.append({
                    "role": msg.role,
                    "content": msg.content
                })
        return formatted

    async def complete(self, messages: List[Message], options: CompletionOptions) -> CompletionResult:
        start_time = time.time()
        chunks = []
        full_content = ""
        tool_calls = []
        usage = None
        finish_reason = "stop"
        error = None

        try:
            async for chunk in self.stream_complete(messages, options):
                chunks.append(chunk)
                full_content += chunk.content
                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)
                if chunk.usage:
                    usage = chunk.usage
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
        except Exception as e:
            error = str(e)
            finish_reason = "error"

        latency_ms = (time.time() - start_time) * 1000

        return CompletionResult(
            content=full_content,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            usage=usage,
            model=options.model,
            provider=self.name,
            chunks=chunks,
            error=error,
            latency_ms=latency_ms
        )

    async def stream_complete(self, messages: List[Message], options: CompletionOptions) -> AsyncGenerator[CompletionChunk, None]:
        session = self._get_session()
        payload = {
            "model": options.model,
            "messages": self._format_messages(messages),
            "stream": True,
            "options": {
                "temperature": options.temperature,
                "num_predict": options.max_tokens,
                "top_p": options.top_p,
                "stop": options.stop,
            },
        }

        # Add tools if provided
        if options.tools:
            payload["tools"] = [self._format_tool(t) for t in options.tools]
            payload["tool_choice"] = options.tool_choice

        # Add extra params
        payload.update(options.extra_params)

        async with session.post(f"{self.base_url}/api/chat", json=payload) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"Ollama API error {resp.status}: {error_text}")

            async for line in resp.content:
                line = line.decode('utf-8').strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                content = data.get('message', {}).get('content', '')
                tool_calls = []

                if 'tool_calls' in data.get('message', {}):
                    for tc in data['message']['tool_calls']:
                        tool_calls.append(ToolCall(
                            id=tc.get('id', str(uuid.uuid4())[:8]),
                            name=tc['function']['name'],
                            arguments=tc['function']['arguments']
                        ))

                finish_reason = None
                if data.get('done', False):
                    finish_reason = data.get('done_reason', 'stop')

                usage = None
                if 'prompt_eval_count' in data or 'eval_count' in data:
                    usage = {
                        'prompt_tokens': data.get('prompt_eval_count', 0),
                        'completion_tokens': data.get('eval_count', 0),
                        'total_tokens': data.get('prompt_eval_count', 0) + data.get('eval_count', 0)
                    }

                yield CompletionChunk(
                    content=content,
                    finish_reason=finish_reason,
                    tool_calls=tool_calls,
                    usage=usage,
                    model=options.model,
                    provider=self.name
                )

    def _format_tool(self, tool: ToolDefinition) -> Dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters
            }
        }


class OpenAICompatibleProvider(AIProvider):
    """OpenAI-compatible API provider (Groq, OpenRouter, LM Studio, etc.)"""

    def __init__(self, config: 'AIProviderConfig'):
        super().__init__(config)
        self.base_url = config.base_url.rstrip('/')
        self.api_key = config.api_key or os.environ.get('OPENAI_API_KEY', '')

    async def initialize(self) -> bool:
        try:
            await self._fetch_models()
            return True
        except Exception as e:
            logger.warning(f"Failed to fetch models for {self.name}: {e}")
            # Try to use configured models
            self._available_models = self.config.models or []
            return len(self._available_models) > 0

    async def _fetch_models(self):
        session = self._get_session()
        headers = self._get_headers()
        url = f"{self.base_url}/models" if not self.base_url.endswith('/models') else self.base_url

        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                models = data.get('data', [])
                self._available_models = [m['id'] for m in models if 'id' in m]
                self._models_fetched = True

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # Add extra headers from config
        extra = self.config.extra_params.get('extra_headers', {})
        for k, v in extra.items():
            # Replace env vars
            if isinstance(v, str) and v.startswith('${') and v.endswith('}'):
                env_var = v[2:-1]
                v = os.environ.get(env_var, '')
            headers[k] = v
        return headers

    async def list_models(self) -> List[str]:
        if not self._models_fetched:
            await self._fetch_models()
        return self._available_models or self.config.models

    async def health_check(self) -> bool:
        try:
            session = self._get_session()
            headers = self._get_headers()
            url = f"{self.base_url}/models" if not self.base_url.endswith('/models') else self.base_url
            async with session.get(url, headers=headers) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _format_messages(self, messages: List[Message]) -> List[Dict]:
        formatted = []
        for msg in messages:
            if msg.role == "tool":
                formatted.append({
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id
                })
            elif msg.role == "assistant" and msg.tool_calls:
                formatted.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments)
                            }
                        }
                        for tc in msg.tool_calls
                    ]
                })
            else:
                formatted.append({
                    "role": msg.role,
                    "content": msg.content
                })
        return formatted

    async def complete(self, messages: List[Message], options: CompletionOptions) -> CompletionResult:
        start_time = time.time()
        chunks = []
        full_content = ""
        tool_calls = []
        usage = None
        finish_reason = "stop"
        error = None

        try:
            async for chunk in self.stream_complete(messages, options):
                chunks.append(chunk)
                full_content += chunk.content
                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)
                if chunk.usage:
                    usage = chunk.usage
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
        except Exception as e:
            error = str(e)
            finish_reason = "error"

        latency_ms = (time.time() - start_time) * 1000

        return CompletionResult(
            content=full_content,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            usage=usage,
            model=options.model,
            provider=self.name,
            chunks=chunks,
            error=error,
            latency_ms=latency_ms
        )

    async def stream_complete(self, messages: List[Message], options: CompletionOptions) -> AsyncGenerator[CompletionChunk, None]:
        session = self._get_session()
        headers = self._get_headers()

        payload = {
            "model": options.model,
            "messages": self._format_messages(messages),
            "temperature": options.temperature,
            "max_tokens": options.max_tokens,
            "top_p": options.top_p,
            "frequency_penalty": options.frequency_penalty,
            "presence_penalty": options.presence_penalty,
            "stream": True,
        }

        if options.stop:
            payload["stop"] = options.stop

        if options.tools:
            payload["tools"] = [self._format_tool(t) for t in options.tools]
            payload["tool_choice"] = options.tool_choice

        payload.update(options.extra_params)

        async with session.post(f"{self.base_url}/chat/completions", json=payload, headers=headers) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"API error {resp.status}: {error_text}")

            async for line in resp.content:
                line = line.decode('utf-8').strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    line = line[6:]

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                choices = data.get('choices', [])
                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get('delta', {})
                content = delta.get('content', '')

                tool_calls = []
                if 'tool_calls' in delta:
                    for tc in delta['tool_calls']:
                        if 'function' in tc:
                            args = tc['function'].get('arguments', '{}')
                            try:
                                arguments = json.loads(args) if isinstance(args, str) else args
                            except json.JSONDecodeError:
                                arguments = {}
                            tool_calls.append(ToolCall(
                                id=tc.get('id', str(uuid.uuid4())[:8]),
                                name=tc['function'].get('name', ''),
                                arguments=arguments
                            ))

                finish_reason = choice.get('finish_reason')
                usage = data.get('usage')

                yield CompletionChunk(
                    content=content,
                    finish_reason=finish_reason,
                    tool_calls=tool_calls,
                    usage=usage,
                    model=options.model,
                    provider=self.name
                )

    def _format_tool(self, tool: ToolDefinition) -> Dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters
            }
        }


class ProviderFactory:
    """Factory for creating AI providers"""

    _providers = {
        'ollama': OllamaProvider,
        'ollama_remote': OllamaProvider,
        'openai_compatible': OpenAICompatibleProvider,
    }

    @classmethod
    def create(cls, config: 'AIProviderConfig') -> AIProvider:
        provider_class = cls._providers.get(config.type)
        if not provider_class:
            raise ValueError(f"Unknown provider type: {config.type}")
        return provider_class(config)

    @classmethod
    def register(cls, type_name: str, provider_class: type):
        cls._providers[type_name] = provider_class