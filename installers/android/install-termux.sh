#!/data/data/com.termux/files/usr/bin/bash
# AI Orchestrator — установка на Android (8 / 11+) через Termux
# 
# Требования:
#   - Termux из F-Droid (не Google Play — устаревший)
#   - Android 8 (API 26) или 11+ (API 30)
#   - 500MB+ свободного места
#
# Установка:
#   pkg install curl -y
#   curl -fsSL https://github.com/pop31-ai/ai-orchestrator/raw/main/installers/android/install-termux.sh | bash

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[*]${NC} $1"; }
err()  { echo -e "${RED}[!]${NC} $1"; }
step() { echo -e "${CYAN} >>${NC} $1"; }

ANDROID_SDK=$(getprop ro.build.version.sdk 2>/dev/null || echo "26")
ANDROID_RELEASE=$(getprop ro.build.version.release 2>/dev/null || echo "8")
INSTALL_DIR="$HOME/.local/share/ai-orchestrator"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="$HOME/bin"

log "Android: $ANDROID_RELEASE (API $ANDROID_SDK)"

# Проверка SDK
if [ "$ANDROID_SDK" -lt 26 ]; then
    err "Android 8 (API 26) минимально. Ваша версия: $ANDROID_RELEASE (API $ANDROID_SDK)"
    exit 1
fi

# --- 1. Termux зависимости ---
step "Обновление пакетов..."
pkg update -y -q

step "Установка зависимостей..."
pkg install -y -q python python-pip git curl openssh which

# Для Android 11+ — дополнительные пакеты для работы в фоне
if [ "$ANDROID_SDK" -ge 30 ]; then
    pkg install -y -q termux-services termux-api 2>/dev/null || true
    log "termux-services установлен (фоновый режим)"
fi

log "Python: $(python --version 2>&1)"

# --- 2. Клонирование ---
step "Загрузка AI Orchestrator..."
if [ -d "$INSTALL_DIR" ]; then
    warn "Директория $INSTALL_DIR существует. Обновление..."
    cd "$INSTALL_DIR"
    git pull --ff-only 2>/dev/null || true
else
    git clone --depth 1 https://github.com/pop31-ai/ai-orchestrator.git "$INSTALL_DIR"
fi
log "Репозиторий загружен"

# --- 3. Виртуальное окружение ---
step "Создание виртуального окружения..."
python -m venv "$VENV_DIR" --without-pip
pkg install -y -q python-pip 2>/dev/null || true
"$VENV_DIR/bin/pip" install --upgrade pip -q 2>/dev/null || \
    curl -sS https://bootstrap.pypa.io/get-pip.py | "$VENV_DIR/bin/python"

"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR" -q
log "Зависимости установлены"

# --- 4. Симлинк ---
step "Добавление в PATH..."
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/ai-orchestrator" "$BIN_DIR/ai-orchestrator" 2>/dev/null || true

# Добавить ~/bin в PATH (если ещё не добавлен)
if ! grep -q "export PATH=\"\$HOME/bin" "$HOME/.bashrc" 2>/dev/null; then
    echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.bashrc"
    log "Добавлено в .bashrc"
fi

source "$HOME/.bashrc" 2>/dev/null || true
log "Команда 'ai-orchestrator' доступна"

# --- 5. Ollama для Android (через Termux) ---
step "Проверка Ollama..."
if command -v ollama &>/dev/null; then
    log "Ollama уже установлен"
else
    warn "Ollama для Android: https://github.com/ollama/ollama/issues/1298"
    warn "  Пока нет официальной сборки под Termux."
    warn "  Используйте облачных провайдеров (Groq, OpenRouter) или"
    warn "  Ollama на другом компьютере в сети."
    warn ""
    warn "  Настройка удалённого Ollama:"
    warn "    ai-orchestrator config  → установите base_url вашего сервера"
fi

# --- 6. Настройка для работы в фоне (Android 11+) ---
if [ "$ANDROID_SDK" -ge 30 ]; then
    step "Настройка фонового сервиса..."
    mkdir -p "$PREFIX/var/service/ai-orchestrator/log"
    cat > "$PREFIX/var/service/ai-orchestrator/run" << 'SERVICEEOF'
#!/data/data/com.termux/files/usr/bin/bash
exec 2>&1
cd /data/data/com.termux/files/home/.local/share/ai-orchestrator
exec ./venv/bin/python -m ai_orchestrator serve --port 8080
SERVICEEOF
    chmod +x "$PREFIX/var/service/ai-orchestrator/run"
    log "Сервис для termux-services создан"
    log "  sv up ai-orchestrator    — запустить"
    log "  sv down ai-orchestrator  — остановить"
fi

# --- 7. Тест ---
step "Проверка..."
"$VENV_DIR/bin/python" -c "from ai_orchestrator import AIOrchestrator; print('OK')" 2>&1 && \
    log "Установка проверена!" || \
    warn "Проверка не удалась"

# --- 8. Готово ---
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} AI Orchestrator установлен на Android!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  ${CYAN}ai-orchestrator chat${NC}              Интерактивный чат"
echo -e "  ${CYAN}ai-orchestrator ask${NC} 'привет'      Один вопрос"
echo -e ""
echo -e "  ${YELLOW}Cloud провайдеры (рекомендуется для Android):${NC}"
echo -e "    Groq:       https://console.groq.com/keys"
echo -e "    OpenRouter: https://openrouter.ai/keys"
echo -e ""
echo -e "  Настройка провайдера:"
echo -e "    ai-orchestrator switch openrouter_free"
echo -e "    export OPENROUTER_API_KEY=sk-..."
echo -e ""
echo -e "  ${YELLOW}Советы для Android:${NC}"
echo -e "  • Используйте Termux из F-Droid (не Google Play!)"
echo -e "  • Для работы в фоне: установите Termux:API"
echo -e "  • Для запуска: long-press Home → New session → ai-orchestrator chat"