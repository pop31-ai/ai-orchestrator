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

### Windows
```powershell
# Одно касание (PowerShell Admin):
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
irm https://github.com/pop31-ai/ai-orchestrator/releases/latest/download/install.ps1 | iex

# Или вручную:
.\installers\install.ps1                           # Интерактивно
.\installers\install.ps1 -InstallOllama -PullModel  # С Ollama
```

### Linux / Astra Linux
```bash
# curl одной строкой:
bash <(curl -fsSL https://github.com/pop31-ai/ai-orchestrator/raw/main/installers/linux/install.sh)

# Или .deb пакет:
bash installers/linux/build-deb.sh
sudo dpkg -i installers/linux/dist/ai-orchestrator_1.0.0_all.deb

# systemd сервис:
systemctl --user start ai-orchestrator   # http://localhost:8080
```

### Android 8 / 11+

**Готовый APK:** Скачайте из [Releases](https://github.com/pop31-ai/ai-orchestrator/releases):
- `AI-Orchestrator-android8-release.apk` — Android 8 (API 26) +
- `AI-Orchestrator-android11-release.apk` — Android 11 (API 30) +

**Сборка APK из исходников:**
```bash
# Требуется: Android SDK, JDK 17, Gradle 8.5

# Linux:
bash installers/android/apk/build-apk.sh release

# Windows PowerShell:
.\installers\android\apk\build-apk.ps1 -Release

# Docker:
cd installers/android/apk
docker build -t ai-orchestrator-apk .
docker run --rm -v $(pwd)/dist:/app/dist ai-orchestrator-apk
```

**GitHub Actions:** Автосборка при пуше тега `v*`. Скачать APK → Actions → Build APK → Artifacts.

**Установка через Termux (альтернатива):**
```bash
# В Termux (F-Droid):
pkg install curl -y
curl -fsSL https://github.com/pop31-ai/ai-orchestrator/raw/main/installers/android/install-termux.sh | bash

# Автозапуск:
bash installers/android/termux-autostart.sh chat   # чат при старте
bash installers/android/termux-autostart.sh serve  # сервер в фоне
```

### pip (любая платформа)
```bash
git clone https://github.com/pop31-ai/ai-orchestrator
cd ai-orchestrator
pip install -e .
```

### Pull free AI models

### Вариант 1: Одно касание (рекомендуется)
```powershell
# Откройте PowerShell от имени администратора и выполните:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
irm https://github.com/pop31-ai/ai-orchestrator/releases/latest/download/install.ps1 | iex
```
Или вручную:
```powershell
.\installers\install.ps1                           # Интерактивная установка
.\installers\install.ps1 -InstallOllama -PullModel  # С Ollama и моделью
.\installers\install.ps1 -NoPath -NoContextMenu     # Без интеграции в систему
```
Скрипт сам установит Python (если нет), создаст venv, добавит в PATH, добавит пункт в контекстное меню.

### Вариант 2: Inno Setup (exe-инсталятор)
Скачайте `AI-Orchestrator-1.0.0-Setup.exe` из [Release](https://github.com/pop31-ai/ai-orchestrator/releases) и запустите.

Сборка из исходников:
```powershell
.\installers\build.ps1              # Собрать все пакеты
.\installers\build.ps1 -SkipInno    # Только ZIP (без Inno Setup)
```
Требуется [Inno Setup 6](https://jrsoftware.org/isdl.php): `winget install JRSoftware.InnoSetup`

### Вариант 3: pip / ручная установка
```bash
git clone https://github.com/pop31-ai/ai-orchestrator
cd ai-orchestrator
pip install -e .
```

После установки:
```bash
ai-orchestrator chat             # Интерактивный чат
ai-orchestrator providers        # Список провайдеров
ai-orchestrator config           # Показать конфиг
```

### Pull free AI models
```bash
# Установите Ollama и скачайте бесплатные модели:
ollama pull qwen2.5:1.5b         # 1.1 GB — быстрый чат
ollama pull phi3.5:3.8b          # 2.2 GB — общая
ollama pull qwen2.5-coder:7b     # 4.7 GB — код
```

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
├── __init__.py          # Пакет, public API
├── __main__.py          # CLI точка входа (click)
├── config.py            # Конфигурация (провайдеры, агент, история, UI)
├── providers.py         # Абстракции AI-провайдеров (Ollama, OpenAI)
├── agent.py             # Система агентов, инструменты, оркестрация
├── orchestrator.py      # Главный класс приложения AIOrchestrator
├── history.py           # История (SQLite), виртуальный скролл
├── tools/
│   └── __init__.py      # Встроенные инструменты (shell, файлы, grep)

installers/
├── install.ps1                  # Установка одним скриптом
├── build.ps1                    # Сборка инсталятора
├── ai-orchestrator-installer.iss # Inno Setup скрипт
├── ai-orchestrator.bat          # Быстрый запуск
├── launch.bat / launch.ps1      # Лаунчеры с venv
├── install_deps.ps1             # Установка зависимостей
├── windows-integration.ps1      # PATH + контекстное меню + Terminal
├── terminal-profile.json        # Профиль Windows Terminal
└── generate-icon.ps1            # Генерация иконки
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

## Windows Integration

После установки доступны:

**Контекстное меню:** ПКМ в любой папке → "AI Orchestrator chat"

**PATH:** Команда `ai-orchestrator` доступна из любого терминала

**Windows Terminal:** Профиль "AI Orchestrator" в выпадающем списке

```powershell
# Добавить в PATH
.\installers\windows-integration.ps1 -AddToPath

# Добавить контекстное меню
.\installers\windows-integration.ps1 -AddContextMenu

# Добавить профиль Terminal
.\installers\windows-integration.ps1 -AddTerminalProfile

# Удалить
.\installers\windows-integration.ps1 -RemoveFromPath -RemoveContextMenu
```

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