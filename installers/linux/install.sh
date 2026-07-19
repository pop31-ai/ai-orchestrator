#!/bin/bash
# AI Orchestrator — установка на Linux (Astra Linux / Debian / Ubuntu)
# Использование:
#   curl -fsSL https://github.com/pop31-ai/ai-orchestrator/releases/.../install.sh | sh
#   или: bash install.sh [--ollama] [--dev]

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[*]${NC} $1"; }
err()  { echo -e "${RED}[!]${NC} $1"; }
step() { echo -e "${CYAN} >>${NC} $1"; }

INSTALL_DIR="/usr/share/ai-orchestrator"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="/usr/bin"
INSTALL_OLLAMA=false
REPO_URL="https://github.com/pop31-ai/ai-orchestrator.git"

# --- Парсинг аргументов ---
for arg in "$@"; do
    case "$arg" in
        --ollama) INSTALL_OLLAMA=true ;;
        --dev)    DEV_MODE=true ;;
    esac
done

# --- 1. Проверка ---
step "Проверка системы..."
OS_ID=$(grep -oP '(?<=^ID=).+' /etc/os-release 2>/dev/null || echo "linux")
OS_VER=$(grep -oP '(?<=^VERSION_ID=).+' /etc/os-release 2>/dev/null || echo "?")
log "ОС: $OS_ID $OS_VER"

if [ "$(id -u)" -ne 0 ]; then
    err "Запустите с sudo: sudo bash install.sh"
    exit 1
fi

# --- 2. Зависимости ---
step "Установка зависимостей..."
if command -v apt &>/dev/null; then
    apt update -qq
    apt install -y -qq python3 python3-pip python3-venv git curl 2>/dev/null
elif command -v dnf &>/dev/null; then
    dnf install -y python3 python3-pip git curl
elif command -v pacman &>/dev/null; then
    pacman -Sy --noconfirm python python-pip git curl
fi
log "Python: $(python3 --version 2>&1)"

# --- 3. Клонирование / копирование ---
step "Установка приложения..."
mkdir -p "$INSTALL_DIR"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/../pyproject.toml" ]; then
    # Установка из локального репозитория
    cp -r "$SCRIPT_DIR/../"* "$INSTALL_DIR/" 2>/dev/null || true
    log "Файлы скопированы из $SCRIPT_DIR"
else
    # Установка с GitHub
    git clone --depth 1 "$REPO_URL" /tmp/ai-orchestrator 2>/dev/null || {
        err "Не удалось клонировать репозиторий"
        exit 1
    }
    cp -r /tmp/ai-orchestrator/* "$INSTALL_DIR/"
    rm -rf /tmp/ai-orchestrator
    log "Репозиторий склонирован"
fi

# --- 4. Виртуальное окружение ---
step "Создание виртуального окружения..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR" -q
log "Зависимости установлены"

# --- 5. Симлинк ---
step "Добавление в PATH..."
ln -sf "$INSTALL_DIR/venv/bin/ai-orchestrator" "$BIN_DIR/ai-orchestrator" 2>/dev/null || true
chmod +x "$INSTALL_DIR/venv/bin/ai-orchestrator" 2>/dev/null || true
log "Команда 'ai-orchestrator' доступна"

# --- 6. systemd сервис ---
step "Настройка systemd сервиса..."
mkdir -p /usr/lib/systemd/user /usr/lib/systemd/system
cp "$INSTALL_DIR/installers/linux/usr/lib/systemd/user/ai-orchestrator.service" \
   /usr/lib/systemd/user/ai-orchestrator.service 2>/dev/null || true
cp "$INSTALL_DIR/installers/linux/usr/lib/systemd/system/ai-orchestrator@.service" \
   /usr/lib/systemd/system/ai-orchestrator@.service 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true
log "systemd сервис установлен"

# --- 7. Десктоп ---
step "Десктоп интеграция..."
mkdir -p /usr/share/applications /usr/share/icons/hicolor/256x256/apps
cp "$INSTALL_DIR/installers/linux/usr/share/applications/ai-orchestrator.desktop" \
   /usr/share/applications/ 2>/dev/null || true
update-desktop-database 2>/dev/null || true
log "Десктоп файл установлен"

# --- 8. Ollama (опционально) ---
if [ "$INSTALL_OLLAMA" = true ]; then
    step "Установка Ollama..."
    if command -v ollama &>/dev/null; then
        log "Ollama уже установлен: $(ollama --version 2>&1)"
    else
        curl -fsSL https://ollama.com/install.sh | sh
        log "Ollama установлен"
    fi

    step "Скачивание бесплатной модели qwen2.5:1.5b..."
    ollama pull qwen2.5:1.5b &
    log "Модель скачивается в фоне"
fi

# --- 9. Директории данных ---
mkdir -p /etc/ai-orchestrator /var/lib/ai-orchestrator /var/log/ai-orchestrator

# --- 10. Тест ---
step "Проверка..."
"$VENV_DIR/bin/python" -c "from ai_orchestrator import AIOrchestrator; print('OK')" 2>&1 && \
    log "Установка проверена!" || \
    warn "Проверка не удалась"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN} AI Orchestrator установлен!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "  ${CYAN}ai-orchestrator chat${NC}              Интерактивный чат"
echo -e "  ${CYAN}ai-orchestrator ask${NC} 'привет'      Один вопрос"
echo -e "  ${CYAN}ai-orchestrator providers${NC}         Список провайдеров"
echo ""
echo -e "  ${YELLOW}Веб-сервер:${NC}"
echo -e "    systemctl --user start ai-orchestrator"
echo -e "    http://localhost:8080"
echo ""
echo -e "  ${YELLOW}Если Ollama не запущен:${NC}"
echo -e "    ollama serve"
echo -e "    ollama pull qwen2.5:1.5b"