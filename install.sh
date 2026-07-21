#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# install.sh — Полная установка AI Orchestrator на Termux (Android)
# Full install of AI Orchestrator on Termux (Android)
# =============================================================================
# Устанавливает Python, зависимости, скачивает TinyLlama GGUF,
# клонирует проект и запускает сервер.
# Installs Python, deps, downloads TinyLlama GGUF,
# clones project and starts server.
# =============================================================================

set -euo pipefail

# --- Переменные / Variables ---
INSTALL_DIR="$HOME/ai_orchestrator"
MODEL_DIR="$HOME/.cache/ctransformers"
LOG_FILE="$HOME/.cache/orchestrator.log"
MODEL_NAME="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
MODEL_REPO="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF"
# HuggingFace mirror for regions with access issues
HF_MIRROR="${HF_MIRROR:-https://huggingface.co}"
PORT="${PORT:-8080}"
PYTHON_MIN_VERSION="3.10"

# --- Цвета / Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# --- Функции / Functions ---

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

cleanup() {
    # Очистка при ошибке / Cleanup on error
    local code=$?
    if [ $code -ne 0 ]; then
        err "Установка прервана (код $code) / Install aborted (code $code)"
        err "См. логи: $LOG_FILE / See logs: $LOG_FILE"
    fi
}
trap cleanup EXIT

check_termux() {
    # Проверяем что запущено в Termux / Verify running in Termux
    if [ ! -d "/data/data/com.termux" ] && [ -z "${TERMUX_VERSION:-}" ]; then
        warn "Этот скрипт предназначен для Termux. Продолжаем... / This script is for Termux. Continuing..."
    fi
}

check_installed() {
    # Проверяем, уже ли установлена система / Check if already installed
    if [ -d "$INSTALL_DIR/ai_orchestrator" ] && [ -f "$INSTALL_DIR/ai_orchestrator/agentic_chat.py" ]; then
        return 0
    fi
    return 1
}

install_system_packages() {
    info "Обновление пакетов Termux / Updating Termux packages..."
    pkg update -y 2>&1 | tail -1 >> "$LOG_FILE"
    pkg upgrade -y 2>&1 | tail -1 >> "$LOG_FILE"

    info "Установка Python 3.11, pip, git / Installing Python 3.11, pip, git..."
    for pkg in python git wget; do
        if ! command -v "$pkg" &>/dev/null && [ "$pkg" != "python" ] || \
           ! python3 --version &>/dev/null 2>&1; then
            pkg install -y "$pkg" 2>&1 | tail -1 >> "$LOG_FILE"
        fi
    done

    # Убедимся что Python доступен / Ensure Python is available
    if ! command -v python3 &>/dev/null; then
        err "Не удалось установить Python / Failed to install Python"
        exit 1
    fi

    # Симлинки для удобства / Symlinks for convenience
    if ! command -v python &>/dev/null; then
        ln -sf "$(command -v python3)" "$PREFIX/bin/python" 2>/dev/null || true
    fi
    if ! command -v pip &>/dev/null; then
        ln -sf "$(command -v pip3 2>/dev/null || echo "$PREFIX/bin/pip3")" "$PREFIX/bin/pip" 2>/dev/null || true
    fi

    ok "Python: $(python3 --version 2>&1)"
    ok "pip: $(pip --version 2>&1 | head -1)"
    ok "git: $(git --version 2>&1)"
}

install_pip_packages() {
    info "Установка Python-пакетов / Installing Python packages..."

    # Обновляем pip / Update pip
    pip install --upgrade pip setuptools wheel 2>&1 | tail -1 >> "$LOG_FILE"

    # Основные зависимости / Core dependencies
    local core_pkgs=(
        "aiohttp"
        "requests"
        "fpdf2"
        "Pillow"
    )

    # Пакеты для локальной LLM / Local LLM packages
    # llama-cpp-python более стабилен в Termux чем ctransformers
    local llm_pkgs=(
        "llama-cpp-python"
    )

    # Дополнительные пакеты / Optional packages
    local extra_pkgs=(
        "numpy"
        "scipy"
    )

    info "Установка базовых пакетов / Installing base packages..."
    pip install "${core_pkgs[@]}" 2>&1 | tail -3 >> "$LOG_FILE"

    info "Установка llama-cpp-python для Termux (это может занять время) / Installing llama-cpp-python for Termux (may take a while)..."
    if ! python3 -c "import llama_cpp" 2>/dev/null; then
        # Сначала пробуем установить из бинарников / Try binary first
        if ! pip install llama-cpp-python 2>> "$LOG_FILE"; then
            warn "Бинарник недоступен, собираем из исходников / Binary unavailable, building from source..."
            # Для Termux может потребоваться установить сборочные зависимости
            pkg install -y cmake build-essential 2>&1 | tail -1 >> "$LOG_FILE" || true
            CMAKE_ARGS="-DLLAMA_NATIVE=ON" pip install llama-cpp-python --no-cache-dir 2>&1 | tail -3 >> "$LOG_FILE"
        fi
    fi

    info "Установка дополнительных пакетов / Installing extra packages..."
    pip install "${extra_pkgs[@]}" 2>&1 | tail -1 >> "$LOG_FILE"

    ok "Все Python-пакеты установлены / All Python packages installed"
}

create_directories() {
    info "Создание директорий / Creating directories..."
    mkdir -p "$MODEL_DIR"
    mkdir -p "$HOME/.cache"
    ok "Директории созданы / Directories created"
}

download_model() {
    info "Проверка модели TinyLlama / Checking TinyLlama model..."

    local model_path="$MODEL_DIR/$MODEL_NAME"

    if [ -f "$model_path" ]; then
        local size
        size=$(stat -c%s "$model_path" 2>/dev/null || stat -f%z "$model_path" 2>/dev/null || echo "0")
        if [ "$size" -gt 100000000 ]; then
            # >100MB — модель уже скачана / Model already downloaded
            ok "Модель уже скачана: $model_path ($size bytes) / Model already downloaded"
            return 0
        fi
        warn "Модель повреждена ($size bytes), перекачиваем... / Model corrupted ($size bytes), re-downloading..."
        rm -f "$model_path"
    fi

    info "Скачивание TinyLlama 1.1B Chat Q4_K_M (~669 MB) / Downloading TinyLlama 1.1B Chat Q4_K_M (~669 MB)..."
    info "Это может занять 5-15 минут в зависимости от сети / This may take 5-15 min depending on connection..."
    echo ""

    # Пробуем huggingface-cli / Try huggingface-cli first
    if command -v huggingface-cli &>/dev/null || pip show huggingface-hub &>/dev/null 2>&1; then
        info "Скачивание через huggingface-hub / Downloading via huggingface-hub..."
        python3 -c "
from huggingface_hub import hf_hub_download
path = hf_hub_download(
    '$MODEL_REPO',
    '$MODEL_NAME',
    cache_dir='$MODEL_DIR'
)
print(f'Downloaded to: {path}')
# Создаём симлинк для удобства / Create symlink for convenience
import os, shutil
target = '$model_path'
if not os.path.exists(target):
    os.symlink(path, target)
print(f'Linked: {target}')
" 2>> "$LOG_FILE" && { ok "Модель скачана через huggingface-hub / Model downloaded via huggingface-hub"; return 0; }
        warn "huggingface-hub не сработал, пробуем wget... / huggingface-hub failed, trying wget..."
    fi

    # Fallback: прямое скачивание wget / Fallback: direct wget download
    local url="${HF_MIRROR}/${MODEL_REPO}/resolve/main/${MODEL_NAME}"
    info "Прямое скачивание: $url / Direct download: $url"

    if wget --progress=bar:force:noscroll -O "$model_path" "$url" 2>&1 | tail -5; then
        ok "Модель скачана через wget / Model downloaded via wget"
    else
        err "Не удалось скачать модель / Failed to download model"
        err "Попробуйте вручную: wget -O $model_path $url"
        err "Or set HF_MIRROR to a mirror URL and re-run"
        return 1
    fi

    # Проверка размера / Check size
    local size
    size=$(stat -c%s "$model_path" 2>/dev/null || stat -f%z "$model_path" 2>/dev/null || echo "0")
    if [ "$size" -lt 100000000 ]; then
        err "Скачанный файл слишком мал ($size bytes). Возможно, ошибка / Downloaded file too small ($size bytes). Likely error."
        rm -f "$model_path"
        return 1
    fi
    ok "Модель: $model_path ($size bytes)"
}

setup_project() {
    info "Получение проекта / Setting up project..."

    if check_installed; then
        info "Проект уже установлен, обновляем / Project already installed, updating..."
        cd "$INSTALL_DIR"
        git pull 2>&1 | tail -3 >> "$LOG_FILE" || warn "git pull failed, continuing..."
        return 0
    fi

    # Клонируем или копируем / Clone or copy
    local remote_url="${GIT_REPO:-}"

    if [ -n "$remote_url" ]; then
        info "Клонирование из $remote_url / Cloning from $remote_url..."
        git clone "$remote_url" "$INSTALL_DIR" 2>> "$LOG_FILE"
    elif [ -d "$(dirname "$0")/ai_orchestrator" ]; then
        # Скрипт запущен из папки проекта — копируем / Script run from project dir — copy
        info "Копирование проекта из текущей директории / Copying project from current directory..."
        local src_dir
        src_dir="$(cd "$(dirname "$0")" && pwd)"
        mkdir -p "$INSTALL_DIR"
        cp -r "$src_dir"/* "$INSTALL_DIR/" 2>/dev/null || true
        cp -r "$src_dir"/.git "$INSTALL_DIR/" 2>/dev/null || true
    else
        # Клонируем из предполагаемого репозитория / Clone from assumed repository
        warn "Исходный код не найден рядом со скриптом. Клонируем из GitHub..."
        warn "Source code not found near script. Cloning from GitHub..."
        git clone "https://github.com/anomalyco/opencode" "$INSTALL_DIR" 2>> "$LOG_FILE" || {
            err "Не удалось клонировать. Укажите GIT_REPO=<url> / Clone failed. Set GIT_REPO=<url>"
            return 1
        }
    fi

    cd "$INSTALL_DIR"

    ok "Проект установлен в $INSTALL_DIR / Project installed to $INSTALL_DIR"
}

create_model_config() {
    # Создаём файл конфигурации модели для llama-cpp-python
    # Create model config for llama-cpp-python
    info "Настройка конфигурации модели / Setting up model config..."

    local config_file="$INSTALL_DIR/.model_config"
    cat > "$config_file" << EOF
# Конфигурация модели для AI Orchestrator (Termux)
# Model config for AI Orchestrator (Termux)
MODEL_BACKEND=llama-cpp
MODEL_PATH=$MODEL_DIR/$MODEL_NAME
MODEL_TYPE=llama
N_CTX=2048
N_THREADS=4
EOF

    ok "Конфигурация модели создана / Model config created"
}

setup_environment() {
    info "Настройка переменных окружения / Setting up environment..."

    local env_file="$HOME/.orchestrator_env"

    cat > "$env_file" << 'ENVEOF'
# AI Orchestrator — Termux environment / Переменные окружения
export OPCODE_LLM_MODEL="tinyllama"
export PYTHONUNBUFFERED="1"
# For llama-cpp-python backend (replaces ctransformers on Termux):
export LLAMA_CPP_MODEL_PATH="$HOME/.cache/ctransformers/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
ENVEOF

    ok "Файл окружения создан: $env_file / Environment file created: $env_file"
}

print_summary() {
    echo ""
    echo -e "${GREEN}=============================================${NC}"
    echo -e "${GREEN}  Установка завершена! / Installation complete!${NC}"
    echo -e "${GREEN}=============================================${NC}"
    echo ""
    echo -e "  Директория: ${CYAN}$INSTALL_DIR${NC}"
    echo -e "  Модель:     ${CYAN}$MODEL_DIR/$MODEL_NAME${NC}"
    echo -e "  Логи:       ${CYAN}$LOG_FILE${NC}"
    echo -e "  Порт:       ${CYAN}$PORT${NC}"
    echo ""
    echo -e "  Запуск / Start:"
    echo -e "    ${YELLOW}cd $INSTALL_DIR && python ai_orchestrator/agentic_chat.py${NC}"
    echo ""
    echo -e "  Или используйте / Or use:"
    echo -e "    ${YELLOW}bash $(dirname "$0")/start_termux.sh${NC}"
    echo ""
    echo -e "  Откройте в браузере / Open in browser:"
    echo -e "    ${CYAN}http://127.0.0.1:$PORT${NC}"
    echo ""
}

# --- Основной поток / Main flow ---

main() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║  AI Orchestrator — Установка для Termux       ║${NC}"
    echo -e "${CYAN}║  AI Orchestrator — Termux Installer           ║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════╝${NC}"
    echo ""

    # Лог-файл / Log file
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "=== Installation started: $(date) ===" > "$LOG_FILE"

    # Проверка: уже установлено? / Already installed?
    if check_installed; then
        ok "Проект уже установлен! / Project already installed!"
        info "Для перезапуска используйте start_termux.sh / Use start_termux.sh to restart"
        info "Для переустановки удалите $INSTALL_DIR / To reinstall, delete $INSTALL_DIR"
        echo ""
        info "Запускаем сервер... / Starting server..."
        cd "$INSTALL_DIR"

        # Загружаем окружение / Load environment
        [ -f "$HOME/.orchestrator_env" ] && source "$HOME/.orchestrator_env"

        nohup python3 ai_orchestrator/agentic_chat.py >> "$LOG_FILE" 2>&1 &
        local pid=$!
        ok "Сервер запущен (PID: $pid) / Server started (PID: $pid)"
        ok "Логи: $LOG_FILE / Logs: $LOG_FILE"
        ok "Откройте http://127.0.0.1:${PORT} в браузере"
        exit 0
    fi

    check_termux
    install_system_packages
    install_pip_packages
    create_directories
    download_model
    setup_project
    create_model_config
    setup_environment
    print_summary

    # Автозапуск сервера / Auto-start server
    read -r -p "Запустить сервер сейчас? / Start server now? [Y/n] " answer
    answer=${answer:-Y}
    if [[ "$answer" =~ ^[Yy] ]]; then
        cd "$INSTALL_DIR"
        [ -f "$HOME/.orchestrator_env" ] && source "$HOME/.orchestrator_env"
        nohup python3 ai_orchestrator/agentic_chat.py >> "$LOG_FILE" 2>&1 &
        local pid=$!
        echo ""
        ok "Сервер запущен (PID: $pid) / Server started (PID: $pid)"
        ok "Откройте http://127.0.0.1:${PORT} в браузере / Open in browser"
    fi
}

# Запуск / Run
main "$@"
