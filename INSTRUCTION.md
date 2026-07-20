# Инструкция по запуску AI Orchestrator (offline)

## Что уже есть
- **Python 3.12** установлен глобально
- **Все пакеты** установлены: ctransformers, aiohttp, rich, click, huggingface_hub
- **5 моделей TinyLlama GGUF** скачаны и закешированы (offline)
- **Исходный код** в папке `C:\Users\e\Desktop\4a`

## Быстрый старт

Откройте PowerShell (Win+R → `powershell` → Enter) и выполните:

```powershell
cd C:\Users\e\Desktop\4a
```

### 1. Задать вопрос одной строкой
```powershell
python -m ai_orchestrator ask "Напиши hello world на Python"
```
Ответ выводится сразу, программа завершается.

### 2. Интерактивный чат
```powershell
python -m ai_orchestrator chat
```
Нажмите `Ctrl+C` для выхода.

### 3. Desktop-режим (все персонажи)
```powershell
python -m ai_orchestrator desktop
```
Откроется браузер с веб-интерфейсом: http://127.0.0.1:8080/

Можно писать команды прямо в чате. Персонажи могут использовать `CMD: dir C:\` для выполнения shell-команд. Результат подставляется в ответ.

### 4. HTTP-сервер (для Android APK)
```powershell
python -m ai_orchestrator serve
```

### 5. Список доступных провайдеров
```powershell
python -m ai_orchestrator providers
```

## Провайдеры (выбор модели)

### TinyLlama 1.1B (все 5 работают offline, без скачивания)

| Имя в CLI | Имя в web UI | Размер | Память |
|----------|-------------|--------|--------|
| local_tinyllama (по умолч.) | Assistant | 750 MB | ~800 MB |
| local_tinyllama_q2 | Speedy | 461 MB | ~500 MB |
| local_tinyllama_q3 | Thinker | 638 MB | ~700 MB |
| local_tinyllama_q5 | Analyst | 1.1 GB | ~1.2 GB |
| local_tinyllama_q8 | Scholar | 1.3 GB | ~1.4 GB |

### Mistral 7B (скачивается при первом запуске, ~4.1GB)

| Имя в CLI | Имя в web UI | Размер | Память |
|----------|-------------|--------|--------|
| local_mistral7b | Mistral | 4.1 GB | ~4.5 GB |

Mistral 7B — **понимает команды и делегирование**. После скачивания:

```powershell
# Спросить через Mistral с выполнением команд
python -m ai_orchestrator ask -p local_mistral7b "проверь свободное место на диске C:"

# Или в desktop-режиме просто написать в чат
```

### Как скачать Mistral
Нажми **Download** на карточке Mistral в веб-интерфейсе, или вручную:
```powershell
python -c "from huggingface_hub import hf_hub_download; hf_hub_download('MaziyarPanahi/Mistral-7B-Instruct-v0.3-GGUF', 'Mistral-7B-Instruct-v0.3.Q4_K_M.gguf')"
```

## Команды в чате (CMD:)

В desktop-режиме персонажи могут выполнять shell-команды. Напишите в чат "проверь диск C:" — если персонаж сгенерирует `CMD: dir C:\`, команда выполнится автоматически.

Mistral 7B делает это стабильнее всех. TinyLlama — через раз.

## Если что-то сломалось

```powershell
# Проверить, что Python работает
python --version

# Проверить, что все пакеты на месте
pip list | findstr "ctransformers aiohttp rich click huggingface"

# Проверить, что модель есть в кеше
dir $env:USERPROFILE\.cache\huggingface\hub\ -Recurse -Filter *.gguf

# Переустановить пакет (если нужно)
pip install -e C:\Users\e\Desktop\4a

# Посмотреть логи
python -m ai_orchestrator ask -v "test"
```

## Важно
- **Не нужен интернет** — модели загружаются с диска (кроме первого скачивания Qwen)
- **Не нужны API-ключи** — всё локально
- Работает из любой папки, если предварительно выполнить `cd C:\Users\e\Desktop\4a`
