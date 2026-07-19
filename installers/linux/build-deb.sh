#!/bin/bash
# build-deb.sh — сборка .deb пакета для Astra Linux / Debian / Ubuntu
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$SCRIPT_DIR/dist"
VERSION="1.0.0"
PACKAGE="ai-orchestrator_${VERSION}_all.deb"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $1"; }
step() { echo -e "${CYAN} >>${NC} $1"; }
err()  { echo -e "${RED}[!]${NC} $1"; }

# --- 1. Подготовка ---
BUILD_DIR="/tmp/ai-orchestrator-deb-build"
DEB_DIR="$BUILD_DIR/ai-orchestrator_${VERSION}_all"

step "Очистка..."
rm -rf "$BUILD_DIR"
mkdir -p "$DEB_DIR/DEBIAN"
mkdir -p "$DEB_DIR/usr/share/ai-orchestrator"
mkdir -p "$DEB_DIR/usr/bin"
mkdir -p "$DEB_DIR/usr/share/applications"
mkdir -p "$DEB_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$DEB_DIR/usr/lib/systemd/user"
mkdir -p "$DEB_DIR/usr/lib/systemd/system"
mkdir -p "$DEB_DIR/etc/ai-orchestrator"

# --- 2. Копирование файлов приложения ---
step "Копирование исходников..."
cp -r "$PROJECT_DIR/ai_orchestrator" "$DEB_DIR/usr/share/ai-orchestrator/ai_orchestrator"
cp "$PROJECT_DIR/pyproject.toml" "$DEB_DIR/usr/share/ai-orchestrator/"
cp "$PROJECT_DIR/requirements.txt" "$DEB_DIR/usr/share/ai-orchestrator/"
cp "$PROJECT_DIR/README.md" "$DEB_DIR/usr/share/ai-orchestrator/"

# --- 3. DEBIAN файлы ---
step "Подготовка DEBIAN control..."
cp "$SCRIPT_DIR/DEBIAN/control" "$DEB_DIR/DEBIAN/control"
cp "$SCRIPT_DIR/DEBIAN/postinst" "$DEB_DIR/DEBIAN/postinst"
cp "$SCRIPT_DIR/DEBIAN/prerm" "$DEB_DIR/DEBIAN/prerm"
cp "$SCRIPT_DIR/DEBIAN/postrm" "$DEB_DIR/DEBIAN/postrm"
cp "$SCRIPT_DIR/DEBIAN/conffiles" "$DEB_DIR/DEBIAN/conffiles"
chmod 755 "$DEB_DIR/DEBIAN/postinst" "$DEB_DIR/DEBIAN/prerm" "$DEB_DIR/DEBIAN/postrm"

# --- 4. Скрипты и сервисы ---
step "Копирование скриптов..."
cp "$SCRIPT_DIR/usr/bin/ai-orchestrator" "$DEB_DIR/usr/bin/ai-orchestrator"
chmod 755 "$DEB_DIR/usr/bin/ai-orchestrator"

cp "$SCRIPT_DIR/usr/share/applications/ai-orchestrator.desktop" \
   "$DEB_DIR/usr/share/applications/ai-orchestrator.desktop"

cp "$SCRIPT_DIR/usr/lib/systemd/user/ai-orchestrator.service" \
   "$DEB_DIR/usr/lib/systemd/user/ai-orchestrator.service"

cp "$SCRIPT_DIR/usr/lib/systemd/system/ai-orchestrator@.service" \
   "$DEB_DIR/usr/lib/systemd/system/ai-orchestrator@.service"

# --- 5. Дефолтный конфиг ---
step "Конфиг..."
cat > "$DEB_DIR/etc/ai-orchestrator/config.json" << 'EOF'
{
  "active_provider": "ollama_local",
  "default_model": "qwen2.5:1.5b",
  "log_level": "INFO",
  "data_dir": "/var/lib/ai-orchestrator"
}
EOF

# --- 6. Сборка ---
step "Сборка .deb пакета..."
mkdir -p "$OUTPUT_DIR"
fakeroot dpkg-deb --build "$DEB_DIR" "$OUTPUT_DIR/$PACKAGE" 2>/dev/null || {
    # fallback без fakeroot
    dpkg-deb --build "$DEB_DIR" "$OUTPUT_DIR/$PACKAGE"
}

# --- 7. Проверка ---
step "Проверка пакета..."
dpkg-deb --info "$OUTPUT_DIR/$PACKAGE" 2>/dev/null | head -5

log "Пакет собран: $OUTPUT_DIR/$PACKAGE"
log "Размер: $(du -h "$OUTPUT_DIR/$PACKAGE" | cut -f1)"

echo ""
echo -e "${GREEN}Установка:${NC}"
echo "  sudo dpkg -i $OUTPUT_DIR/$PACKAGE"
echo "  sudo apt install -f   # если нужны зависимости"