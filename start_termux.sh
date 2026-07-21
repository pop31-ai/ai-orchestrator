#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# start_termux.sh — Быстрый запуск AI Orchestrator на Termux
# Quick launcher for AI Orchestrator on Termux (daily use)
# =============================================================================
# Проверяет зависимости, выводит IP для доступа из браузера,
# запускает сервер с обработкой Ctrl+C.
# Checks deps, prints local IP for browser access,
# starts server with graceful Ctrl+C handling.
# =============================================================================

set -euo pipefail

# --- Переменные / Variables ---
INSTALL_DIR="${ORCHESTRATOR_DIR:-$HOME/ai_orchestrator}"
LOG_FILE="$HOME/.cache/orchestrator.log"
PORT="${PORT:-8080}"
PID_FILE="$HOME/.cache/orchestrator.pid"

# --- Цвета / Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# --- Обработка сигналов / Signal handling ---

cleanup() {
    echo ""
    info "Останавливаем сервер... / Stopping server..."
    if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill -TERM "$SERVER_PID" 2>/dev/null || true
        # Ждём завершения / Wait for exit
        for i in $(seq 1 10); do
            if ! kill -0 "$SERVER_PID" 2>/dev/null; then
                break
            fi
            sleep 0.5
        done
        # Если не завершился — принудительно / Force kill if needed
        if kill -0 "$SERVER_PID" 2>/dev/null; then
            kill -9 "$SERVER_PID" 2>/dev/null || true
        fi
    fi
    # Убираем PID-файл / Clean up PID file
    rm -f "$PID_FILE"
    ok "Сервер остановлен / Server stopped"
    exit 0
}

trap cleanup SIGINT SIGTERM SIGHUP

# --- Проверки / Checks ---

check_python() {
    if ! command -v python3 &>/dev/null; then
        err "Python3 не установлен / Python3 not installed"
        err "Запустите: pkg install python / Run: pkg install python"
        exit 1
    fi

    local ver
    ver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    ok "Python: $ver"

    local major minor
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 10 ]; }; then
        err "Требуется Python 3.10+, установлен $ver / Requires Python 3.10+, found $ver"
        exit 1
    fi
}

check_deps() {
    local missing=()

    # Проверяем Python-модули / Check Python modules
    for mod in aiohttp; do
        if ! python3 -c "import $mod" 2>/dev/null; then
            missing+=("$mod")
        fi
    done

    if [ ${#missing[@]} -gt 0 ]; then
        warn "Отсутствуют пакеты: ${missing[*]} / Missing packages: ${missing[*]}"
        info "Установка... / Installing..."
        pip install "${missing[@]}" 2>&1 | tail -1 >> "$LOG_FILE" || true
    fi

    # Проверяем llama-cpp-python или ctransformers / Check LLM backend
    if python3 -c "import llama_cpp" 2>/dev/null; then
        ok "LLM backend: llama-cpp-python"
    elif python3 -c "import ctransformers" 2>/dev/null; then
        ok "LLM backend: ctransformers"
    else
        warn "LLM-библиотека не найдена — LLM-режим будет недоступен / LLM lib not found — LLM mode unavailable"
        warn "Установите: pip install llama-cpp-python / Install: pip install llama-cpp-python"
    fi
}

check_project() {
    if [ ! -d "$INSTALL_DIR/ai_orchestrator" ]; then
        err "Проект не найден: $INSTALL_DIR/ai_orchestrator / Project not found"
        err "Запустите install.sh для установки / Run install.sh to install"
        exit 1
    fi

    if [ ! -f "$INSTALL_DIR/ai_orchestrator/agentic_chat.py" ]; then
        err "Главный файл не найден / Main file not found"
        exit 1
    fi
}

check_model() {
    local model_dir="$HOME/.cache/ctransformers"
    local found=0

    # Ищем любой .gguf файл / Look for any .gguf file
    for f in "$model_dir"/*.gguf; do
        if [ -f "$f" ]; then
            local size
            size=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo "0")
            if [ "$size" -gt 100000000 ]; then
                ok "Модель найдена: $(basename "$f") ($(( size / 1048576 )) MB) / Model found"
                found=1
                break
            fi
        fi
    done

    if [ "$found" -eq 0 ]; then
        warn "Модель GGUF не найдена в $model_dir / GGUF model not found in $model_dir"
        warn "LLM-режим будет недоступен (инструменты работают) / LLM mode unavailable (tools work)"
    fi
}

is_running() {
    # Проверяем, запущен ли уже сервер / Check if server is already running
    if [ -f "$PID_FILE" ]; then
        local old_pid
        old_pid=$(cat "$PID_FILE")
        if kill -0 "$old_pid" 2>/dev/null; then
            return 0
        fi
        rm -f "$PID_FILE"
    fi
    return 1
}

get_local_ip() {
    # Получаем локальный IP / Get local IP address
    local ip=""

    # Termux: wlan0 / wifi
    if command -v ifconfig &>/dev/null; then
        ip=$(ifconfig wlan0 2>/dev/null | grep 'inet ' | awk '{print $2}' | head -1)
    fi

    # Fallback: hostname -I
    if [ -z "$ip" ] && command -v hostname &>/dev/null; then
        ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi

    # Fallback:ip route
    if [ -z "$ip" ] && command -v ip &>/dev/null; then
        ip=$(ip route get 1 2>/dev/null | awk '{print $7; exit}')
    fi

    # Fallback: parse /proc/net
    if [ -z "$ip" ]; then
        ip=$(awk '/wlan0/{found=1} found && /inet /{print $2; exit}' /proc/net/fib_trie 2>/dev/null)
    fi

    echo "${ip:-127.0.0.1}"
}

print_banner() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║  AI Orchestrator — Termux Launcher             ║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════╝${NC}"
    echo ""
}

# --- Основной поток / Main flow ---

main() {
    print_banner

    # Загружаем окружение / Load environment
    [ -f "$HOME/.orchestrator_env" ] && source "$HOME/.orchestrator_env"

    # Быстрые проверки / Quick checks
    check_python
    check_project
    check_deps
    check_model

    # Проверяем, не запущен ли уже / Check if already running
    if is_running; then
        local old_pid
        old_pid=$(cat "$PID_FILE")
        warn "Сервер уже запущен (PID: $old_pid) / Server already running (PID: $old_pid)"
        local ip
        ip=$(get_local_ip)
        echo ""
        ok "Откройте в браузере / Open in browser:"
        echo -e "    ${CYAN}http://${ip}:${PORT}${NC}"
        echo -e "    ${CYAN}http://127.0.0.1:${PORT}${NC}"
        echo ""
        info "Для перезапуска: kill $old_pid && bash $0"
        exit 0
    fi

    # Получаем IP / Get IP
    local ip
    ip=$(get_local_ip)

    echo ""
    ok "Всё готово / Everything ready!"
    echo ""
    echo -e "  Локальный IP / Local IP:   ${CYAN}${ip}${NC}"
    echo -e "  Порт / Port:                ${CYAN}${PORT}${NC}"
    echo ""
    echo -e "  Откройте в браузере / Open in browser:"
    echo -e "    ${GREEN}http://${ip}:${PORT}${NC}"
    echo -e "    ${GREEN}http://127.0.0.1:${PORT}${NC}"
    echo ""
    echo -e "  ${YELLOW}Нажмите Ctrl+C для остановки / Press Ctrl+C to stop${NC}"
    echo ""

    # Запуск сервера / Start server
    cd "$INSTALL_DIR"

    # Создаём лог-файл / Create log file
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "=== Server started: $(date) ===" >> "$LOG_FILE"

    python3 ai_orchestrator/agentic_chat.py \
        >> "$LOG_FILE" 2>&1 &

    SERVER_PID=$!
    echo "$SERVER_PID" > "$PID_FILE"

    ok "Сервер запущен (PID: $SERVER_PID) / Server started (PID: $SERVER_PID)"
    ok "Логи: $LOG_FILE"

    # Ждём завершения / Wait for completion
    wait "$SERVER_PID" 2>/dev/null || true
    rm -f "$PID_FILE"
}

main "$@"
