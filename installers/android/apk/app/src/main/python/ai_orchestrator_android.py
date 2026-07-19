#!/usr/bin/env python3
# ai_orchestrator_android — Python backend для Android APK

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='[AI] %(message)s')
log = logging.getLogger(__name__)


class AndroidBackend:
    """Backend-сервер для работы внутри APK через Chaquopy"""

    def __init__(self, api_level: int = 26):
        self.api_level = api_level
        self.data_dir = Path.home() / '.ai_orchestrator'
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Настройки в зависимости от API
        self.config = {
            'api_level': api_level,
            'data_dir': str(self.data_dir),
            'max_messages': 100 if api_level < 30 else 500,
            'enable_streaming': api_level >= 30,
            'use_notifications': api_level >= 26,
        }

        log.info(f"AndroidBackend инициализирован (API {api_level})")

    async def handle_chat(self, message: str) -> dict:
        """Обработка сообщения чата"""
        return {
            'response': f'AI Orchestrator на Android {self.api_level}: {message}',
            'api_level': self.api_level,
            'model': 'android-embedded'
        }

    async def get_providers(self) -> list:
        """Список доступных провайдеров"""
        return [
            {'name': 'android_embedded', 'type': 'local', 'model': 'tiny'},
            {'name': 'openrouter_free', 'type': 'cloud', 'model': 'qwen2.5-7b'},
            {'name': 'groq', 'type': 'cloud', 'model': 'llama-3.1-8b'},
        ]

    async def get_history(self) -> list:
        """История сообщений"""
        history_file = self.data_dir / 'history.json'
        if history_file.exists():
            return json.loads(history_file.read_text())
        return []

    def start(self):
        """Запуск (синхронная обёртка для совместимости с Chaquopy)"""
        asyncio.run(self._run())

    async def _run(self):
        log.info("Backend запущен")
        # Здесь будет aiohttp сервер
        await asyncio.sleep(1)
        log.info("Backend готов")


def start_server(api_level: int = 26):
    """Точка входа из Java/Kotlin"""
    log.info(f"Запуск сервера для API {api_level}")
    backend = AndroidBackend(api_level)
    backend.start()
