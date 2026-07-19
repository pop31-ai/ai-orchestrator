#!/bin/bash
# bootstrap-gradle.sh — скачать и установить Gradle wrapper
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GRADLE_VERSION="8.5"

if [ -f "$SCRIPT_DIR/gradlew" ]; then
    echo "[+] Gradle wrapper already exists"
    exit 0
fi

echo "[*] Downloading Gradle $GRADLE_VERSION wrapper..."

# Качаем gradle-wrapper.jar напрямую из репозитория Gradle
JAR_URL="https://raw.githubusercontent.com/gradle/gradle/v$GRADLE_VERSION/gradle/wrapper/gradle-wrapper.jar"
JAR_DEST="$SCRIPT_DIR/gradle/wrapper/gradle-wrapper.jar"

mkdir -p "$SCRIPT_DIR/gradle/wrapper"

if command -v curl &>/dev/null; then
    curl -sL "$JAR_URL" -o "$JAR_DEST"
elif command -v wget &>/dev/null; then
    wget -q "$JAR_URL" -O "$JAR_DEST"
else
    echo "[!] Neither curl nor wget available"
    exit 1
fi

# Создаём gradlew
cat > "$SCRIPT_DIR/gradlew" << 'GRADLEW_EOF'
#!/bin/sh
# Gradle wrapper
APP_NAME="Gradle Wrapper"
APP_BASE_NAME=$(basename "$0")
APP_HOME=$(cd "$(dirname "$0")" && pwd)

CLASSPATH=$APP_HOME/gradle/wrapper/gradle-wrapper.jar
exec java -classpath "$CLASSPATH" org.gradle.wrapper.GradleWrapperMain "$@"
GRADLEW_EOF
chmod +x "$SCRIPT_DIR/gradlew"

# Создаём gradlew.bat
cat > "$SCRIPT_DIR/gradlew.bat" << 'GRADLEW_BAT_EOF'
@echo off
set APP_BASE_NAME=%~n0
set APP_HOME=%~dp0
set CLASSPATH=%APP_HOME%\gradle\wrapper\gradle-wrapper.jar
java -classpath "%CLASSPATH%" org.gradle.wrapper.GradleWrapperMain %*
GRADLEW_BAT_EOF

echo "[+] Gradle wrapper installed:"
ls -lh "$SCRIPT_DIR/gradlew" "$SCRIPT_DIR/gradlew.bat" "$JAR_DEST"