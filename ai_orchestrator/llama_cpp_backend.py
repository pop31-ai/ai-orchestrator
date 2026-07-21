"""llama.cpp HTTP server backend for orchestrator."""
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

BIN_DIR = Path(__file__).parent / "llama_bin"
LLAMA_SERVER = BIN_DIR / "llama-server.exe"
DEFAULT_PORT = 18082  # internal port for llama.cpp server (avoid conflict with web server)


class LlamaCppServer:
    """Manages a llama.cpp server subprocess for GGUF inference."""

    def __init__(self, model_path: str, port: int = DEFAULT_PORT, n_ctx: int = 2048):
        self.model_path = Path(model_path)
        self.port = port
        self.n_ctx = n_ctx
        self.process: Optional[subprocess.Popen] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._stderr_file = None

    async def start(self, timeout: int = 60) -> bool:
        if not LLAMA_SERVER.exists():
            logger.error(f"llama-server not found at {LLAMA_SERVER}")
            return False
        if not self.model_path.exists():
            logger.error(f"Model not found: {self.model_path}")
            return False

        cmd = [
            str(LLAMA_SERVER),
            "-m", str(self.model_path),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "-c", str(self.n_ctx),
            "-ngl", "0",  # no GPU offloading
            "--no-kv-offload",
            "-np", "1",
        ]
        log_path = Path(BIN_DIR).parent / "llama_server_stderr.log"
        stderr_fh = open(log_path, "wb")
        self._stderr_file = stderr_fh
        logger.info(f"Starting llama-server: {' '.join(cmd)}")
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=stderr_fh,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
        except Exception as e:
            logger.error(f"Failed to start llama-server: {e}")
            return False

        # Wait for server to be ready
        # Use a longer timeout session for health check
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=120),
            headers={"Content-Type": "application/json"},
        )
        url = f"http://127.0.0.1:{self.port}/health"
        logger.info(f"Waiting for llama-server health check at {url} ...")
        for i in range(timeout):
            try:
                async with self._session.get(url) as resp:
                    if resp.status == 200:
                        logger.info(f"llama-server ready on port {self.port} (took ~{i+1}s)")
                        return True
            except (aiohttp.ClientError, asyncio.TimeoutError) as ex:
                if i % 5 == 0:
                    logger.debug(f"Health check attempt {i+1}: {type(ex).__name__}")
            await asyncio.sleep(1)
        logger.warning(f"llama-server did not become ready after {timeout}s")
        return False

    async def generate(self, prompt: str, max_tokens: int = 100, temperature: float = 0.7) -> str:
        if not self._session:
            return "Error: server not started"
        url = f"http://127.0.0.1:{self.port}/completion"
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "stop": ["</s>", "User:", "\n\n"],
            "stream": False,
        }
        try:
            async with self._session.post(url, json=payload) as resp:
                data = await resp.json()
                return data.get("content", "")
        except Exception as e:
            logger.error(f"llama-server generate error: {e}")
            return f"Error: {e}"

    async def generate_stream(self, prompt: str, max_tokens: int = 100, temperature: float = 0.7):
        if not self._session:
            yield "Error: server not started"
            return
        url = f"http://127.0.0.1:{self.port}/completion"
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "stop": ["</s>", "User:", "\n\n"],
            "stream": True,
        }
        try:
            async with self._session.post(url, json=payload) as resp:
                async for line in resp.content:
                    if line:
                        text = line.decode("utf-8", errors="replace").strip()
                        if text.startswith("data: "):
                            try:
                                data = json.loads(text[6:])
                                content = data.get("content", "")
                                if content:
                                    yield content
                                    if data.get("stop"):
                                        break
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            logger.error(f"llama-server stream error: {e}")
            yield f"Error: {e}"

    async def stop(self):
        if self._session:
            await self._session.close()
            self._session = None
        if self._stderr_file:
            try:
                self._stderr_file.close()
            except Exception:
                pass
            self._stderr_file = None
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None
            logger.info("llama-server stopped")

    def __del__(self):
        if self._stderr_file:
            try:
                self._stderr_file.close()
            except Exception:
                pass
        if self.process:
            try:
                self.process.kill()
            except Exception:
                pass
