#!/bin/bash
# build-apk.sh — сборка APK для Android 8 и 11
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/dist"
BUILD_TYPE="${1:-debug}"  # debug или release
FLAVORS="${2:-android8 android11}"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $1"; }
step() { echo -e "${CYAN} >>${NC} $1"; }
err()  { echo -e "${RED}[!]${NC} $1"; }

mkdir -p "$OUTPUT_DIR"

# --- 1. Проверка Gradle ---
if [ ! -f "$SCRIPT_DIR/gradlew" ]; then
    step "Downloading Gradle wrapper..."
    cd "$SCRIPT_DIR"
    gradle wrapper --gradle-version 8.5 2>/dev/null || {
        curl -sL "https://services.gradle.org/distributions/gradle-8.5-bin.zip" -o /tmp/gradle.zip
        unzip -q /tmp/gradle.zip -d /tmp/gradle-8.5
        export PATH="/tmp/gradle-8.5/gradle-8.5/bin:$PATH"
    }
fi

# --- 2. ANDROID_HOME ---
if [ -z "${ANDROID_HOME:-}" ]; then
    for dir in "$HOME/Android/Sdk" "/opt/android-sdk" "/usr/lib/android-sdk"; do
        if [ -d "$dir" ]; then
            export ANDROID_HOME="$dir"
            break
        fi
    done
fi

if [ -z "${ANDROID_HOME:-}" ]; then
    err "ANDROID_HOME not set. Install Android SDK:"
    err "  apt install android-sdk"
    err "  or: https://developer.android.com/studio#command-tools"
    exit 1
fi
log "Android SDK: $ANDROID_HOME"

# --- 3. Установка SDK компонентов (если нет) ---
if [ ! -d "$ANDROID_HOME/platforms/android-34" ]; then
    step "Installing Android SDK platform 34..."
    yes | "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" \
        "platforms;android-34" "build-tools;34.0.0" 2>/dev/null || true
fi

# --- 4. Сборка ---
GRADLE="${GRADLE:-$SCRIPT_DIR/gradlew}"
cd "$SCRIPT_DIR"

for flavor in $FLAVORS; do
    step "Building $flavor ($BUILD_TYPE)..."
    
    if [ "$BUILD_TYPE" = "release" ]; then
        $GRADLE "assemble${flavor^}Release" --daemon --no-daemon
    else
        $GRADLE "assemble${flavor^}Debug" --daemon --no-daemon
    fi

    # Копирование APK
    apks=$(find "$SCRIPT_DIR/app/build/outputs/apk" -name "*$flavor*$BUILD_TYPE*.apk" 2>/dev/null)
    for apk in $apks; do
        dest="AI-Orchestrator-$flavor-$BUILD_TYPE.apk"
        cp "$apk" "$OUTPUT_DIR/$dest"
        size=$(du -h "$OUTPUT_DIR/$dest" | cut -f1)
        log "$dest ($size)"
    done
done

# --- 5. Подпись (если release) ---
if [ "$BUILD_TYPE" = "release" ] && [ -n "${KEYSTORE_PATH:-}" ]; then
    step "Signing APKs..."
    for apk in "$OUTPUT_DIR"/*-release-unsigned.apk; do
        if [ -f "$apk" ]; then
            jarsigner -verbose -sigalg SHA1withRSA -digestalg SHA1 \
                -keystore "$KEYSTORE_PATH" "$apk" "${KEYSTORE_ALIAS:-ai-orchestrator}"
            log "Signed: $(basename $apk)"
        fi
    done
fi

echo ""
log "Done! APK files in: $OUTPUT_DIR"
ls -lh "$OUTPUT_DIR"/*.apk 2>/dev/null || echo "  (no APK files)"