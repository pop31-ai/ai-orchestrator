#!/data/data/com.termux/files/usr/bin/bash
# termux-autostart.sh — автозапуск AI Orchestrator при открытии Termux
#
# Добавляет запуск AI Orchestrator в .bashrc при старте Termux.
# Режимы:
#   1) chat  — сразу открыть чат (по умолчанию)
#   2) serve — запустить веб-сервер в фоне
#   3) off   — отключить автозапуск

set -euo pipefail

MODE="${1:-chat}"
BASHRC="$HOME/.bashrc"
MARKER_BEGIN="# >>> AI Orchestrator autostart"
MARKER_END="# <<< AI Orchestrator autostart"

case "$MODE" in
    chat)
        cat >> "$BASHRC" << 'BASHEOF'

# >>> AI Orchestrator autostart
if command -v ai-orchestrator &>/dev/null && [ -z "$AI_ORCHESTRATOR_STARTED" ]; then
    export AI_ORCHESTRATOR_STARTED=1
    echo ""
    echo "========================================"
    echo "  AI Orchestrator"
    echo "  Введите /help для списка команд"
    echo "  exit — выход в обычный терминал"
    echo "========================================"
    echo ""
    ai-orchestrator chat
fi
# <<< AI Orchestrator autostart
BASHEOF
        echo "[+] Автозапуск чата добавлен в .bashrc"
        ;;

    serve)
        cat >> "$BASHRC" << 'BASHEOF'

# >>> AI Orchestrator autostart
if command -v ai-orchestrator &>/dev/null && [ -z "$AI_ORCHESTRATOR_STARTED" ]; then
    export AI_ORCHESTRATOR_STARTED=1
    nohup ai-orchestrator serve --port 8080 > /dev/null 2>&1 &
    echo "[*] AI Orchestrator сервер запущен на http://localhost:8080"
fi
# <<< AI Orchestrator autostart
BASHEOF
        echo "[+] Автозапуск сервера добавлен в .bashrc"
        ;;

    off|remove)
        sed -i "/$MARKER_BEGIN/,/$MARKER_END/d" "$BASHRC" 2>/dev/null || true
        echo "[+] Автозапуск отключён"
        ;;

    *)
        echo "Использование: termux-autostart.sh [chat|serve|off]"
        exit 1
        ;;
esac

echo "    Перезапустите Termux или выполните: source ~/.bashrc"