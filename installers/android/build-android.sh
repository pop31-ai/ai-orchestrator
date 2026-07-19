#!/bin/bash
# build-android.sh — сборка пакета для Android Termux
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$SCRIPT_DIR/dist"
VERSION="1.0.0"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $1"; }
step() { echo -e "${CYAN} >>${NC} $1"; }

mkdir -p "$OUTPUT_DIR"

step "Создание Termux .deb пакета..."

BUILD_DIR="/tmp/ai-orchestrator-termux"
TERMUX_DIR="$BUILD_DIR/ai-orchestrator_${VERSION}_all"

rm -rf "$BUILD_DIR"
mkdir -p "$TERMUX_DIR/DEBIAN"
mkdir -p "$TERMUX_DIR/data/data/com.termux/files/usr/share/ai-orchestrator"
mkdir -p "$TERMUX_DIR/data/data/com.termux/files/usr/bin"

# --- control для Termux ---
cat > "$TERMUX_DIR/DEBIAN/control" << 'CTRL'
Package: ai-orchestrator
Version: 1.0.0
Section: utils
Priority: optional
Architecture: all
Depends: python (>= 3.10), python-pip, git, curl
Maintainer: pop31-ai
Homepage: https://github.com/pop31-ai/ai-orchestrator
Description: Local AI agent orchestration for Android (Termux)
CTRL

# --- Копирование ---
cp -r "$PROJECT_DIR/ai_orchestrator" "$TERMUX_DIR/data/data/com.termux/files/usr/share/ai-orchestrator/"
cp "$PROJECT_DIR/pyproject.toml" "$TERMUX_DIR/data/data/com.termux/files/usr/share/ai-orchestrator/"
cp "$PROJECT_DIR/requirements.txt" "$TERMUX_DIR/data/data/com.termux/files/usr/share/ai-orchestrator/"

# --- postinst для Termux ---
cat > "$TERMUX_DIR/DEBIAN/postinst" << 'PEOF'
#!/data/data/com.termux/files/usr/bin/bash
set -e
APP_DIR="$PREFIX/share/ai-orchestrator"
VENV_DIR="$APP_DIR/venv"

echo "[*] AI Orchestrator: настройка..."
python -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -e "$APP_DIR" -q

# Симлинк
ln -sf "$VENV_DIR/bin/ai-orchestrator" "$PREFIX/bin/ai-orchestrator"

echo "[+] Установка завершена!"
PEOF
chmod 755 "$TERMUX_DIR/DEBIAN/postinst"

# --- Сборка ---
cd "$BUILD_DIR"
dpkg-deb --build "$TERMUX_DIR" "$OUTPUT_DIR/ai-orchestrator-termux_${VERSION}_all.deb"
log "Termux .deb: $OUTPUT_DIR/ai-orchestrator-termux_${VERSION}_all.deb"

# --- Сборка tar.gz для прямой установки ---
step "Сборка tar.gz..."
TAR_DIR="$BUILD_DIR/ai-orchestrator-tar"
mkdir -p "$TAR_DIR"

cp -r "$PROJECT_DIR/ai_orchestrator" "$TAR_DIR/"
cp "$PROJECT_DIR/pyproject.toml" "$TAR_DIR/"
cp "$PROJECT_DIR/requirements.txt" "$TAR_DIR/"
cp "$SCRIPT_DIR/install-termux.sh" "$TAR_DIR/"
cp "$SCRIPT_DIR/termux-autostart.sh" "$TAR_DIR/"

cd "$BUILD_DIR"
tar czf "$OUTPUT_DIR/ai-orchestrator-termux_${VERSION}.tar.gz" -C "$(dirname "$TAR_DIR")" "ai-orchestrator-tar"
log "tar.gz: $OUTPUT_DIR/ai-orchestrator-termux_${VERSION}.tar.gz"

echo ""
log "Готово! Файлы в $OUTPUT_DIR"