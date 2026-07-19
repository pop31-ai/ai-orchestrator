# AI Orchestrator

A powerful local AI agent orchestration system that works with free AI models (Ollama, Groq, OpenRouter, etc.) and provides agent capabilities for computer interaction.

## Features

- **Multi-provider support**: Ollama (local), Groq, OpenRouter, LM Studio, llama.cpp, HuggingFace
- **Agent system**: Agents with tool execution (shell, file ops, web search, code execution)
- **Efficient history**: Virtual scrolling, pagination, token-aware context management
- **Model switching**: Hot-swap between providers/models mid-conversation
- **Session management**: Persistent sessions with export/import
- **CLI & API**: Interactive CLI, FastAPI web server, WebSocket support

## Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.ai/) (for local models) or API keys for cloud providers

### Installation

```bash
# Install from source
git clone https://github.com/yourname/ai-orchestrator
cd ai-orchestrator
pip install -e .

# Or install dependencies only
pip install -r requirements.txt
```

### Pull some free models

```bash
# Small fast models
ollama pull qwen2.5:1.5b
ollama pull phi3.5:3.8b
ollama pull gemma2:2b

# Code models
ollama pull qwen2.5-coder:7b
ollama pull deepseek-coder:6.7b
```

### Run the CLI

```bash
ai-orchestrator

# Or with options
ai-orchestrator --provider ollama_local --model qwen2.5:1.5b --debug
```

### Start the web server

```bash
ai-orchestrator serve --port 8080
```

Then open http://localhost:8080

## Configuration

Config file: `~/.ai_orchestrator/config.json`

```json
{
  "active_provider": "ollama_local",
  "default_model": "qwen2.5:1.5b",
  "providers": {
    "ollama_local": {
      "name": "Ollama Local",
      "type": "ollama",
      "base_url": "http://localhost:11434",
      "model": "qwen2.5:1.5b",
      "enabled": true,
      "priority": 10
    },
    "groq": {
      "name": "Groq",
      "type": "openai_compatible",
      "base_url": "https://api.groq.com/openai/v1",
      "api_key": "${GROQ_API_KEY}",
      "model": "llama-3.1-70b-versatile",
      "enabled": false
    }
  }
}
```

Set API keys as environment variables:
```bash
export GROQ_API_KEY=your_key
export OPENROUTER_API_KEY=your_key
export HF_TOKEN=your_token
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/providers` | List providers |
| `/switch <name>` | Switch provider |
| `/models` | List models |
| `/model <name>` | Switch model |
| `/sessions` | List sessions |
| `/session <id>` | Switch session |
| `/new-session` | Create session |
| `/history [page]` | Show history |
| `/search <query>` | Search history |
| `/export [json|md]` | Export session |
| `/config` | Show config |
| `/health` | Health check |
| `/agent <type> [prompt]` | Create agent |

## Architecture

```
ai_orchestrator/
├── config.py          # Configuration management
├── providers.py       # AI provider abstractions
├── agent.py           # Agent orchestration
├── history.py         # History & virtual scrolling
├── tools/             # Built-in tools
│   ├── __init__.py
│   ├── shell.py       # Shell commands
│   ├── file_ops.py    # File read/write/edit
│   └── web.py         # Web search/fetch
├── orchestrator.py    # Main application
├── __main__.py        # CLI entry point
└── api/               # FastAPI web server
    ├── main.py
    ├── routes/
    └── websocket.py
```

## Agent Tools

Built-in tools available to agents:
- `shell` - Execute commands
- `file_read` - Read files
- `file_write` - Write files
- `file_edit` - Edit files
- `file_list` - List directories
- `file_glob` - Find files
- `file_grep` - Search in files

## Web API

Start server: `ai-orchestrator serve`

Endpoints:
- `GET /api/providers` - List providers
- `POST /api/switch_provider` - Switch provider
- `POST /api/chat` - Send message
- `WS /ws/chat/{agent_id}` - Streaming chat
- `GET /api/history/{session_id}` - Get history
- `POST /api/sessions` - Create session

## Performance

- **Virtual scrolling** for 10k+ message histories
- **Token-aware context** management
- **Automatic summarization** for long conversations
- **Async streaming** for real-time responses
- **Connection pooling** for providers

## Free Model Recommendations

| Model | Size | Use Case | Provider |
|-------|------|----------|----------|
| qwen2.5:1.5b | 1.1GB | Fast chat | Ollama |
| phi3.5:3.8b | 2.2GB | General | Ollama |
| gemma2:2b | 1.6GB | General | Ollama |
| qwen2.5-coder:7b | 4.7GB | Coding | Ollama |
| deepseek-coder:6.7b | 4.1GB | Coding | Ollama |
| llama-3.1-8b-instant | API | Fast cloud | Groq |
| mistral-7b-instruct | API | General | OpenRouter |
| qwen2.5-7b-instruct | API | General | OpenRouter |

## License

MIT