# Dockerfile — сборка APK для AI Orchestrator
# Использование:
#   docker build -t ai-orchestrator-apk .
#   docker run --rm -v $(pwd)/dist:/app/dist ai-orchestrator-apk

FROM ubuntu:22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV ANDROID_HOME=/opt/android-sdk
ENV GRADLE_HOME=/opt/gradle
ENV PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$GRADLE_HOME/bin

# Системные зависимости
RUN apt-get update && apt-get install -y -qq \
    openjdk-17-jdk-headless \
    wget curl unzip git python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Gradle
RUN wget -q https://services.gradle.org/distributions/gradle-8.5-bin.zip -O /tmp/gradle.zip \
    && unzip -q /tmp/gradle.zip -d /opt \
    && mv /opt/gradle-8.5 $GRADLE_HOME \
    && rm /tmp/gradle.zip

# Android SDK command-line tools
RUN wget -q https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -O /tmp/cmdline-tools.zip \
    && unzip -q /tmp/cmdline-tools.zip -d /tmp/cmdline-tools \
    && mkdir -p $ANDROID_HOME/cmdline-tools \
    && mv /tmp/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest \
    && rm -rf /tmp/cmdline-tools*

# SDK компоненты (API 28 для Android 9, API 34 для Android 14)
RUN yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses > /dev/null 2>&1 || true
RUN $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager \
    "platforms;android-28" \
    "platforms;android-34" \
    "build-tools;34.0.0" \
    "platform-tools" \
    "ndk;25.2.9519653" \
    "cmake;3.22.1" \
    2>&1 | tail -5

# Chaquopy требует NDK
ENV ANDROID_NDK_HOME=$ANDROID_HOME/ndk/25.2.9519653

WORKDIR /app
COPY ai_orchestrator/ /app/ai_orchestrator/
COPY installers/android/apk/ /app/apk/
COPY pyproject.toml /app/
COPY requirements.txt /app/

WORKDIR /app/apk

# --- Сборка для Android 8 (API 26) ---
FROM base AS build-android8
RUN ./gradlew assembleAndroid8Release --no-daemon && \
    mkdir -p /app/dist && \
    cp app/build/outputs/apk/android8/release/*.apk /app/dist/ && \
    echo "android8: OK" >> /app/dist/BUILD.log

# --- Сборка для Android 11 (API 30) ---
FROM base AS build-android11
RUN ./gradlew assembleAndroid11Release --no-daemon && \
    mkdir -p /app/dist && \
    cp app/build/outputs/apk/android11/release/*.apk /app/dist/ && \
    echo "android11: OK" >> /app/dist/BUILD.log

# --- Финальный образ ---
FROM alpine:3.19
COPY --from=build-android8 /app/dist/ /app/dist/
COPY --from=build-android11 /app/dist/ /app/dist/

RUN apk add --no-cache tree
RUN echo "=== AI Orchestrator APK Build ===" && \
    tree /app/dist && \
    echo "Build complete!"

VOLUME /app/dist
CMD ["cp", "-r", "/app/dist/.", "/out/"]