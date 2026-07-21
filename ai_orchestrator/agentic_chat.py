"""
Agentic Chat System - 7 agents with tool execution, streaming, tabbed UI
"""
import asyncio
import json
import logging
import os
import re
import signal
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
from urllib.parse import quote_plus
from enum import Enum

import aiohttp
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

try:
    from .checkpoint_system import Checkpoint
except ImportError:
    # Fallback when run directly (python agentic_chat.py)
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from ai_orchestrator.checkpoint_system import Checkpoint


@dataclass
class ChatMessage:
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AgentConfig:
    name: str
    model: str
    system_prompt: str
    role: str = ""  # custom role/profile (e.g. "хирург, стаж 15 лет")
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    max_steps: int = 10
    tools: list = field(default_factory=lambda: [
        "web_search", "shell", "git", "file", "process", "user_agent", "api_call", "ssh"
    ])


class ProcessManager:
    def __init__(self):
        self.processes: Dict[int, Dict] = {}

    async def start(self, name: str, cmd: str, cwd: str = None) -> Dict:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or os.getcwd(),
                start_new_session=True,
            )
            pid = proc.pid
            self.processes[pid] = {
                "pid": pid,
                "name": name,
                "cmd": cmd,
                "proc": proc,
                "started_at": datetime.now().isoformat(),
                "status": "running",
            }
            asyncio.create_task(self._monitor(pid))
            return {"pid": pid, "name": name, "status": "started", "cmd": cmd}
        except Exception as e:
            return {"error": str(e)}

    async def _monitor(self, pid: int):
        if pid not in self.processes:
            return
        info = self.processes[pid]
        try:
            stdout, stderr = await info["proc"].communicate()
            info["status"] = "completed" if info["proc"].returncode == 0 else "failed"
            info["stdout"] = stdout.decode("utf-8", errors="replace")
            info["stderr"] = stderr.decode("utf-8", errors="replace")
            info["returncode"] = info["proc"].returncode
            info["completed_at"] = datetime.now().isoformat()
        except Exception as e:
            info["status"] = "error"
            info["error"] = str(e)

    async def kill(self, pid: int) -> Dict:
        if pid not in self.processes:
            return {"error": f"Process {pid} not found"}
        info = self.processes[pid]
        try:
            os.killpg(os.getpgid(info["proc"].pid), signal.SIGTERM)
            try:
                await asyncio.wait_for(info["proc"].wait(), timeout=3)
            except asyncio.TimeoutError:
                os.killpg(os.getpgid(info["proc"].pid), signal.SIGKILL)
            info["status"] = "killed"
            return {"status": "killed", "pid": pid}
        except Exception as e:
            return {"error": str(e)}

    async def list_all(self) -> List[Dict]:
        return [
            {k: v for k, v in p.items() if k != "proc"}
            for p in self.processes.values()
        ]

    async def get_output(self, pid: int, tail: int = 100) -> Dict:
        if pid not in self.processes:
            return {"error": f"Process {pid} not found"}
        p = self.processes[pid]
        stdout = (p.get("stdout") or "").split("\n")[-tail:]
        stderr = (p.get("stderr") or "").split("\n")[-tail:]
        return {
            "pid": pid,
            "stdout": "\n".join(stdout),
            "stderr": "\n".join(stderr),
            "status": p["status"],
        }

    async def close(self):
        for pid in list(self.processes):
            await self.kill(pid)


class ToolExecutor:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.session: Optional[aiohttp.ClientSession] = None
        self.work_dir = Path.cwd()
        self.process_mgr = ProcessManager()
        self.doc_tools = DocumentTools(str(self.work_dir))
        self.image_tools = ImageTools(str(self.work_dir))
        self.video_tools = VideoTools(str(self.work_dir))
        self.generator = GeneratorTools(str(self.work_dir))
        try:
            from .ssh_client import SSHManager
            self.ssh_mgr = SSHManager()
        except ImportError:
            try:
                import sys
                sys.path.insert(0, str(Path(__file__).parent))
                from ssh_client import SSHManager
                self.ssh_mgr = SSHManager()
            except Exception:
                self.ssh_mgr = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": self.user_agent},
            )
        return self.session

    # --- Web search ---
    async def web_search(self, query: str, max_results: int = 5):
        session = await self._get_session()
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            async with session.get(url) as resp:
                html = await resp.text()
            results = []
            for m in re.finditer(r'class="result__snippet">([^<]+)</a>', html):
                s = m.group(1).strip()
                if len(s) > 20:
                    results.append({"snippet": s[:500]})
                    if len(results) >= max_results:
                        break
            return results if results else [{"snippet": "No results found"}]
        except Exception as e:
            return [{"error": str(e)}]

    # --- Shell ---
    async def shell_exec(self, cmd: str, timeout: int = 60, background: bool = False):
        if background:
            return await self.process_mgr.start("shell", cmd, str(self.work_dir))
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "command": cmd,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
            }
        except asyncio.TimeoutError:
            return {"error": f"Timeout after {timeout}s", "command": cmd}
        except Exception as e:
            return {"error": str(e), "command": cmd}

    # --- Git ---
    async def git_init(self, path: str = "."):
        return await self.shell_exec(f"git -C {path} init")

    async def git_clone(self, url: str, path: str = None):
        cmd = f"git clone {url}"
        if path:
            cmd += f" {path}"
        return await self.shell_exec(cmd, timeout=120)

    async def git_status(self, path: str = "."):
        return await self.shell_exec(f"git -C {path} status")

    async def git_log(self, path: str = ".", n: int = 10):
        return await self.shell_exec(f"git -C {path} log --oneline -n {n}")

    async def git_commit(self, path: str = ".", message: str = "update"):
        cmd = f"git -C {path} add -A && git -C {path} commit -m \"{message}\""
        return await self.shell_exec(cmd)

    async def git_push(self, path: str = ".", remote: str = "origin", branch: str = "main"):
        return await self.shell_exec(f"git -C {path} push {remote} {branch}")

    async def git_pull(self, path: str = "."):
        return await self.shell_exec(f"git -C {path} pull")

    async def git_branch(self, path: str = ".", name: str = None, create: bool = False):
        if create and name:
            return await self.shell_exec(f"git -C {path} checkout -b {name}")
        elif name:
            return await self.shell_exec(f"git -C {path} checkout {name}")
        return await self.shell_exec(f"git -C {path} branch")

    # --- Files ---
    async def file_read(self, path: str):
        try:
            p = Path(self.work_dir) / path
            content = p.read_text(encoding="utf-8")
            return {"path": str(path), "content": content[:10000], "size": p.stat().st_size}
        except Exception as e:
            return {"error": str(e), "path": path}

    # --- SSH ---
    async def ssh_exec(self, host: str, command: str, port: int = 22,
                       user: str = None, key_path: str = None, timeout: int = 30) -> Dict:
        if not self.ssh_mgr:
            return {"error": "SSH client not available", "host": host}
        try:
            return await self.ssh_mgr.exec(host, command, port, user, key_path, None, timeout)
        except Exception as e:
            return {"error": str(e), "host": host, "success": False}

    async def ssh_connect(self, host: str, port: int = 22,
                          user: str = None, key_path: str = None) -> Dict:
        if not self.ssh_mgr:
            return {"error": "SSH client not available"}
        try:
            conn = await self.ssh_mgr.connect(host, port, user, key_path)
            return {"host": host, "port": port, "user": conn.user, "connected": True}
        except Exception as e:
            return {"error": str(e), "host": host, "connected": False}

    async def ssh_list(self) -> List[Dict]:
        if not self.ssh_mgr:
            return []
        return self.ssh_mgr.list_connections()

    async def ssh_disconnect(self, host: str, port: int = 22, user: str = None) -> Dict:
        if not self.ssh_mgr:
            return {"error": "SSH client not available"}
        await self.ssh_mgr.disconnect(host, port, user)
        return {"host": host, "disconnected": True}

    async def file_write(self, path: str, content: str):
        try:
            p = Path(self.work_dir) / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"path": str(path), "size": len(content), "status": "written"}
        except Exception as e:
            return {"error": str(e), "path": path}

    async def file_list(self, path: str = "."):
        try:
            p = Path(self.work_dir) / path
            items = []
            for item in p.iterdir():
                items.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                })
            return {"path": str(path), "items": items}
        except Exception as e:
            return {"error": str(e), "path": path}

    # --- API ---
    async def api_call(self, url: str, method: str = "GET", headers: Dict = None, data: Any = None):
        session = await self._get_session()
        try:
            async with session.request(method, url, headers=headers, json=data) as resp:
                text = await resp.text()
                return {"status": resp.status, "data": text[:5000], "url": url}
        except Exception as e:
            return {"error": str(e), "url": url}

    # --- User Agent ---
    async def get_user_agent(self):
        return self.user_agent

    async def set_user_agent(self, ua: str):
        old = self.user_agent
        self.user_agent = ua
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
        return {"old_user_agent": old, "new_user_agent": self.user_agent}

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
        await self.process_mgr.close()


DANGEROUS_PATTERNS = [
    r"rm\s+-[rf]+\s+(?:/|\*|\.)",  # rm -rf /, rm -rf *, rm -rf .
    r"rmdir\s+/[sq]\s+",            # rmdir /s /q
    r"format\s+\w:",                # format C:, format D:
    r"diskpart",                    # diskpart
    r"del\s+/[fq]\s+",             # del /f, del /q
    r"rd\s+/[sq]\s+",              # rd /s /q
    r"shutdown\s+/[rs]",           # shutdown /r, shutdown /s (remote already handled)
    r"taskkill\s+/f\s+/im",        # taskkill /f /im (force kill)
    r"reg\s+delete",               # reg delete
    r"cipher\s+/w:",               # cipher /w: (wipe disk space)
    r"chkdsk\s+\w:\s*/f",          # chkdsk C: /f (fix disk)
    r":\(\)\{:\|:&\};:",           # fork bomb
    r">\s*/dev/sda",               # direct disk write
    r"dd\s+if=",                   # dd (disk destroyer)
    r"mkfs\.",                     # mkfs (create filesystem)
    r"fdisk\s+/?(dev)?",           # fdisk (partition tool)
    r"mkswap",                     # mkswap
    r"pv\s+/dev/",                 # pv (physical volume)
    r"vgremove", "lvremove",       # LVM removal
    r"iptables\s+-F",             # flush firewall
    r"route\s+delete",            # route delete
    r"kill\s+-9\s+-1",            # kill all processes
    r":\(\)\s*\{",                 # bash fork bomb
]


class AgentChat:
    def __init__(self, config: AgentConfig, llm=None, orchestrator=None):
        self.config = config
        self.llm = llm
        self.orchestrator = orchestrator  # for pipeline routing
        self.executor = ToolExecutor(config.user_agent)
        self.messages: List[Dict] = []
        self.session_id = str(uuid.uuid4())[:8]
        self.step_count = 0
        self.max_steps = config.max_steps
        self._pending_dangerous: Optional[str] = None  # pending dangerous command awaiting confirmation
        self.messages.append({
            "role": "system",
            "content": config.system_prompt,
            "timestamp": datetime.now().isoformat(),
        })

    async def process(self, user_input: str) -> AsyncGenerator[str, None]:
        self.messages.append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat(),
        })

        # Check for pipeline: "command >> agent: prompt"
        pipeline_match = re.split(r"\s*>>\s*", user_input, maxsplit=1)
        if len(pipeline_match) > 1:
            first_cmd = pipeline_match[0].strip()
            rest = pipeline_match[1].strip()
            pipe_rest = re.match(r"(\w[\w_]*)\s*:\s*(.*)", rest)
            if pipe_rest:
                target_agent = pipe_rest.group(1)
                target_prompt = pipe_rest.group(2)
            else:
                target_agent = rest
                target_prompt = f"Continue processing this result"
            pipe_tool_results = await self._execute_tools(first_cmd)
            if pipe_tool_results:
                pipe_output = "\n".join(pipe_tool_results)
                yield json.dumps({"token": f"[PIPE] {first_cmd}\n{pipe_output}\n"}) + "\n"
                await asyncio.sleep(0.01)
                yield json.dumps({"token": f"[PIPE] >> {target_agent}: {target_prompt}\n"}) + "\n"
                await asyncio.sleep(0.01)
                orch = self.orchestrator
                if orch is not None:
                    target_chat = orch.get_chat(target_agent)
                    if not target_chat and target_agent in DEFAULT_AGENTS:
                        target_chat = orch.create_chat(target_agent, DEFAULT_AGENTS[target_agent])
                    if target_chat:
                        pipeline_goal = f"Received from pipeline (first step output): {pipe_output[:500]}\nTask: {target_prompt}"
                        async for chunk in target_chat.process(pipeline_goal):
                            yield chunk
                        yield json.dumps({"done": True}) + "\n"
                        return
                yield json.dumps({"token": f"[PIPE] Result: {pipe_output[:2000]}"}) + "\n"
                yield json.dumps({"done": True}) + "\n"
                return

        # Check for confirmation of pending dangerous command
        if self._pending_dangerous:
            confirm_text = user_input.strip().lower()
            if confirm_text in ("yes", "y", "да", "д", "confirm", "yeah", "yep"):
                cmd = self._pending_dangerous
                self._pending_dangerous = None
                yield json.dumps({"token": f"[CONFIRMED] Executing: {cmd}\n"}) + "\n"
                await asyncio.sleep(0.01)
                r = await self.executor.shell_exec(cmd)
                if "error" in r:
                    result_text = f"Error: {r['error']}"
                else:
                    out = r.get("stdout", "") or r.get("stderr", "")
                    result_text = f"$ {cmd}\n{out[:2000]}"
                yield json.dumps({"token": result_text}) + "\n"
                self.messages.append({"role": "assistant", "content": result_text, "timestamp": datetime.now().isoformat()})
                yield json.dumps({"done": True}) + "\n"
                return
            else:
                self._pending_dangerous = None
                yield json.dumps({"token": "[CANCELLED] Dangerous command not executed.\n"}) + "\n"
                self.messages.append({"role": "assistant", "content": "[CANCELLED] Dangerous command not executed.", "timestamp": datetime.now().isoformat()})
                yield json.dumps({"done": True}) + "\n"
                return

        # Run tools first (catches "create game", "run", "read file", etc.)
        tool_results = await self._execute_tools(user_input)

        # Tool commands: return results directly, skip slow LLM
        if tool_results:
            for r in tool_results:
                yield json.dumps({"token": r}) + "\n"
                await asyncio.sleep(0.01)
            self.messages.append({
                "role": "assistant",
                "content": "\n".join(tool_results),
                "timestamp": datetime.now().isoformat(),
            })
            yield json.dumps({"done": True}) + "\n"
            return

        # Natural language: use LLM
        prompt = self._build_prompt(tool_results)
        # Route code/creative requests to tools when TinyLlama is the backend
        if self.llm and getattr(self.llm, 'backend_type', None) == BackendType.TINYLLAMA:
            try:
                from .prompt_booster import booster
            except ImportError:
                import sys
                sys.path.insert(0, str(Path(__file__).parent))
                from prompt_booster import booster
            boosted = booster.build(user_input)
            logger.info(f"[Booster] intent={boosted.intent}, examples={len(boosted.examples)}")
            if boosted.intent == "code":
                # Route to create_game for games, otherwise use write code
                game_kw = ["игра", "game", "snake", "pong", "arkanoid", "tetris", "зме", "tile", "рпе"]
                if any(k in user_input.lower() for k in game_kw):
                    tool_cmd = f"create game {user_input}"
                else:
                    tool_cmd = f"write code {user_input} as output.py"
                results = await self._execute_tools(tool_cmd)
                for r in results:
                    yield json.dumps({"token": r}) + "\n"
                    await asyncio.sleep(0.01)
                yield json.dumps({"done": True}) + "\n"
                return
            # For non-code: boost prompt for TinyLlama
            prompt = boosted.final_prompt + "\n\n---\n\n" + prompt
        if self.llm:
            response = ""
            try:
                if hasattr(self.llm, 'generate_stream_async'):
                    async for token in self.llm.generate_stream_async(prompt, max_tokens=100, temperature=0.7):
                        response += token
                        yield json.dumps({"token": token}) + "\n"
                        await asyncio.sleep(0.01)
                else:
                    text = self.llm.generate(prompt, max_tokens=100, temperature=0.7)
                    for i in range(0, len(text), 3):
                        token = text[i : i + 3]
                        response += token
                        yield json.dumps({"token": token}) + "\n"
                        await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"LLM generation error: {e}", exc_info=True)
                yield json.dumps({"token": f"\n[LLM Error] {e}\n"}) + "\n"
                await asyncio.sleep(0.01)
                response = self._fallback_response(user_input, tool_results)
                for i in range(0, len(response), 50):
                    yield json.dumps({"token": response[i : i + 50]}) + "\n"
                    await asyncio.sleep(0.01)
        else:
            response = self._fallback_response(user_input, tool_results)
            for i in range(0, len(response), 50):
                yield json.dumps({"token": response[i : i + 50]}) + "\n"
                await asyncio.sleep(0.01)

        self.messages.append({
            "role": "assistant",
            "content": response,
            "timestamp": datetime.now().isoformat(),
        })

        yield json.dumps({"done": True}) + "\n"

    def _build_prompt(self, tool_results: List[str]) -> str:
        """Simple format that works with both GPT4All and TinyLlama."""
        parts = []
        sys_text = ""
        for m in self.messages:
            if m["role"] == "system":
                sys_text = m["content"]
                if self.config.role:
                    sys_text = f"Role: {self.config.role}\n{sys_text}"
                break
        # System prompt as a concise instruction
        parts.append(sys_text[:1500])  # keep system prompt short
        # Last user message
        for m in self.messages[-2:]:
            if m["role"] == "user" and m["content"]:
                parts.append(f"User: {m['content']}")
        parts.append("Assistant:")
        return "\n\n".join(parts)

    def _fallback_response(self, task: str, tool_results: List[str]) -> str:
        t = task.lower()
        if tool_results:
            return f"Here are the results:\n" + "\n".join(tool_results)
        if any(k in t for k in ["search", "find", "look"]):
            return "Search completed. Results shown above."
        if any(k in t for k in ["run", "execute", "shell", "cmd"]):
            return "Command executed. Output shown above."
        if "git" in t:
            return "Git operation completed. Output shown above."
        if any(k in t for k in ["file", "read", "write", "list"]):
            return "File operation completed."
        if any(k in t for k in ["image", "img", "video", "vid", "gif"]):
            return "Image/Video operation completed."
        if "user agent" in t:
            return "User agent updated."
        if "process" in t:
            return "Process operation completed."
        return f"Task processed: {task}"

    def _is_dangerous(self, cmd: str) -> bool:
        """Check if a command matches dangerous patterns."""
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, cmd, re.I):
                return True
        # Generic danger: rm *, del *.*, etc.
        if re.search(r'(?:rm|del|erase)\s+[\*\.\?]', cmd, re.I):
            return True
        if re.search(r'remove-item|clear\-content|wipe|nuke|destroy', cmd, re.I):
            return True
        return False

    async def _execute_tools(self, text: str) -> List[str]:
        results = []
        t = text.lower().strip()

        # === SHORT FORMS ===
        # df = disk free
        if t in ("df", "disk", "disks", "drives"):
            r = await self.executor.shell_exec("wmic logicaldisk get caption,size,freespace /format:csv")
            if "error" in r:
                results.append(f"Error: {r['error']}")
            else:
                results.append(f"{r.get('stdout','')[:3000]}")

        elif t.startswith("disk ") or t.startswith("df "):
            m = re.search(r"(?:disk|df)\s+(\S+)", t)
            if m:
                letter = m.group(1).rstrip(":").upper()
                r = await self.executor.shell_exec(
                    f"wmic logicaldisk where caption='{letter}:' get caption,size,freespace /format:csv"
                )
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    results.append(f"Disk {letter}: \n{r.get('stdout','')[:1000]}")

        # ps = process list (short)
        elif t in ("ps", "tasks", "tasklist"):
            r = await self.executor.shell_exec(
                "powershell -c \"Get-Process | Sort-Object CPU -Desc | Select Name,CPU,WorkingSet,Id | ConvertTo-Json -Compress\""
            )
            if "error" in r:
                results.append(f"Error: {r['error']}")
            else:
                results.append(f"Processes:\n{r.get('stdout','')[:2000]}")

        # ls = list files
        elif t.startswith("ls") or t.startswith("ll"):
            path = t[2:].strip() or "."
            r = await self.executor.file_list(path)
            if "items" in r:
                items = "\n".join(f"{'[d]' if i['type']=='dir' else '[f]'} {i['name']}" for i in r["items"][:30])
                results.append(f"Files in {path}:\n{items}")
            else:
                results.append(f"Error: {r.get('error','')}")

        # top / htop
        elif t in ("top", "htop", "cpu"):
            r = await self.executor.shell_exec(
                "powershell -c \"Get-Process | Sort-Object CPU -Desc | Select -First 10 Name,CPU,WorkingSet,Id | ConvertTo-Json -Compress\""
            )
            if "error" in r:
                results.append(f"Error: {r['error']}")
            else:
                results.append(f"Top CPU:\n{r.get('stdout','')[:2000]}")

        # who / users
        elif t in ("who", "users", "sessions"):
            r = await self.executor.shell_exec("query session")
            i = r.get("stdout", "") or r.get("stderr", "")
            results.append(f"Sessions:\n{i[:1000]}" )

        # date / time
        elif t in ("date", "time", "now", "when"):
            from datetime import datetime
            results.append(f"Date: {datetime.now().isoformat()}")

        # mem / memory / ram
        elif t in ("mem", "memory", "ram"):
            r = await self.executor.shell_exec(
                "powershell -c \"Get-CimInstance Win32_OperatingSystem | Select TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json -Compress\""
            )
            if "error" in r:
                results.append(f"Error: {r['error']}")
            else:
                results.append(f"Memory:\n{r.get('stdout','')[:1000]}")

        # Web search
        if t.startswith("search ") or t.startswith("find ") or t.startswith("look up "):
            m = re.search(r"(?:search|find|look up)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.web_search(m.group(1).strip())
                formatted = "\n".join(
                    f"- {x.get('snippet', x.get('error', ''))}" for x in r[:3]
                )
                results.append(f"Search results:\n{formatted}")

        # Shell
        elif t.startswith("run ") or t.startswith("execute ") or t.startswith("cmd ") or t.startswith("shell "):
            m = re.search(r"(?:run|execute|shell|cmd)\s+(.+)", text, re.I)
            if m:
                cmd = m.group(1).strip()
                background = "background" in t
                if background:
                    cmd = cmd.replace(" background", "").strip()
                # Check for dangerous commands
                if self._is_dangerous(cmd):
                    self._pending_dangerous = cmd
                    results.append(f"[DANGER] This command may be harmful:\n  {cmd}\nType 'yes' to confirm, or anything else to cancel.")
                    return results
                r = await self.executor.shell_exec(cmd, background=background)
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    out = r.get("stdout", "") or r.get("stderr", "")
                    results.append(f"$ {cmd}\n{out[:2000]}")

        # Git
        elif t.startswith("git "):
            results.append(await self._handle_git(t, text))

        # Files
        elif t.startswith("read file "):
            path = text[10:].strip()
            r = await self.executor.file_read(path)
            content = r.get("content", r.get("error", ""))
            results.append(f"File '{path}':\n{content[:2000]}")

        elif t.startswith("write file "):
            m = re.search(r"write file\s+(.+?)\s+with\s+(.+)", text, re.I | re.DOTALL)
            if m:
                r = await self.executor.file_write(m.group(1).strip(), m.group(2).strip())
                results.append(f"Written: {r.get('path', r.get('error', ''))}")

        elif t.startswith("list files") or t.startswith("ls"):
            m = re.search(r"(?:list files|ls)\s*(.*)", text, re.I)
            path = m.group(1).strip() if m and m.group(1) else "."
            r = await self.executor.file_list(path)
            if "items" in r:
                items = "\n".join(
                    f"{'[dir]' if i['type'] == 'dir' else '[file]'} {i['name']}"
                    for i in r["items"][:30]
                )
                results.append(f"Files in {path}:\n{items}")
            else:
                results.append(r.get("error", "Error"))

        # API
        elif t.startswith("api ") or t.startswith("http "):
            m = re.search(r"(?:api|http)\s+(GET|POST)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.api_call(m.group(2).strip(), m.group(1))
                results.append(
                    f"{m.group(1)} {m.group(2)}: {r.get('status', 'error')}\n"
                    f"{r.get('data', r.get('error', ''))[:1000]}"
                )

        # SSH
        elif t.startswith("ssh "):
            m = re.match(r"ssh\s+(?:(\w+)@)?([^\s]+)\s+(.+)", text, re.I)
            if m:
                user = m.group(1)
                host = m.group(2)
                cmd = m.group(3)
                r = await self.executor.ssh_exec(host, cmd, user=user)
                if "error" in r:
                    results.append(f"SSH Error: {r['error']}")
                else:
                    results.append(
                        f"SSH [{user or 'default'}@{host}] $ {cmd}\n"
                        f"exit code: {r.get('returncode', '?')}\n"
                        f"{r.get('stdout', '')[:2000]}"
                        + (f"\nSTDERR:\n{r.get('stderr', '')[:500]}" if r.get('stderr', '').strip() else "")
                    )
            elif "connect" in t:
                m2 = re.match(r"ssh\s+connect\s+(?:(\w+)@)?([^\s]+)(?::(\d+))?", text, re.I)
                if m2:
                    user = m2.group(1)
                    host = m2.group(2)
                    port = int(m2.group(3)) if m2.group(3) else 22
                    r = await self.executor.ssh_connect(host, port, user)
                    results.append(f"SSH connect: {json.dumps(r)}")
                else:
                    results.append("Usage: ssh connect [user@]host[:port]")
            elif "list" in t or "show" in t:
                conns = await self.executor.ssh_list()
                if conns:
                    lines = "\n".join(f"  {c['user']}@{c['host']}:{c['port']} [{'connected' if c['connected'] else 'disconnected'}]" for c in conns)
                    results.append(f"SSH Connections:\n{lines}")
                else:
                    results.append("No active SSH connections")
            else:
                results.append("Usage: ssh [user@]host command | ssh connect [user@]host[:port] | ssh list")

        # User agent
        elif "user agent" in t:
            if "get" in t or "show" in t:
                ua = await self.executor.get_user_agent()
                results.append(f"Current User-Agent: {ua}")
            elif "set" in t:
                m = re.search(r"set\s+user.?agent\s+(.+)", text, re.I)
                if m:
                    r = await self.executor.set_user_agent(m.group(1).strip())
                    results.append(json.dumps(r))

        # Process management
        elif t.startswith("process list") or t.startswith("list processes") or t.startswith("ps"):
            procs = await self.executor.process_mgr.list_all()
            if procs:
                lines = "\n".join(
                    f"PID {p['pid']} [{p['status']}] {p.get('name', '')} - {p.get('cmd', '')}"
                    for p in procs
                )
                results.append(f"Processes:\n{lines}")
            else:
                results.append("No running processes")

        elif t.startswith("kill process") or t.startswith("kill pid"):
            m = re.search(r"(?:kill process|kill pid)\s+(\d+)", text, re.I)
            if m:
                r = await self.executor.process_mgr.kill(int(m.group(1)))
                results.append(json.dumps(r))
            else:
                results.append("Usage: kill process <pid>")

        elif t.startswith("process output") or t.startswith("process log"):
            m = re.search(r"(?:process output|process log)\s+(\d+)", text, re.I)
            if m:
                r = await self.executor.process_mgr.get_output(int(m.group(1)))
                results.append(
                    f"PID {r['pid']} [{r['status']}]\n"
                    f"STDOUT:\n{r.get('stdout', '')}\nSTDERR:\n{r.get('stderr', '')}"
                )
            else:
                results.append("Usage: process output <pid>")

        # Document tools
        elif t.startswith("read doc ") or t.startswith("read file "):
            m = re.search(r"(?:read doc|read file)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.doc_tools.read_doc(m.group(1).strip())
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    results.append(
                        f"File: {r['path']} ({r['total_lines']} lines, showing {r['showing']})\n"
                        f"{r['content'][:3000]}"
                    )

        elif t.startswith("create doc ") or t.startswith("write file "):
            m = re.search(r"(?:create doc|write file)\s+(.+?)\s+with\s+(.+)", text, re.I | re.DOTALL)
            if m:
                r = await self.executor.doc_tools.create_doc(m.group(1).strip(), m.group(2).strip())
                results.append(f"Created: {r.get('path', r.get('error', ''))} ({r.get('lines', 0)} lines)")
            else:
                results.append("Usage: create doc <path> with <content>")

        elif t.startswith("edit doc ") or t.startswith("edit file "):
            m = re.search(
                r"(?:edit doc|edit file)\s+(.+?)\s+find\s+(.+?)\s+replace\s+(.+)",
                text, re.I,
            )
            if m:
                r = await self.executor.doc_tools.edit_doc(
                    m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                )
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    results.append(f"Edited {r['path']}: {r['replacements']} replacement(s)")
            else:
                results.append("Usage: edit doc <path> find <old> replace <new>")

        elif t.startswith("search docs ") or t.startswith("grep "):
            m = re.search(r"(?:search docs|grep)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.doc_tools.search_docs(m.group(1).strip())
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    hits = "\n".join(
                        f"  {h['file']}:{h['line']}: {h['text']}"
                        for h in r.get("results", [])[:20]
                    )
                    results.append(f"Search '{r['query']}' ({r['total']} matches):\n{hits}")
            else:
                results.append("Usage: search docs <query>")

        elif t.startswith("summary ") or t.startswith("summarize "):
            m = re.search(r"(?:summary|summarize)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.doc_tools.summary(m.group(1).strip())
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    top = ", ".join(f"{w}({c})" for w, c in r.get("top_words", [])[:8])
                    results.append(
                        f"Summary of {r['path']}:\n"
                        f"  Lines: {r['total_lines']} (non-empty: {r['non_empty_lines']})\n"
                        f"  Words: {r['total_words']}, Chars: {r['total_chars']}\n"
                        f"  Type: {r['extension']}\n"
                        f"  Top words: {top}\n"
                        f"  Preview:\n{r['preview'][:500]}"
                    )

        elif t.startswith("list docs ") or t.startswith("list files"):
            m = re.search(r"(?:list docs|list files)\s*(.*)", text, re.I)
            path = m.group(1).strip() if m and m.group(1) else "."
            r = await self.executor.doc_tools.list_docs(path)
            if "error" in r:
                results.append(f"Error: {r['error']}")
            else:
                items = "\n".join(
                    f"  {'[dir]' if i['type']=='dir' else '[file]'} {i['name']}"
                    + (f" ({i['size']}B)" if i.get('size') else "")
                    for i in r.get("items", [])[:30]
                )
                results.append(f"Documents in {r['path']}:\n{items}")

        # PDF-specific commands
        elif t.startswith("pdf info ") or t.startswith("pdf meta "):
            m = re.search(r"(?:pdf info|pdf meta)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.doc_tools._pdf_metadata(
                    await self.executor.doc_tools._resolve(m.group(1).strip())
                )
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    results.append(
                        f"PDF: {r['path']}\n"
                        f"  Pages: {r['total_pages']}\n"
                        f"  Title: {r.get('title', 'N/A')}\n"
                        f"  Author: {r.get('author', 'N/A')}\n"
                        f"  Size: {r['size']} bytes"
                    )

        elif t.startswith("pdf page ") or t.startswith("read page "):
            m = re.search(r"(?:pdf page|read page)\s+(\S+)\s+(\d+)", text, re.I)
            if m:
                r = await self.executor.doc_tools.read_pdf_page(m.group(1).strip(), int(m.group(2)))
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    results.append(
                        f"PDF {r['path']} page {r['page']}/{r['total_pages']}:\n{r['text'][:3000]}"
                    )
            else:
                results.append("Usage: pdf page <path> <page_number>")

        elif t.startswith("pdf range ") or t.startswith("read pages "):
            m = re.search(r"(?:pdf range|read pages)\s+(\S+)\s+(\d+)\s*[-–]\s*(\d+)", text, re.I)
            if m:
                r = await self.executor.doc_tools.read_pdf_range(
                    m.group(1).strip(), int(m.group(2)), int(m.group(3))
                )
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    results.append(
                        f"PDF {r['path']} pages {r['pages']}/{r['total_pages']}:\n{r['content'][:4000]}"
                    )
            else:
                results.append("Usage: pdf range <path> <start>-<end>")

        elif t.startswith("pdf all ") or t.startswith("read pdf "):
            m = re.search(r"(?:pdf all|read pdf)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.doc_tools.read_doc(m.group(1).strip(), limit=2000)
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    results.append(
                        f"PDF: {r['path']} ({r.get('total_pages', '?')} pages)\n"
                        f"Title: {r.get('title', 'N/A')}\n"
                        f"{r['content'][:5000]}"
                    )

        # Image tools
        elif t.startswith("image info ") or t.startswith("img info "):
            m = re.search(r"(?:image info|img info)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.image_tools.image_info(m.group(1).strip())
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    frames = f", Frames: {r.get('frames', 1)}" if r.get("frames") else ""
                    results.append(
                        f"Image: {r['path']}\n"
                        f"  Format: {r['format']}, Mode: {r['mode']}\n"
                        f"  Size: {r['width']}x{r['height']}{frames}\n"
                        f"  File: {r['size']} bytes"
                    )

        elif t.startswith("image analyze ") or t.startswith("img analyze "):
            m = re.search(r"(?:image analyze|img analyze)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.image_tools.image_analyze(m.group(1).strip())
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    colors = "\n".join(
                        f"  {c['hex']} ({c['count']} px)" for c in r.get("top_colors", [])
                    )
                    results.append(
                        f"Image analysis: {r['path']}\n"
                        f"  {r['width']}x{r['height']}, {r['format']}, {r['mode']}\n"
                        f"  Brightness: {r['brightness']} ({r['brightness_label']})\n"
                        f"  Aspect: {r['aspect_ratio']}\n"
                        f"  Top colors:\n{colors}"
                    )

        elif t.startswith("image thumb ") or t.startswith("img thumb "):
            m = re.search(r"(?:image thumb|img thumb)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.image_tools.image_thumbnail(m.group(1).strip())
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    results.append(f"[THUMBNAIL]{r['thumbnail']}[/THUMBNAIL]")

        elif t.startswith("gif frames ") or t.startswith("gif extract "):
            m = re.search(r"(?:gif frames|gif extract)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.image_tools.gif_extract_frames(m.group(1).strip())
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    for fr in r.get("frames", [])[:10]:
                        results.append(f"[FRAME {fr['index']}]{fr['thumbnail']}[/FRAME]")
                    results.append(f"Extracted {r['extracted']}/{r['total_frames']} frames")

        elif t.startswith("list images ") or t.startswith("ls images"):
            m = re.search(r"(?:list images|ls images)\s*(.*)", text, re.I)
            path = m.group(1).strip() if m and m.group(1) else "."
            r = await self.executor.image_tools.list_images(path)
            if "error" in r:
                results.append(f"Error: {r['error']}")
            else:
                items = "\n".join(
                    f"  {i['name']} ({i['ext']}, {i['size']}B)" for i in r.get("images", [])[:30]
                )
                results.append(f"Images in {r['path']} ({r['total']} total):\n{items}")

        # Video tools
        elif t.startswith("video info ") or t.startswith("vid info "):
            m = re.search(r"(?:video info|vid info)\s+(.+)", text, re.I)
            if m:
                r = await self.executor.video_tools.video_info(m.group(1).strip())
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    results.append(
                        f"Video: {r['path']}\n"
                        f"  Format: {r['format']}, Codec: {r['codec']}\n"
                        f"  Resolution: {r['width']}x{r['height']}\n"
                        f"  FPS: {r['fps']}, Frames: {r['total_frames']}\n"
                        f"  Duration: {r['duration_fmt']} ({r['duration_sec']}s)\n"
                        f"  Size: {r['size']} bytes"
                    )

        elif t.startswith("video frame ") or t.startswith("vid frame "):
            m = re.search(r"(?:video frame|vid frame)\s+(.+?)\s+(\d+(?:\.\d+)?)", text, re.I)
            if m:
                r = await self.executor.video_tools.video_frame(m.group(1).strip(), float(m.group(2)))
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    results.append(
                        f"[VIDEO FRAME {r['time_sec']}s]{r['thumbnail']}[/VIDEO FRAME]"
                    )
            else:
                results.append("Usage: video frame <path> <time_seconds>")

        elif t.startswith("video frames ") or t.startswith("vid frames "):
            m = re.search(r"(?:video frames|vid frames)\s+(.+?)(?:\s+(\d+))?$", text, re.I)
            if m:
                count = int(m.group(2)) if m.group(2) else 5
                r = await self.executor.video_tools.video_frames(m.group(1).strip(), count)
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    for fr in r.get("frames", [])[:15]:
                        results.append(
                            f"[FRAME {fr['index']} @ {fr['time_fmt']}]{fr['thumbnail']}[/FRAME]"
                        )
                    results.append(
                        f"Extracted {r['extracted']} frames from {r['duration_sec']}s video"
                    )
            else:
                results.append("Usage: video frames <path> [count]")

        elif t.startswith("gif info "):
            m = re.search(r"gif info\s+(.+)", text, re.I)
            if m:
                r = await self.executor.video_tools.gif_info(m.group(1).strip())
                if "error" in r:
                    results.append(f"Error: {r['error']}")
                else:
                    results.append(
                        f"GIF: {r['path']}\n"
                        f"  Size: {r['width']}x{r['height']}, Mode: {r['mode']}\n"
                        f"  Frames: {r.get('frames', 1)}\n"
                        f"  Frame duration: {r.get('duration_ms', 0)}ms\n"
                        f"  Loop: {r.get('loop', 'infinite')}\n"
                        f"  Total: {r.get('total_duration_sec', 0)}s\n"
                        f"  File: {r['size']} bytes"
                    )

        # --- UML (before draw to avoid catch-all) ---
        if t.startswith("create uml ") or t.startswith("make uml ") or t.startswith("draw uml "):
            m = re.search(r"(?:create uml|make uml|draw uml)\s+(.+?)(?:\s+(\d+)x(\d+))?$", text, re.I)
            if m:
                desc = m.group(1).strip()
                w, h = (int(m.group(2)), int(m.group(3))) if m.group(2) else (900, 700)
                r = await self.executor.generator.create_uml(desc, w, h)
                results.append(f"[UML] Generated: {r.get('path', r.get('error', ''))} ({r.get('width', '?')}x{r.get('height', '?')}, {r.get('size', '?')}B)")

        # --- Diagram (before draw to avoid catch-all) ---
        elif t.startswith("create diagram ") or t.startswith("make diagram ") or t.startswith("draw diagram "):
            m = re.search(r"(?:create diagram|make diagram|draw diagram)\s+(.+?)(?:\s+(\d+)x(\d+))?$", text, re.I)
            if m:
                desc = m.group(1).strip()
                w, h = (int(m.group(2)), int(m.group(3))) if m.group(2) else (800, 600)
                r = await self.executor.generator.create_diagram(desc, w, h)
                results.append(f"[DIAGRAM] Generated: {r.get('path', r.get('error', ''))} ({r.get('width', '?')}x{r.get('height', '?')}, {r.get('size', '?')}B)")

        # --- Image generation ---
        elif t.startswith("create image ") or t.startswith("make image ") or t.startswith("draw "):
            m = re.search(r"(?:create image|make image|draw)\s+(.+?)(?:\s+(\d+)x(\d+))?$", text, re.I)
            if m:
                desc = m.group(1).strip()
                w, h = (int(m.group(2)), int(m.group(3))) if m.group(2) else (512, 512)
                r = await self.executor.generator.create_image(desc, w, h)
                results.append(f"[IMAGE] Generated: {r.get('path', r.get('error', ''))} ({r.get('width', '?')}x{r.get('height', '?')}, {r.get('size', '?')}B)")

        elif t.startswith("create gif ") or t.startswith("make gif ") or t.startswith("animate "):
            m = re.search(r"(?:create gif|make gif|animate)\s+(.+?)(?:\s+(\d+)\s*frames?)?$", text, re.I)
            if m:
                desc = m.group(1).strip()
                nf = int(m.group(2)) if m.group(2) else 10
                r = await self.executor.generator.create_gif(desc, nf)
                results.append(f"[GIF] Generated: {r.get('path', r.get('error', ''))} ({r.get('frames', '?')} frames, {r.get('size', '?')}B)")

        elif t.startswith("create video ") or t.startswith("make video "):
            m = re.search(r"(?:create video|make video)\s+(.+?)(?:\s+(\d+)s)?$", text, re.I)
            if m:
                desc = m.group(1).strip()
                dur = int(m.group(2)) if m.group(2) else 3
                r = await self.executor.generator.create_video(desc, dur)
                results.append(f"[VIDEO] Generated: {r.get('path', r.get('error', ''))} ({r.get('duration_sec', '?')}s, {r.get('fps', '?')}fps, {r.get('size', '?')}B)")

        elif t.startswith("create pdf ") or t.startswith("make pdf ") or t.startswith("generate pdf "):
            m = re.search(r"(?:create pdf|make pdf|generate pdf)\s+(.+?)(?:\s+with\s+(.+))?$", text, re.I | re.DOTALL)
            if m:
                title = m.group(1).strip()
                content = m.group(2).strip() if m.group(2) else ""
                r = await self.executor.generator.create_pdf(title, content)
                results.append(f"[PDF] Generated: {r.get('path', r.get('error', ''))} ({r.get('pages', '?')} pages, {r.get('size', '?')}B)")

        elif t.startswith("create music ") or t.startswith("make music ") or t.startswith("compose "):
            m = re.search(r"(?:create music|make music|compose)\s+(.+?)(?:\s+(\d+)s)?$", text, re.I)
            if m:
                desc = m.group(1).strip()
                dur = int(m.group(2)) if m.group(2) else 5
                r = await self.executor.generator.create_music(desc, dur)
                results.append(f"[MUSIC] Generated: {r.get('path', r.get('error', ''))} ({r.get('duration_sec', '?')}s, {r.get('size', '?')}B, {r.get('format', '?')})")

        elif t.startswith("create diagram ") or t.startswith("make diagram ") or t.startswith("draw diagram "):
            m = re.search(r"(?:create diagram|make diagram|draw diagram)\s+(.+?)(?:\s+(\d+)x(\d+))?$", text, re.I)
            if m:
                desc = m.group(1).strip()
                w, h = (int(m.group(2)), int(m.group(3))) if m.group(2) else (800, 600)
                r = await self.executor.generator.create_diagram(desc, w, h)
                results.append(f"[DIAGRAM] Generated: {r.get('path', r.get('error', ''))} ({r.get('width', '?')}x{r.get('height', '?')}, {r.get('size', '?')}B)")

        elif t.startswith("create gost ") or t.startswith("make gost ") or t.startswith("gost doc "):
            m = re.search(r"(?:create gost|make gost|gost doc)\s+(.+?)(?:\s+with\s+(.+))?$", text, re.I | re.DOTALL)
            if m:
                title = m.group(1).strip()
                content = m.group(2).strip() if m.group(2) else ""
                r = await self.executor.generator.create_gost_doc(title, content)
                results.append(f"[GOST] Generated: {r.get('path', r.get('error', ''))} ({r.get('pages', '?')} pages, {r.get('size', '?')}B)")

        # --- Agent creation ---
        if t.startswith("create agent ") or t.startswith("make agent ") or t.startswith("new agent "):
            m = re.search(r"(?:create agent|make agent|new agent)\s+(.+?)(?:\s+with\s+(.+))?$", text, re.I | re.DOTALL)
            if m:
                desc = m.group(1).strip()
                tools = m.group(2).strip() if m.group(2) else ""
                r = await self.executor.generator.create_agent(desc, tools=tools)
                results.append(f"[AGENT] Created: {r.get('agent_name', r.get('error', ''))} — file: {r.get('file', '')}, {r.get('status', '')}")

        # --- Code generation: write code to .py file and run ---
        if t.startswith("write code ") or t.startswith("make code ") or t.startswith("write script "):
            m = re.search(r"(?:write code|make code|write script)\s+(.+?)(?:\s+as\s+(\S+\.py))?$", text, re.I)
            if m:
                desc = m.group(1).strip()
                filename = m.group(2).strip() if m.group(2) else None
                r = await self.executor.generator.create_code(desc, filename=filename)
                results.append(f"[CODE] Created: {r.get('path', r.get('error', ''))} ({r.get('lines', '?')} lines)")
                if r.get("run_result"):
                    results.append(f"[RUN] Output:\n{r['run_result'][:1000]}")

        # --- Game creation ---
        if t.startswith("create game ") or t.startswith("make game ") or t.startswith("new game "):
            m = re.search(r"(?:create game|make game|new game)\s+(.+?)$", text, re.I)
            if m:
                desc = m.group(1).strip()
                r = await self.executor.generator.create_game(desc)
                results.append(f"[GAME] Created: {r.get('title', r.get('error', ''))} — file: {r.get('path', '')} ({r.get('lines', '?')} lines)")
                if r.get("launcher"):
                    results.append(f"[LAUNCH] Run: {r['launcher']}")

        return results


class GeneratorTools:
    """Tools for generating images, GIFs, videos, PDFs, music, and diagrams"""

    def __init__(self, work_dir: str = None):
        self.work_dir = Path(work_dir or os.getcwd())
        self.out_dir = self.work_dir / "generated"
        self.out_dir.mkdir(exist_ok=True)

    # --- Image generation ---
    async def create_image(self, description: str, width: int = 512, height: int = 512,
                           color: str = "random", filename: str = None) -> Dict:
        """Generate a simple image based on description using Pillow"""
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageFilter
            import random as rnd
            img = Image.new("RGB", (width, height), (13, 17, 23))
            draw = ImageDraw.Draw(img)
            desc = description.lower()

            if "gradient" in desc or "rainbow" in desc:
                for y in range(height):
                    r = int(255 * y / height)
                    g = int(255 * (1 - y / height))
                    b = int(255 * abs(0.5 - y / height) * 2)
                    draw.line([(0, y), (width, y)], fill=(r, g, b))
            elif "grid" in desc or "checkerboard" in desc or "checker" in desc:
                size = 40
                for y in range(0, height, size):
                    for x in range(0, width, size):
                        if (x // size + y // size) % 2 == 0:
                            draw.rectangle([x, y, x + size, y + size], fill=(200, 200, 200))
            elif "circle" in desc or "dot" in desc:
                for _ in range(rnd.randint(10, 200)):
                    x, y = rnd.randint(0, width), rnd.randint(0, height)
                    r = rnd.randint(5, 50)
                    c = tuple(rnd.randint(0, 255) for _ in range(3))
                    draw.ellipse([x - r, y - r, x + r, y + r], fill=c)
            elif "line" in desc or "stripe" in desc:
                for _ in range(rnd.randint(5, 50)):
                    x1, y1 = rnd.randint(0, width), rnd.randint(0, height)
                    x2, y2 = rnd.randint(0, width), rnd.randint(0, height)
                    c = tuple(rnd.randint(0, 255) for _ in range(3))
                    draw.line([(x1, y1), (x2, y2)], fill=c, width=rnd.randint(1, 5))
            elif "star" in desc:
                cx, cy = width // 2, height // 2
                outer, inner = min(width, height) // 3, min(width, height) // 6
                points = []
                for i in range(10):
                    angle = i * 36 - 90
                    r = outer if i % 2 == 0 else inner
                    points.append((cx + r * __import__('math').cos(__import__('math').radians(angle)),
                                   cy + r * __import__('math').sin(__import__('math').radians(angle))))
                draw.polygon(points, fill=(255, 215, 0))
            else:
                # Default: random colorful shapes
                for _ in range(rnd.randint(5, 30)):
                    shape = rnd.choice(["rect", "ellipse", "line"])
                    c = tuple(rnd.randint(0, 255) for _ in range(3))
                    x1, y1 = rnd.randint(0, width), rnd.randint(0, height)
                    x2, y2 = rnd.randint(0, width), rnd.randint(0, height)
                    if shape == "rect":
                        draw.rectangle([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)], fill=c, outline=(255, 255, 255))
                    elif shape == "ellipse":
                        draw.ellipse([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)], fill=c)
                    else:
                        draw.line([(x1, y1), (x2, y2)], fill=c, width=2)

            if filename:
                path = self.out_dir / filename
            else:
                path = self.out_dir / f"image_{datetime.now().strftime('%H%M%S')}.png"
            img.save(str(path), "PNG")
            return {"path": str(path.relative_to(self.work_dir)), "width": width, "height": height,
                    "size": path.stat().st_size, "format": "PNG"}
        except Exception as e:
            return {"error": str(e)}

    # --- GIF generation ---
    async def create_gif(self, description: str = "animated shapes", frames: int = 10,
                         width: int = 256, height: int = 256, filename: str = None) -> Dict:
        """Generate an animated GIF using Pillow"""
        try:
            from PIL import Image, ImageDraw
            import random as rnd
            images = []
            desc = description.lower()

            for i in range(frames):
                img = Image.new("RGB", (width, height), (13, 17, 23))
                draw = ImageDraw.Draw(img)
                progress = i / max(frames - 1, 1)

                if "bounce" in desc or "ball" in desc:
                    r = 20
                    cx = int(width * (0.5 + 0.4 * __import__('math').sin(progress * 6.28)))
                    cy = int(height * (0.5 + 0.4 * __import__('math').cos(progress * 6.28)))
                    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 100, 100))
                elif "spiral" in desc:
                    cx, cy = width // 2, height // 2
                    angle = progress * 6.28 * 3
                    r = int(min(width, height) * 0.4 * progress)
                    x = cx + int(r * __import__('math').cos(angle))
                    y = cy + int(r * __import__('math').sin(angle))
                    draw.ellipse([x - 8, y - 8, x + 8, y + 8], fill=(100, 200, 255))
                elif "rainbow" in desc or "color" in desc:
                    for y in range(height):
                        r = int(255 * (0.5 + 0.5 * __import__('math').sin(progress * 6.28 + y / height * 6.28)))
                        g = int(255 * (0.5 + 0.5 * __import__('math').sin(progress * 6.28 + y / height * 6.28 + 2.09)))
                        b = int(255 * (0.5 + 0.5 * __import__('math').sin(progress * 6.28 + y / height * 6.28 + 4.19)))
                        draw.line([(0, y), (width, y)], fill=(r, g, b))
                else:
                    # Rotating shapes
                    cx, cy = width // 2, height // 2
                    for j in range(5):
                        angle = progress * 6.28 + j * 1.26
                        r = 60
                        x = cx + int(r * __import__('math').cos(angle))
                        y = cy + int(r * __import__('math').sin(angle))
                        c = tuple(int(128 + 127 * __import__('math').sin(progress * 6.28 + j)) for _ in range(3))
                        draw.ellipse([x - 15, y - 15, x + 15, y + 15], fill=c)

                images.append(img)

            if images:
                if filename:
                    path = self.out_dir / filename
                else:
                    path = self.out_dir / f"anim_{datetime.now().strftime('%H%M%S')}.gif"
                images[0].save(str(path), "GIF", save_all=True, append_images=images[1:],
                              duration=100, loop=0)
                return {"path": str(path.relative_to(self.work_dir)), "frames": len(images),
                        "size": path.stat().st_size, "duration_ms": 100}
            return {"error": "No frames generated"}
        except Exception as e:
            return {"error": str(e)}

    # --- Video generation ---
    async def create_video(self, description: str = "moving shapes", duration_sec: int = 3,
                           width: int = 320, height: int = 240, fps: int = 10,
                           filename: str = None) -> Dict:
        """Generate a simple video using OpenCV"""
        try:
            import cv2
            import numpy as np
            import random as rnd
            desc = description.lower()

            if filename:
                path = self.out_dir / filename
            else:
                path = self.out_dir / f"video_{datetime.now().strftime('%H%M%S')}.mp4"

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
            total_frames = int(duration_sec * fps)

            for i in range(total_frames):
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                frame[:] = (13, 17, 23)
                progress = i / max(total_frames - 1, 1)

                if "bounce" in desc or "ball" in desc:
                    cx = int(width * (0.5 + 0.4 * __import__('math').cos(progress * 6.28)))
                    cy = int(height * (0.5 + 0.4 * __import__('math').sin(progress * 6.28 * 2)))
                    cv2.circle(frame, (cx, cy), 20, (100, 200, 255), -1)
                elif "spiral" in desc:
                    cx, cy = width // 2, height // 2
                    angle = progress * 6.28 * 5
                    r = int(min(width, height) * 0.4 * progress)
                    x = cx + int(r * __import__('math').cos(angle))
                    y = cy + int(r * __import__('math').sin(angle))
                    cv2.circle(frame, (x, y), 10, (255, 255, 100), -1)
                else:
                    # Moving bars
                    for j in range(3):
                        x = int(width * (0.2 + 0.6 * (j / 2 + progress) % 1))
                        h = int(height * (0.3 + 0.5 * __import__('math').sin(progress * 6.28 + j)))
                        c = [0, 0, 0]
                        c[j] = 200
                        cv2.rectangle(frame, (x - 15, height // 2 - h // 2), (x + 15, height // 2 + h // 2),
                                      tuple(c), -1)

                out.write(frame)

            out.release()
            return {"path": str(path.relative_to(self.work_dir)), "frames": total_frames,
                    "fps": fps, "duration_sec": duration_sec,
                    "resolution": f"{width}x{height}", "size": path.stat().st_size}
        except Exception as e:
            return {"error": str(e)}

    # --- PDF generation ---
    async def create_pdf(self, title: str = "Document", content: str = "Hello World",
                         page_size: str = "A4", filename: str = None) -> Dict:
        """Generate a PDF document using fpdf"""
        try:
            from fpdf import FPDF
            pdf = FPDF(orientation='P', unit='mm', format=page_size)
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)

            # Title
            pdf.set_font("Helvetica", "B", 18)
            pdf.cell(0, 15, title, new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.ln(5)

            # Content
            pdf.set_font("Helvetica", "", 11)
            for line in content.split("\n"):
                if line.strip():
                    pdf.multi_cell(0, 6, line)
                else:
                    pdf.ln(3)

            if filename:
                path = self.out_dir / filename
            else:
                path = self.out_dir / f"doc_{datetime.now().strftime('%H%M%S')}.pdf"

            pdf.output(str(path))
            return {"path": str(path.relative_to(self.work_dir)), "pages": pdf.pages_count,
                    "title": title, "size": path.stat().st_size, "page_size": page_size}
        except Exception as e:
            return {"error": str(e)}

    # --- Diagram / Schematic generation ---
    async def create_diagram(self, description: str = "flowchart", width: int = 800,
                             height: int = 600, filename: str = None) -> Dict:
        """Generate a diagram or schematic as an image using Pillow"""
        try:
            from PIL import Image, ImageDraw
            import random as rnd
            desc = description.lower()
            img = Image.new("RGB", (width, height), (13, 17, 23))
            draw = ImageDraw.Draw(img)
            nodes = []

            if "flowchart" in desc or "flow" in desc:
                # Draw boxes with arrows
                box_w, box_h = 150, 40
                labels = ["Start", "Process", "Decision", "Output", "End"]
                positions = [(width // 2 - box_w // 2, 20),
                             (width // 2 - box_w // 2, 120),
                             (width // 2 - box_w // 2, 220),
                             (width // 2 - box_w // 2, 320),
                             (width // 2 - box_w // 2, 420)]
                for i, (lx, ly) in enumerate(positions):
                    draw.rectangle([lx, ly, lx + box_w, ly + box_h],
                                   fill=(40, 60, 100), outline=(100, 180, 255), width=2)
                    draw.text((lx + 10, ly + 12), labels[i], fill=(255, 255, 255))
                    if i > 0:
                        px, py = positions[i - 1]
                        draw.line([(px + box_w // 2, py + box_h),
                                   (lx + box_w // 2, ly)], fill=(100, 180, 255), width=2)
                nodes = [{"label": l, "pos": p} for l, p in zip(labels, positions)]
            elif "gantt" in desc or "schedule" in desc:
                tasks = [("Task A", 0, 60), ("Task B", 20, 80), ("Task C", 50, 100),
                         ("Task D", 90, 140), ("Task E", 120, 180)]
                bar_h = 30
                margin = 100
                for i, (task, start, end) in enumerate(tasks):
                    y = 40 + i * (bar_h + 10)
                    # Label
                    draw.text((10, y + 5), task, fill=(200, 200, 200))
                    # Bar
                    x1 = margin + int(start * (width - margin - 20) / 200)
                    x2 = margin + int(end * (width - margin - 20) / 200)
                    c = tuple(rnd.randint(60, 200) for _ in range(3))
                    draw.rectangle([x1, y, x2, y + bar_h], fill=c, outline=(255, 255, 255))
            elif "architecture" in desc or "system" in desc:
                layers = [("Frontend", (50, 20)), ("API", (50, 160)),
                          ("Services", (50, 300)), ("Database", (50, 440))]
                bw, bh = 300, 100
                for i, (label, (lx, ly)) in enumerate(layers):
                    draw.rectangle([lx, ly, lx + bw, ly + bh],
                                   fill=(30 + i * 20, 40 + i * 15, 60 + i * 10),
                                   outline=(100, 200, 255), width=2)
                    draw.text((lx + bw // 3, ly + bh // 2 - 5), label, fill=(255, 255, 255))
                    if i > 0:
                        px, py = layers[i - 1][1]
                        draw.line([(px + bw // 2, py + bh), (lx + bw // 2, ly)],
                                  fill=(100, 200, 255), width=2)
            else:
                # Simple network/graph diagram
                import math
                cx, cy = width // 2, height // 2
                for i in range(8):
                    angle = i * 45 * math.pi / 180
                    nx = cx + int(200 * math.cos(angle))
                    ny = cy + int(200 * math.sin(angle))
                    nodes.append((nx, ny))
                    draw.ellipse([nx - 20, ny - 20, nx + 20, ny + 20],
                                 fill=(40 + i * 20, 80, 100), outline=(100, 200, 255))
                    draw.text((nx - 10, ny - 5), str(i + 1), fill=(255, 255, 255))
                    # Center node
                    draw.line([(cx, cy), (nx, ny)], fill=(60, 120, 180), width=2)
                draw.ellipse([cx - 25, cy - 25, cx + 25, cy + 25],
                             fill=(100, 150, 200), outline=(255, 255, 100))
                draw.text((cx - 10, cy - 5), "0", fill=(255, 255, 255))

            if filename:
                path = self.out_dir / filename
            else:
                path = self.out_dir / f"diagram_{datetime.now().strftime('%H%M%S')}.png"
            img.save(str(path), "PNG")
            return {"path": str(path.relative_to(self.work_dir)), "width": width, "height": height,
                    "nodes": len(nodes) if nodes else 0, "size": path.stat().st_size}
        except Exception as e:
            return {"error": str(e)}

    # --- Music generation ---
    async def create_music(self, description: str = "simple melody", duration_sec: int = 5,
                           bpm: int = 120, filename: str = None) -> Dict:
        """Generate a simple WAV music file using numpy/scipy"""
        try:
            import numpy as np
            from scipy.io import wavfile
            import math
            sr = 22050  # sample rate
            desc = description.lower()

            def note_freq(note):
                """Convert note name (C4=261.63) to frequency"""
                notes = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
                         "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
                note = note.upper().rstrip("0123456789")
                octave = int(note[-1]) if note[-1].isdigit() else 4
                if note in notes:
                    semi = notes[note] + (octave - 4) * 12
                    return 440.0 * (2 ** (semi / 12))
                return 440.0

            total_samples = int(sr * duration_sec)
            t = np.linspace(0, duration_sec, total_samples, endpoint=False)

            if "scale" in desc or "piano" in desc:
                # Ascending scale
                scale = ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5"]
                samples = np.zeros(total_samples)
                note_len = total_samples // len(scale)
                for i, n in enumerate(scale):
                    freq = note_freq(n)
                    env = np.linspace(1, 0, note_len) ** 2  # decay envelope
                    start = i * note_len
                    end = min(start + note_len, total_samples)
                    if start < total_samples:
                        note_samples = np.sin(2 * math.pi * freq * t[start:end])
                        # Add harmonics for piano-like sound
                        note_samples += 0.5 * np.sin(4 * math.pi * freq * t[start:end])
                        note_samples += 0.25 * np.sin(6 * math.pi * freq * t[start:end])
                        samples[start:end] = note_samples * env[:end - start]
            elif "chord" in desc or "ambient" in desc:
                # Ambient chord
                freqs = [261.63, 329.63, 392.00, 523.25]  # C major + octave
                samples = np.zeros(total_samples)
                for freq in freqs:
                    samples += np.sin(2 * math.pi * freq * t) * 0.3
                # Add slow modulation
                samples *= 0.5 + 0.5 * np.sin(2 * math.pi * 0.5 * t)
            elif "arp" in desc or "arpeggio" in desc:
                notes = [261.63, 329.63, 392.00, 523.25, 659.25]
                samples = np.zeros(total_samples)
                note_len = int(sr * 0.15)  # 150ms per note
                for i in range(total_samples // note_len + 1):
                    freq = notes[i % len(notes)]
                    start = i * note_len
                    end = min(start + note_len, total_samples)
                    if start < total_samples:
                        env = np.linspace(1, 0.3, min(note_len, total_samples - start))
                        samples[start:end] = 0.4 * np.sin(2 * math.pi * freq * t[start:end]) * env
            else:
                # Simple melody with random notes
                base_freqs = [262, 294, 330, 349, 392, 440, 494, 523]
                samples = np.zeros(total_samples)
                note_len = int(sr * 0.25)
                for i in range(total_samples // note_len + 1):
                    freq = base_freqs[i % len(base_freqs)] * (1 + 0.5 * (i // len(base_freqs) % 2))
                    start = i * note_len
                    end = min(start + note_len, total_samples)
                    if start < total_samples:
                        env = np.sin(math.pi * np.linspace(0, 1, end - start))
                        samples[start:end] = 0.3 * np.sin(2 * math.pi * freq * t[start:end]) * env

            # Normalize and convert to int16
            samples = np.clip(samples, -1, 1)
            audio = (samples * 32767).astype(np.int16)

            if filename:
                path = self.out_dir / filename
            else:
                path = self.out_dir / f"music_{datetime.now().strftime('%H%M%S')}.wav"
            wavfile.write(str(path), sr, audio)
            return {"path": str(path.relative_to(self.work_dir)), "duration_sec": duration_sec,
                    "sample_rate": sr, "bpm": bpm, "size": path.stat().st_size,
                    "format": "WAV"}
        except Exception as e:
            return {"error": str(e)}

    # --- GOST / technical document generation ---
    async def create_gost_doc(self, title: str = "Technical Report", content: str = "",
                              doc_type: str = "report", filename: str = None) -> Dict:
        """Generate a GOST-style technical PDF document"""
        try:
            from fpdf import FPDF
            pdf = FPDF(orientation='P', unit='mm', format='A4')
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=20)

            # GOST-style header — use Courier for Cyrillic support
            pdf.set_font("Courier", "B", 8)
            pdf.cell(0, 5, "MINISTERSTVO NAUKI (GOST DOC)", align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            pdf.cell(0, 5, "TECHNICAL DOCUMENTATION", align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(6)

            # Title
            pdf.set_font("Courier", "B", 14)
            pdf.cell(0, 10, title, align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(5)

            # Document info
            pdf.set_font("Courier", "", 9)
            pdf.cell(0, 5, f"Type: {doc_type.upper()}", new_x="LMARGIN", new_y="NEXT")
            pdf.cell(0, 5, f"Date: {datetime.now().strftime('%Y-%m-%d')}", new_x="LMARGIN", new_y="NEXT")
            pdf.cell(0, 5, f"Pages: {pdf.pages_count}", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(10)

            # Content
            pdf.set_font("Courier", "", 10)
            lines = content.split("\n") if content else [
                "1. GENERAL PROVISIONS",
                "",
                "1.1. This document defines technical requirements.",
                "1.2. Conforms to GOST 2.105-2019 standard.",
                "",
                "2. TECHNICAL SPECIFICATIONS",
                "",
                "2.1. AI Orchestrator v1.0",
                "2.2. Multi-agent architecture with isolated chat sessions.",
                "2.3. Local AI model support (TinyLlama 1.1B GGUF).",
                "2.4. Tools: shell, git, web search, SSH, files, PDF, images, video.",
                "",
                "3. ENVIRONMENT REQUIREMENTS",
                "",
                "3.1. Python 3.10+",
                "3.2. Windows/Linux/Android compatible.",
                "3.3. Offline operation without internet access.",
            ]
            for line in lines:
                if line.strip():
                    pdf.multi_cell(0, 5, line)
                else:
                    pdf.ln(2)

            if filename:
                path = self.out_dir / filename
            else:
                safe_title = "".join(c if c.isalnum() else "_" for c in title[:30])
                path = self.out_dir / f"{safe_title}_{datetime.now().strftime('%H%M%S')}.pdf"

            pdf.output(str(path))
            return {"path": str(path.relative_to(self.work_dir)), "pages": pdf.pages_count,
                    "title": title, "type": doc_type, "size": path.stat().st_size}
        except Exception as e:
            return {"error": str(e)}

    # --- UML diagram generation ---
    async def create_uml(self, description: str = "class diagram", width: int = 900,
                         height: int = 700, filename: str = None) -> Dict:
        """Generate UML diagrams as PNG using Pillow"""
        try:
            from PIL import Image, ImageDraw
            desc = description.lower()
            img = Image.new("RGB", (width, height), (13, 17, 23))
            draw = ImageDraw.Draw(img)

            if "class" in desc or "uml" in desc:
                # Class diagram with 2-4 classes
                bw, bh = 200, 160
                classes = [("User", ["id: int", "name: str", "email: str"], ["login()", "logout()"]),
                           ("Order", ["id: int", "user_id: int", "total: float"], ["create()", "pay()", "cancel()"]),
                           ("Product", ["id: int", "name: str", "price: float"], ["get_price()", "update_stock()"])]
                positions = [(60, 30), (360, 30), (660, 30), (60, 280)]
                for i, (cname, fields, methods) in enumerate(classes):
                    x, y = positions[i % len(positions)]
                    box_w, box_h = 180, 20 + len(fields) * 18 + 10 + len(methods) * 18
                    draw.rectangle([x, y, x + box_w, y + box_h], fill=(30, 40, 60),
                                   outline=(100, 200, 255), width=2)
                    draw.text((x + 10, y + 5), cname, fill=(255, 255, 100))
                    # Separator
                    draw.line([(x, y + 20), (x + box_w, y + 20)], fill=(100, 200, 255))
                    for j, f in enumerate(fields):
                        draw.text((x + 10, y + 24 + j * 18), f"- {f}", fill=(200, 200, 200))
                    draw.line([(x, y + 24 + len(fields) * 18), (x + box_w, y + 24 + len(fields) * 18)],
                              fill=(100, 200, 255))
                    for j, m in enumerate(methods):
                        draw.text((x + 10, y + 28 + len(fields) * 18 + j * 18),
                                  f"+ {m}", fill=(150, 255, 150))
                    # Association line
                    if i > 0:
                        px, py = positions[(i - 1) % len(positions)]
                        draw.line([(px + bw, py + bh // 2), (x, y + 20)],
                                   fill=(100, 200, 255), width=1)

            elif "sequence" in desc or "seq" in desc:
                actors = ["User", "System", "DB", "API"]
                actor_w = 100
                for i, a in enumerate(actors):
                    x = 100 + i * (actor_w + 60)
                    draw.text((x + 30, 20), a, fill=(255, 255, 100))
                    # Lifeline
                    draw.line([(x + actor_w // 2, 40), (x + actor_w // 2, height - 30)],
                              fill=(60, 120, 180), width=1)
                # Messages
                msgs = [("User", "System", "login()"), ("System", "DB", "SELECT *"),
                        ("DB", "System", "data"), ("System", "API", "GET /verify"),
                        ("API", "System", "ok"), ("System", "User", "Welcome!")]
                for i, (fr, to, msg) in enumerate(msgs):
                    y = 60 + i * 60
                    fx = 100 + actors.index(fr) * (actor_w + 60) + actor_w // 2
                    tx = 100 + actors.index(to) * (actor_w + 60) + actor_w // 2
                    draw.line([(fx, y), (tx, y)], fill=(200, 200, 200), width=1)
                    draw.text((min(fx, tx) + 5, y - 14), msg, fill=(150, 200, 255))
                    # Arrow
                    if tx > fx:
                        draw.polygon([(tx, y), (tx - 8, y - 4), (tx - 8, y + 4)], fill=(200, 200, 200))
                    else:
                        draw.polygon([(tx, y), (tx + 8, y - 4), (tx + 8, y + 4)], fill=(200, 200, 200))

            elif "use case" in desc or "usecase" in desc:
                actors = ["User", "Admin", "System"]
                use_cases = ["Login", "Register", "Order", "Pay", "Manage"]
                for i, a in enumerate(actors):
                    x, y = 30, 30 + i * 60
                    draw.ellipse([x, y, x + 100, y + 45], fill=(40, 60, 100), outline=(100, 200, 255))
                    draw.text((x + 20, y + 15), a, fill=(255, 255, 100))
                for i, uc in enumerate(use_cases):
                    x, y = 220, 30 + i * 55
                    draw.ellipse([x, y, x + 120, y + 40], fill=(30, 50, 80), outline=(150, 255, 150))
                    draw.text((x + 20, y + 12), uc, fill=(200, 255, 200))
                    # Connect to actor
                    ai = i % len(actors)
                    ax, ay = 30, 30 + ai * 60 + 22
                    draw.line([(ax + 100, ay), (x, y + 20)], fill=(100, 180, 255), width=1)

            elif "activity" in desc:
                nodes = [("Start", "circle"), ("Input Data", "box"), ("Process", "box"),
                         ("Decision", "diamond"), ("Output", "box"), ("End", "circle")]
                cx = width // 2
                for i, (label, ntype) in enumerate(nodes):
                    y = 20 + i * (height - 40) // len(nodes)
                    if ntype == "circle":
                        draw.ellipse([cx - 30, y, cx + 30, y + 30], fill=(60, 120, 60), outline=(100, 255, 100))
                        draw.text((cx - 20, y + 8), label, fill=(255, 255, 255))
                    elif ntype == "diamond":
                        draw.polygon([(cx, y), (cx + 30, y + 20), (cx, y + 40), (cx - 30, y + 20)],
                                     fill=(100, 100, 40), outline=(255, 255, 100))
                        draw.text((cx - 20, y + 14), label, fill=(255, 255, 200))
                    else:
                        draw.rectangle([cx - 50, y, cx + 50, y + 30], fill=(40, 60, 100),
                                       outline=(100, 200, 255))
                        draw.text((cx - 25, y + 8), label, fill=(255, 255, 255))
                    if i > 0:
                        py = 20 + (i - 1) * (height - 40) // len(nodes)
                        pbox_h = 30 if i > 0 else 30
                        draw.line([(cx, py + pbox_h), (cx, y)], fill=(100, 200, 255), width=1)
            else:
                # Default UML
                return await self.create_diagram("flowchart", width, height, filename)

            if filename:
                path = self.out_dir / filename
            else:
                path = self.out_dir / f"uml_{datetime.now().strftime('%H%M%S')}.png"
            img.save(str(path), "PNG")
            return {"path": str(path.relative_to(self.work_dir)), "type": description,
                    "width": width, "height": height, "size": path.stat().st_size}
        except Exception as e:
            return {"error": str(e)}

    # --- Agent creation ---
    async def create_agent(self, description: str, name: str = None,
                           tools: str = "", system_prompt: str = "") -> Dict:
        """Generate a new agent Python file and register it"""
        try:
            agent_name = name or description.lower().replace(" ", "_")[:20]
            if not system_prompt:
                system_prompt = (
                    f"You are a {description} agent. "
                    f"Available tools: {tools or 'search, shell, git, file, image, video, pdf, create image/gif/video/pdf/music/diagram/gost/uml'}. "
                    f"Be concise and helpful."
                )

            # Generate the agent module
            agent_code = '''\"\"\"
Auto-generated agent: {name}
Description: {desc}
\"\"\"

async def handle(orch, message, chat):
    """Main handler for {name} agent"""
    response = []
    async for chunk in orch._process_with_plugins(chat, message):
        response.append(chunk)
    return "".join(response)
'''.format(name=agent_name, desc=description)

            agent_dir = Path(self.work_dir) / "agents"
            agent_dir.mkdir(exist_ok=True)
            init_file = agent_dir / "__init__.py"
            if not init_file.exists():
                init_file.write_text("# Auto-created agents package\n")

            agent_file = agent_dir / f"{agent_name}.py"
            agent_file.write_text(agent_code, encoding="utf-8")

            # Register in the main server by appending to config
            config_line = f'"{agent_name}": AgentConfig(name="{agent_name}", model="tinyllama", system_prompt="""{system_prompt}"""),\n'
            config_path = Path(self.work_dir) / "ai_orchestrator" / "agentic_chat.py"
            content = config_path.read_text(encoding="utf-8")
            marker = "# --- END AUTO AGENTS ---"
            if marker not in content:
                marker = '"""\nAgentic Chat System'
            content = content.replace(marker, f'{config_line}{marker}')
            config_path.write_text(content, encoding="utf-8")

            return {"agent_name": agent_name, "file": str(agent_file.relative_to(self.work_dir)),
                    "system_prompt": system_prompt[:100],
                    "status": "created - restart server to activate"}
        except Exception as e:
            return {"error": str(e)}

    # --- Code generation (write + run) ---
    async def create_code(self, description: str, filename: str = None) -> Dict:
        """Generate Python code from description, save to file, and run it."""
        try:
            if not filename:
                safe = re.sub(r'[^a-z0-9]+', '_', description.lower())[:30].strip('_')
                filename = f"generated/{safe}.py" if safe else f"generated/script_{uuid.uuid4().hex[:6]}.py"
            if not filename.endswith('.py'):
                filename += '.py'
            # Placeholder — actual LLM generates the code in process()
            code_template = f'''"""
Code generated by code_dev agent
Description: {description}
"""
import sys
import os

def main():
    # TODO: LLM will fill this
    print("Code generation in progress...")

if __name__ == "__main__":
    main()
'''
            out_path = self.work_dir / filename
            out_path.parent.mkdir(exist_ok=True)
            out_path.write_text(code_template, encoding="utf-8")
            return {"path": str(out_path.relative_to(self.work_dir)),
                    "lines": code_template.count("\n"),
                    "status": "template created"}
        except Exception as e:
            return {"error": str(e)}

    # --- Game creation ---
    async def create_game(self, description: str = "simple game", engine: str = "pygame",
                          filename: str = None) -> Dict:
        """Generate and run a game using pygame"""
        try:
            import importlib.util
            desc = description.lower()

            if "snake" in desc or "зме" in desc or "snak" in desc:
                code = '''import pygame, sys, random
pygame.init()
W, H = 400, 400
screen = pygame.display.set_mode((W, H))
clock = pygame.time.Clock()
snake = [(100, 100)]
dx, dy = 20, 0
food = (random.randrange(0, W, 20), random.randrange(0, H, 20))
score = 0
font = pygame.font.SysFont("Arial", 20)
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT: running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_UP and dy == 0: dx, dy = 0, -20
            if event.key == pygame.K_DOWN and dy == 0: dx, dy = 0, 20
            if event.key == pygame.K_LEFT and dx == 0: dx, dy = -20, 0
            if event.key == pygame.K_RIGHT and dx == 0: dx, dy = 20, 0
    head = (snake[0][0] + dx, snake[0][1] + dy)
    if head[0] < 0 or head[0] >= W or head[1] < 0 or head[1] >= H: running = False
    if head in snake[1:]: running = False
    snake.insert(0, head)
    if head == food:
        score += 1
        food = (random.randrange(0, W, 20), random.randrange(0, H, 20))
    else:
        snake.pop()
    screen.fill((0, 0, 0))
    for s in snake: pygame.draw.rect(screen, (0, 255, 0), (*s, 20, 20))
    pygame.draw.rect(screen, (255, 0, 0), (*food, 20, 20))
    screen.blit(font.render(f"Score: {score}", True, (255, 255, 255)), (10, 10))
    pygame.display.flip()
    clock.tick(10)
pygame.quit()
sys.exit()
'''
                title = "Snake"
            elif "pong" in desc or "tennis" in desc or "понг" in desc or "теннис" in desc or "ping" in desc:
                code = '''import pygame, sys, random
pygame.init()
W, H = 600, 400
screen = pygame.display.set_mode((W, H))
clock = pygame.time.Clock()
p1 = p2 = H // 2 - 30
bx, by = W // 2, H // 2
bvx, bvy = 5 * random.choice([-1, 1]), 3 * random.choice([-1, 1])
s1 = s2 = 0
font = pygame.font.SysFont("Arial", 30)
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT: running = False
    keys = pygame.key.get_pressed()
    if keys[pygame.K_w] and p1 > 0: p1 -= 5
    if keys[pygame.K_s] and p1 < H - 60: p1 += 5
    if keys[pygame.K_UP] and p2 > 0: p2 -= 5
    if keys[pygame.K_DOWN] and p2 < H - 60: p2 += 5
    bx += bvx; by += bvy
    if by <= 0 or by >= H: bvy = -bvy
    if bx <= 20 and p1 <= by <= p1 + 60: bvx = -bvx; bvx *= 1.05
    if bx >= W - 30 and p2 <= by <= p2 + 60: bvx = -bvx; bvx *= 1.05
    if bx < 0: s2 += 1; bx, by = W // 2, H // 2; bvx = 5 * random.choice([-1, 1])
    if bx > W: s1 += 1; bx, by = W // 2, H // 2; bvx = 5 * random.choice([-1, 1])
    screen.fill((0, 0, 0))
    pygame.draw.rect(screen, (255, 255, 255), (10, p1, 10, 60))
    pygame.draw.rect(screen, (255, 255, 255), (W - 20, p2, 10, 60))
    pygame.draw.circle(screen, (255, 255, 255), (bx, by), 8)
    pygame.draw.aaline(screen, (60, 60, 60), (W // 2, 0), (W // 2, H))
    screen.blit(font.render(str(s1), True, (255, 255, 255)), (W // 2 - 50, 20))
    screen.blit(font.render(str(s2), True, (255, 255, 255)), (W // 2 + 35, 20))
    pygame.display.flip()
    clock.tick(60)
pygame.quit()
sys.exit()
'''
                title = "Pong"
            elif "tetris" in desc or "tetromino" in desc or "тетрис" in desc or "тетрамино" in desc:
                code = '''import pygame, sys, random
pygame.init()
W, H, S = 200, 400, 20
screen = pygame.display.set_mode((W, H))
clock = pygame.time.Clock()
grid = [[0]*10 for _ in range(20)]
shapes = [[(0,0),(1,0),(2,0),(3,0)],[(0,0),(1,0),(0,1),(1,1)],[(0,0),(1,0),(1,1),(2,1)],
          [(0,1),(1,1),(1,0),(2,0)],[(0,0),(1,0),(1,1),(2,1)],[(0,1),(1,1),(1,0),(2,0)],
          [(0,0),(1,0),(0,1),(1,1)]]
colors = [(0,255,255),(255,255,0),(128,0,128),(0,255,0),(255,0,0),(0,0,255),(255,128,0)]
piece = {"shape":random.choice(shapes),"x":3,"y":0,"color":random.choice(colors)}
score, font, running = 0, pygame.font.SysFont("Arial", 15), True
def collide(s,x,y): return any((x+dx<0 or x+dx>=10 or y+dy>=20 or grid[y+dy][x+dx]) for dx,dy in s)
def merge(s,x,y,c):
    for dx,dy in s: grid[y+dy][x+dx]=c
def clear():
    global score
    full=[i for i,r in enumerate(grid) if all(r)]
    for i in full: del grid[i]; grid.insert(0,[0]*10); score+=100
while running:
    for event in pygame.event.get():
        if event.type==pygame.QUIT: running=False
        if event.type==pygame.KEYDOWN:
            if event.key==pygame.K_LEFT: piece["x"]-=0 if collide(piece["shape"],piece["x"]-1,piece["y"]) else 1
            if event.key==pygame.K_RIGHT: piece["x"]+=0 if collide(piece["shape"],piece["x"]+1,piece["y"]) else 1
            if event.key==pygame.K_DOWN: piece["y"]+=0 if collide(piece["shape"],piece["x"],piece["y"]+1) else 1
            if event.key==pygame.K_UP: piece["shape"]=list(zip(*piece["shape"][::-1]))
    if collide(piece["shape"],piece["x"],piece["y"]+1):
        merge(piece["shape"],piece["x"],piece["y"],piece["color"])
        clear()
        piece={"shape":random.choice(shapes),"x":3,"y":0,"color":random.choice(colors)}
        if collide(piece["shape"],piece["x"],piece["y"]): running=False
    else: piece["y"]+=1
    screen.fill((0,0,0))
    for y in range(20):
        for x in range(10):
            if grid[y][x]: pygame.draw.rect(screen,grid[y][x],(x*S,y*S,S,S),0)
    for dx,dy in piece["shape"]:
        pygame.draw.rect(screen,piece["color"],((piece["x"]+dx)*S,(piece["y"]+dy)*S,S,S),0)
    screen.blit(font.render(f"Score: {score}",True,(255,255,255)),(10,10))
    pygame.display.flip(); clock.tick(10)
pygame.quit()
sys.exit()
'''
                title = "Tetris"
            else:
                code = '''import pygame, sys, random
pygame.init()
W, H = 400, 400
screen = pygame.display.set_mode((W, H))
clock = pygame.time.Clock()
font = pygame.font.SysFont("Arial", 30)
px, py = W // 2, H // 2
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT: running = False
    keys = pygame.key.get_pressed()
    if keys[pygame.K_LEFT]: px -= 5
    if keys[pygame.K_RIGHT]: px += 5
    if keys[pygame.K_UP]: py -= 5
    if keys[pygame.K_DOWN]: py += 5
    screen.fill((0, 0, 0))
    pygame.draw.circle(screen, (0, 200, 255), (px, py), 20)
    pygame.draw.rect(screen, (255, 255, 0), (random.randint(0, W-10), random.randint(0, H-10), 10, 10))
    screen.blit(font.render("Move with arrows", True, (255, 255, 255)), (100, 350))
    pygame.display.flip(); clock.tick(60)
pygame.quit()
sys.exit()
'''
                title = "Move Game"

            if filename:
                path = self.out_dir / filename
            else:
                path = self.out_dir / f"game_{title.lower()}_{datetime.now().strftime('%H%M%S')}.py"
            path.write_text(code, encoding="utf-8")

            # Create launcher script
            bat_path = path.with_suffix(".bat") if sys.platform == "win32" else path.with_suffix(".sh")
            if sys.platform == "win32":
                bat_path.write_text(f'@echo off\npython "{path.absolute()}"\npause', encoding="utf-8")

            return {"title": title, "path": str(path.relative_to(self.work_dir)),
                    "launcher": str(bat_path.relative_to(self.work_dir)) if bat_path.exists() else None,
                    "lines": len(code.splitlines()), "status": "created"}
        except Exception as e:
            return {"error": str(e)}


    async def _handle_git(self, t: str, text: str) -> str:
        if "clone" in t:
            m = re.search(r"git clone\s+(\S+)(?:\s+(\S+))?", text, re.I)
            if m:
                r = await self.executor.git_clone(m.group(1), m.group(2))
                out = r.get("stdout", "") or r.get("stderr", "") or r.get("error", "")
                return f"Git clone:\n{out[:2000]}"
            return "Usage: git clone <url> [path]"

        if "init" in t:
            r = await self.executor.git_init()
            out = r.get("stdout", "") or r.get("stderr", "") or r.get("error", "")
            return f"Git init:\n{out[:2000]}"

        if "status" in t:
            r = await self.executor.git_status()
            out = r.get("stdout", "") or r.get("stderr", "") or r.get("error", "")
            return f"Git status:\n{out[:2000]}"

        if "log" in t:
            r = await self.executor.git_log()
            out = r.get("stdout", "") or r.get("stderr", "") or r.get("error", "")
            return f"Git log:\n{out[:2000]}"

        if "commit" in t:
            m = re.search(r'git commit\s+-m\s+["\']([^"\']+)["\']', text, re.I)
            msg = m.group(1) if m else "update"
            r = await self.executor.git_commit(message=msg)
            out = r.get("stdout", "") or r.get("stderr", "") or r.get("error", "")
            return f"Git commit:\n{out[:2000]}"

        if "push" in t:
            r = await self.executor.git_push()
            out = r.get("stdout", "") or r.get("stderr", "") or r.get("error", "")
            return f"Git push:\n{out[:2000]}"

        if "pull" in t:
            r = await self.executor.git_pull()
            out = r.get("stdout", "") or r.get("stderr", "") or r.get("error", "")
            return f"Git pull:\n{out[:2000]}"

        if "branch" in t:
            m = re.search(r"git branch\s+(.+)", text, re.I)
            if m:
                r = await self.executor.git_branch(name=m.group(1).strip(), create=True)
            else:
                r = await self.executor.git_branch()
            out = r.get("stdout", "") or r.get("stderr", "") or r.get("error", "")
            return f"Git branch:\n{out[:2000]}"

        return "Unknown git command. Available: clone, init, status, log, commit, push, pull, branch"

    def get_history(self):
        return [m for m in self.messages if m["role"] != "system"]

    async def close(self):
        await self.executor.close()


class Cache:
    """Memoize task results to avoid repeated execution"""

    def __init__(self, max_size: int = 100, ttl_sec: int = 300):
        self._data: Dict[str, Dict] = {}
        self._max_size = max_size
        self._ttl_sec = ttl_sec

    def _key(self, agent: str, message: str) -> str:
        return f"{agent}:{message.strip().lower()[:100]}"

    def get(self, agent: str, message: str) -> Optional[str]:
        key = self._key(agent, message)
        entry = self._data.get(key)
        if not entry:
            return None
        if (datetime.now() - entry["ts"]).total_seconds() > self._ttl_sec:
            del self._data[key]
            return None
        return entry["result"]

    def set(self, agent: str, message: str, result: str):
        key = self._key(agent, message)
        if len(self._data) >= self._max_size:
            oldest = min(self._data.keys(), key=lambda k: self._data[k]["ts"])
            del self._data[oldest]
        self._data[key] = {"result": result, "ts": datetime.now()}

    @property
    def size(self):
        return len(self._data)


class BackendType(Enum):
    GPT4ALL = "gpt4all"
    TINYLLAMA = "tinyllama"
    GGUF = "gguf"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"

BACKEND_ALIASES = {
    "gpt4all": BackendType.GPT4ALL,
    "gpt": BackendType.OPENAI,
    "openai": BackendType.OPENAI,
    "chatgpt": BackendType.OPENAI,
    "claude": BackendType.ANTHROPIC,
    "anthropic": BackendType.ANTHROPIC,
    "gemini": BackendType.GEMINI,
    "google": BackendType.GEMINI,
    "tinyllama": BackendType.TINYLLAMA,
    "local": BackendType.GPT4ALL,
    "gguf": BackendType.GGUF,
    "qwen": BackendType.GGUF,
    "llama": BackendType.GGUF,
    "mistral": BackendType.GGUF,
    "deepseek": BackendType.GGUF,
}

class LLMBackend:
    """Unified interface: gguf (llama.cpp server), tinyllama (ctransformers), gpt4all, openai/anthropic/gemini."""

    def __init__(self, backend: str, api_key: str = "", model_name: str = ""):
        self.backend_type = BACKEND_ALIASES.get(backend.lower().strip(), BackendType.GGUF)
        self.api_key = api_key
        self.model_name = model_name
        self._gpt4all = None
        self._tinyllama = None
        self._llama_server = None

    def _get_gpt4all(self):
        if self._gpt4all is None:
            from gpt4all import GPT4All
            name = self.model_name or "orca-mini-3b-gguf2-q4_0.gguf"
            self._gpt4all = GPT4All(name)
            logger.info(f"GPT4All model '{name}' loaded")
        return self._gpt4all

    def _get_gguf_path(self, model_name: str = "") -> str:
        """Find a GGUF file in cache dirs by name prefix. Returns path or empty string."""
        if model_name:
            cache_dir = Path.home() / ".cache" / "ctransformers"
            if cache_dir.exists():
                for f in cache_dir.iterdir():
                    if model_name.lower() in f.name.lower() and f.suffix == ".gguf":
                        return str(f)
            if Path(model_name).exists():
                return model_name
        return ""

    def _ensure_llama_server(self):
        """Lazy-start llama.cpp server if not running."""
        if self._llama_server is not None:
            return self._llama_server
        try:
            from .llama_cpp_backend import LlamaCppServer, DEFAULT_PORT
        except ImportError:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from llama_cpp_backend import LlamaCppServer, DEFAULT_PORT
        path = self._get_gguf_path(self.model_name)
        if not path:
            cache_dir = Path.home() / ".cache" / "ctransformers"
            if cache_dir.exists():
                gguvs = sorted(cache_dir.glob("*.gguf"), key=lambda f: f.stat().st_size)
                if gguvs:
                    path = str(gguvs[-1])
        if not path:
            raise FileNotFoundError("No GGUF model found in cache. Download one first.")
        self._llama_server = LlamaCppServer(path, port=DEFAULT_PORT)
        return self._llama_server

    def _get_tinyllama(self):
        if self._tinyllama is None:
            import os
            import multiprocessing
            n_threads = multiprocessing.cpu_count()
            os.environ["OMP_NUM_THREADS"] = str(n_threads)
            from ctransformers import AutoModelForCausalLM
            path = self._get_gguf_path(self.model_name)
            if not path:
                cache_dir = Path.home() / ".cache" / "ctransformers"
                if cache_dir.exists():
                    # Prefer Q8_0 over Q4_K_M
                    candidates = [f for f in cache_dir.iterdir() if "tinyllama" in f.name.lower() and f.suffix == ".gguf"]
                    q8 = [f for f in candidates if "Q8" in f.name]
                    if q8:
                        path = str(q8[0])
                    elif candidates:
                        path = str(candidates[0])
            if not path:
                raise FileNotFoundError("No TinyLlama model found. Download tinyllama-1.1b-chat-v1.0.Q2_K.gguf")
            from ctransformers import AutoConfig
            config = AutoConfig.from_pretrained(path)
            config.context_length = 2048
            config.batch_size = 512
            config.threads = n_threads
            self._tinyllama = AutoModelForCausalLM.from_pretrained(path, model_type="llama", config=config)
            logger.info(f"TinyLlama loaded: {path}, threads={n_threads}")
        return self._tinyllama

    async def generate_async(self, prompt: str, max_tokens: int = 100, temperature: float = 0.7) -> str:
        """Async generate via llama.cpp server (for GGUF backend)."""
        if self.backend_type not in (BackendType.GGUF, BackendType.TINYLLAMA):
            return self.generate(prompt, max_tokens, temperature)
        server = self._ensure_llama_server()
        if not server.process:
            ok = await server.start()
            if not ok:
                return "Error: could not start llama.cpp server"
        return await server.generate(prompt, max_tokens, temperature)

    async def generate_stream_async(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.7):
        """Async streaming: TinyLlama via ctransformers, GGUF via llama.cpp server."""
        if self.backend_type == BackendType.TINYLLAMA:
            text = self.generate(prompt, max_tokens, temperature)
            for i in range(0, len(text), 3):
                yield text[i : i + 3]
                await asyncio.sleep(0.01)
            return
        if self.backend_type not in (BackendType.GGUF,):
            yield self.generate(prompt, max_tokens, temperature)
            return
        server = self._ensure_llama_server()
        if not server.process:
            logger.info("Starting llama.cpp server (lazy init)...")
            ok = await server.start()
            if not ok:
                yield "[llama-server failed to start — check stderr or memory]"
                return
            logger.info("llama.cpp server is running, generating...")
        async for token in server.generate_stream(prompt, max_tokens, temperature):
            yield token

    def generate(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.7) -> str:
        if self.backend_type == BackendType.TINYLLAMA:
            llm = self._get_tinyllama()
            return llm(prompt, max_new_tokens=max_tokens, temperature=temperature)
        elif self.backend_type == BackendType.OPENAI:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            model = self.model_name or "gpt-4o-mini"
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content
        elif self.backend_type == BackendType.ANTHROPIC:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            model = self.model_name or "claude-3-haiku-20240307"
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text
        elif self.backend_type == BackendType.GEMINI:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            model_name = self.model_name or "gemini-2.0-flash"
            model = genai.GenerativeModel(model_name)
            resp = model.generate_content(prompt)
            return resp.text
        else:  # GPT4ALL
            llm = self._get_gpt4all()
            return llm.generate(prompt, max_tokens=max_tokens, temp=temperature)

    def generate_stream(self, prompt: str, max_tokens: int = 100, temperature: float = 0.7):
        if self.backend_type == BackendType.TINYLLAMA:
            llm = self._get_tinyllama()
            for token in llm(prompt, max_new_tokens=max_tokens, temperature=temperature, stream=True):
                yield token
        elif self.backend_type == BackendType.OPENAI:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            model = self.model_name or "gpt-4o-mini"
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            for chunk in resp:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        elif self.backend_type == BackendType.ANTHROPIC:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            model = self.model_name or "claude-3-haiku-20240307"
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    yield text
        elif self.backend_type == BackendType.GEMINI:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            model_name = self.model_name or "gemini-2.0-flash"
            model = genai.GenerativeModel(model_name)
            resp = model.generate_content(prompt, stream=True)
            for chunk in resp:
                if chunk.text:
                    yield chunk.text
        else:  # GPT4ALL
            llm = self._get_gpt4all()
            for token in llm.generate(prompt, max_tokens=max_tokens, temp=temperature, streaming=True):
                yield token

    def __del__(self):
        self._gpt4all = None
        self._tinyllama = None
        if self._llama_server:
            try:
                import asyncio
                asyncio.get_event_loop().run_until_complete(self._llama_server.stop())
            except Exception:
                pass


class Orchestrator:
    def __init__(self):
        # Set CPU affinity to all available cores at startup
        self._set_cpu_affinity_all()

        # Load LLM backend: try TinyLlama first, fallback to GPT4All
        self._llm = self._init_llm_backend()
        self.chats: Dict[str, AgentChat] = {}
        self._semaphore = asyncio.Semaphore(4)
        self._queue = asyncio.Queue()
        self._workers = 0
        self._worker_tasks = []
        self._cache = Cache()
        self._task_times: Dict[str, float] = {}
        self._history_dir = Path(__file__).parent / "histories"
        self._history_dir.mkdir(exist_ok=True)
        self._checkpoint = Checkpoint()
        self._checkpoint.start_heartbeat()
        # Plugin system
        try:
            from .plugin_system import PluginManager
            self._plugin_mgr = PluginManager()
        except ImportError:
            try:
                # Fallback: direct import
                plugin_path = Path(__file__).parent / "plugin_system.py"
                if plugin_path.exists():
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("plugin_system", str(plugin_path))
                    pm_mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(pm_mod)
                    self._plugin_mgr = pm_mod.PluginManager()
                else:
                    self._plugin_mgr = None
                    logger.warning("plugin_system.py not found")
            except Exception as e:
                logger.warning(f"Plugin system init: {e}")
                self._plugin_mgr = None
        except Exception as e:
            logger.warning(f"Plugin system init: {e}")
            self._plugin_mgr = None

        if self._plugin_mgr:
            try:
                count = self._plugin_mgr.load_all()
                if count:
                    logger.info(f"Loaded {count} plugin(s)")
                self._plugin_mgr.start_watcher()
            except Exception as e:
                logger.warning(f"Plugin load error: {e}")

        # --- Night Mode ---
        self._night_mode = {
            "enabled": False,
            "start_hour": 22,      # 10 PM
            "end_hour": 8,         # 8 AM
            "max_semaphore": 2,    # reduce from 4 to 2 at night
            "reduce_cache_ttl": True,
            "idle_cleanup_minutes": 15,  # more aggressive cleanup at night
        }
        self._night_mode_task: Optional[asyncio.Task] = None
        self._is_night = False

    def _init_llm_backend(self) -> Optional['LLMBackend']:
        """Load best available local LLM. GGUF models use llama.cpp server (async)."""
        model_name = os.environ.get("OPCODE_LLM_MODEL", "").lower()
        api_key = os.environ.get("OPCODE_LLM_KEY", os.environ.get("OPENAI_API_KEY", ""))

        if model_name:
            backend = model_name
        else:
            # Auto-detect best cached GGUF
            cache_dir = Path.home() / ".cache" / "ctransformers"
            if cache_dir.exists():
                gguvs = sorted(cache_dir.glob("*.gguf"), key=lambda f: f.stat().st_size)
                if gguvs:
                    best = gguvs[-1].stem
                    backend = "gguf"
                    model_name = best
                    logger.info(f"Auto-detected GGUF: {best}")
                else:
                    backend = "tinyllama"
                    model_name = ""
            else:
                backend = "tinyllama"
                model_name = ""

        # For GGUF backend: need AVX2 — user's Sandy Bridge only has AVX. Fallback to TinyLlama.
        if backend == "gguf":
            logger.warning(f"GGUF server requires AVX2 — not available on this CPU. Falling back to TinyLlama.")
            backend = "tinyllama"
            model_name = ""

        # For tinyllama/ctransformers: load synchronously
        llm = LLMBackend("tinyllama", api_key=api_key)
        try:
            llm._get_tinyllama()
            logger.info("LLM backend active: tinyllama (ctransformers)")
            return llm
        except Exception as e:
            logger.warning(f"TinyLlama failed: {e}")
        logger.warning("No LLM backend available — using fallback responses")
        return None

    def _set_cpu_affinity_all(self):
        """Bind Python process to all available CPU cores."""
        try:
            import psutil
            p = psutil.Process()
            # Get all logical CPU cores
            all_cpus = list(range(psutil.cpu_count(logical=True)))
            p.cpu_affinity(all_cpus)
            logger.info(f"CPU affinity set to {len(all_cpus)} cores: {all_cpus}")
        except ImportError:
            try:
                import os
                # Windows: use Win32 API via ctypes
                import ctypes
                kernel32 = ctypes.windll.kernel32
                # Get system CPU count
                sys_info = ctypes.create_string_buffer(36)  # SYSTEM_INFO structure
                kernel32.GetSystemInfo(sys_info)
                cpu_count = int.from_bytes(sys_info[4:8], 'little')  # dwNumberOfProcessors
                mask = (1 << cpu_count) - 1  # bitmask for all CPUs
                pid = os.getpid()
                handle = kernel32.OpenProcess(0x1F0FFF, False, pid)  # PROCESS_ALL_ACCESS
                if handle:
                    kernel32.SetProcessAffinityMask(handle, mask)
                    kernel32.CloseHandle(handle)
                    logger.info(f"CPU affinity set to {cpu_count} cores via ctypes")
            except Exception as e:
                logger.warning(f"Could not set CPU affinity: {e}")

    def _is_night_time(self) -> bool:
        """Check if current time is within night mode hours."""
        if not self._night_mode["enabled"]:
            return False
        now = datetime.now().hour
        start = self._night_mode["start_hour"]
        end = self._night_mode["end_hour"]
        if start > end:  # crosses midnight (e.g., 22:00-08:00)
            return now >= start or now < end
        return start <= now < end

    async def _night_mode_loop(self):
        """Background task: check every 5 minutes if night mode should toggle."""
        while True:
            try:
                is_night = self._is_night_time()
                if is_night != self._is_night:
                    self._is_night = is_night
                    if is_night:
                        # Enter night mode: reduce semaphore
                        old = self._semaphore._value
                        max_sem = self._night_mode["max_semaphore"]
                        if old > max_sem:
                            # Reduce semaphore — drain gradually
                            diff = old - max_sem
                            for _ in range(diff):
                                await self._semaphore.acquire()
                        logger.info(f"Night mode ON: semaphore {old}->{max_sem}")
                        # Reduce cache TTL
                        if self._night_mode["reduce_cache_ttl"]:
                            self._cache.ttl_sec = 600  # longer cache at night
                        # Aggressive cleanup
                        await self.cleanup_idle(max_idle_minutes=self._night_mode["idle_cleanup_minutes"])
                    else:
                        # Exit night mode: restore semaphore
                        current = self._semaphore._value
                        target = 4
                        if current < target:
                            for _ in range(target - current):
                                self._semaphore.release()
                        logger.info(f"Night mode OFF: semaphore restored to 4")
                        if self._night_mode["reduce_cache_ttl"]:
                            self._cache.ttl_sec = 300
            except Exception as e:
                logger.warning(f"Night mode check error: {e}")
            await asyncio.sleep(300)  # check every 5 minutes

    def start_night_mode(self):
        """Start the night mode background checker."""
        if not self._night_mode_task:
            self._night_mode_task = asyncio.create_task(self._night_mode_loop())

    def stop_night_mode(self):
        """Stop the night mode background checker."""
        if self._night_mode_task:
            self._night_mode_task.cancel()
            self._night_mode_task = None

    def set_night_mode(self, config: Dict):
        """Update night mode configuration."""
        for key in ("enabled", "start_hour", "end_hour", "max_semaphore", "reduce_cache_ttl", "idle_cleanup_minutes"):
            if key in config:
                self._night_mode[key] = config[key]
        if config.get("enabled"):
            self.start_night_mode()
        else:
            self.stop_night_mode()
            self._is_night = False

    def get_night_mode(self) -> Dict:
        return {
            **self._night_mode,
            "is_night": self._is_night,
            "current_semaphore": self._semaphore._value,
        }

    # --- Chat management ---
    def create_chat(self, name: str, config: AgentConfig) -> AgentChat:
        chat = AgentChat(config, llm=self._llm, orchestrator=self)
        # Restore persistent memory
        self._restore_history(name, chat)
        self.chats[name] = chat
        return chat

    def get_chat(self, name: str) -> Optional[AgentChat]:
        chat = self.chats.get(name)
        if not chat and name in DEFAULT_AGENTS:
            chat = self.create_chat(name, DEFAULT_AGENTS[name])
        return chat

    def list_chats(self) -> List[str]:
        return list(self.chats.keys())

    # --- Plugin hook wrapper for chat processing ---
    async def _process_with_plugins(self, chat: AgentChat, message: str) -> AsyncGenerator[str, None]:
        """Wrap chat.process() with plugin hooks for message/response interception."""
        if self._plugin_mgr:
            context = {"agent": chat.config.name, "session_id": chat.session_id}
            message = self._plugin_mgr.dispatch_message(chat.config.name, message, context)
        async for chunk in chat.process(message):
            if self._plugin_mgr and '"done"' not in chunk and '"token"' in chunk:
                try:
                    data = json.loads(chunk.strip())
                    if "token" in data:
                        context = {"agent": chat.config.name, "session_id": chat.session_id}
                        modified = self._plugin_mgr.dispatch_response(chat.config.name, data["token"], context)
                        if modified != data["token"]:
                            yield json.dumps({"token": modified}) + "\n"
                            continue
                except Exception:
                    pass
            yield chunk

    # --- Persistent memory (disk-backed) ---
    def _history_path(self, name: str) -> Path:
        return self._history_dir / f"{name}.json"

    def _save_history(self, name: str, chat: AgentChat):
        try:
            path = self._history_path(name)
            data = {
                "agent": name,
                "session_id": chat.session_id,
                "messages": chat.messages,
                "saved_at": datetime.now().isoformat(),
            }
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _restore_history(self, name: str, chat: AgentChat):
        try:
            path = self._history_path(name)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                chat.messages = data.get("messages", chat.messages)
                chat.session_id = data.get("session_id", chat.session_id)
        except Exception:
            pass

    # --- History search / export / reset ---
    async def search_history(self, query: str, agent: str = None) -> List[Dict]:
        """Search across all histories for messages matching query"""
        results = []
        hist_dir = self._history_dir
        if not hist_dir.exists():
            return results

        files = [hist_dir / f"{agent}.json"] if agent else list(hist_dir.glob("*.json"))
        for fp in files:
            if not fp.exists():
                continue
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                agent_name = data.get("agent", fp.stem)
                for msg in data.get("messages", []):
                    content = msg.get("content", "")
                    if query.lower() in content.lower():
                        results.append({
                            "agent": agent_name,
                            "session_id": data.get("session_id", ""),
                            "role": msg.get("role", ""),
                            "content": content[:500],
                            "timestamp": msg.get("timestamp", ""),
                        })
            except Exception:
                continue
        return results

    async def export_history(self, agent: str = None, format: str = "json") -> str:
        """Export history as JSON, CSV, or Markdown"""
        if agent:
            data_list = []
            fp = self._history_path(agent)
            if fp.exists():
                try:
                    data_list.append(json.loads(fp.read_text(encoding="utf-8")))
                except Exception:
                    pass
        else:
            data_list = []
            for fp in sorted(self._history_dir.glob("*.json")):
                try:
                    data_list.append(json.loads(fp.read_text(encoding="utf-8")))
                except Exception:
                    continue

        if format == "csv":
            lines = ["agent,session_id,role,content,timestamp"]
            for data in data_list:
                agent_name = data.get("agent", "?")
                session_id = data.get("session_id", "")
                for msg in data.get("messages", []):
                    content = msg.get("content", "").replace('"', '""')
                    lines.append(f'"{agent_name}","{session_id}","{msg.get("role","")}","{content[:500]}","{msg.get("timestamp","")}"')
            return "\n".join(lines)

        elif format == "md":
            parts = []
            for data in data_list:
                agent_name = data.get("agent", "?")
                parts.append(f"# History: {agent_name}\n")
                for msg in data.get("messages", []):
                    role = msg.get("role", "unknown").upper()
                    content = msg.get("content", "")
                    ts = msg.get("timestamp", "")
                    parts.append(f"## {role} ({ts})\n\n{content}\n\n")
            return "\n".join(parts)

        else:
            return json.dumps(data_list, indent=2, ensure_ascii=False)

    async def reset_history(self, agent: str = None) -> int:
        """Reset (clear) history for one or all agents. Returns count of cleared histories."""
        if agent:
            chat = self.chats.get(agent)
            if chat:
                chat.messages = [chat.messages[0]] if chat.messages else []  # keep system prompt
                self._save_history(agent, chat)
            fp = self._history_path(agent)
            if fp.exists():
                fp.unlink()
            return 1

        count = 0
        for fp in list(self._history_dir.glob("*.json")):
            fp.unlink()
            count += 1
        for name, chat in self.chats.items():
            chat.messages = [chat.messages[0]] if chat.messages else []
        return count

    def save_all_histories(self):
        for name, chat in self.chats.items():
            self._save_history(name, chat)

    # --- Queue & workers ---
    async def enqueue(self, agent_name: str, message: str):
        await self._queue.put((agent_name, message))
        if self._workers < 4:
            self._workers += 1
            t = asyncio.create_task(self._worker_loop())
            self._worker_tasks.append(t)

    async def _worker_loop(self):
        while not self._queue.empty():
            agent_name, message = await self._queue.get()
            chat = self.get_chat(agent_name)
            if not chat:
                self._queue.task_done()
                continue
            async with self._semaphore:
                self._checkpoint.save(
                    agent=agent_name,
                    goal=message[:120],
                    status="in_progress",
                    context={"last_task": message[:500], "in_queue": self._queue.qsize()},
                )
                start = datetime.now()
                async for _ in self._process_with_plugins(chat, message):
                    pass
                elapsed = (datetime.now() - start).total_seconds()
                self._task_times[agent_name] = elapsed
                self._save_history(agent_name, chat)
                self._checkpoint.mark_done(f"Agent {agent_name} completed in {elapsed:.1f}s")
            self._queue.task_done()
        self._workers -= 1

    # --- Pipeline: chain agents ---
    async def pipeline(self, steps: List[Dict]) -> str:
        """Run a chain of agents, passing results between them.
        steps: [{"agent": "researcher", "prompt": "search X"}, {"agent": "analyst", "prompt": "analyze: {prev}"}]"""
        result = ""
        self._checkpoint.save(
            agent="pipeline",
            goal=f"Pipeline: {len(steps)} steps",
            status="in_progress",
            task_plan=[{"step": i, "agent": s.get("agent"), "desc": s.get("prompt", "")[:80]} for i, s in enumerate(steps)],
        )
        for i, step in enumerate(steps):
            agent_name = step.get("agent", "researcher")
            prompt = step.get("prompt", "").replace("{prev}", result)
            chat = self.get_chat(agent_name)
            if not chat:
                self._checkpoint.mark_failed(f"Agent '{agent_name}' not found at step {i}")
                return f"Agent '{agent_name}' not found"
            full_output = ""
            async with self._semaphore:
                start = datetime.now()
                async for chunk in self._process_with_plugins(chat, prompt):
                    full_output += chunk
                elapsed = (datetime.now() - start).total_seconds()
                self._task_times[agent_name] = elapsed
                self._checkpoint.save(
                    agent=f"pipeline/step{i}",
                    goal=f"Step {i}: {agent_name}",
                    status="in_progress",
                    progress_pct=int((i + 1) * 100 / len(steps)),
                    context={"step": i, "agent": agent_name, "elapsed_s": round(elapsed, 1)},
                )
            result = full_output
        self._checkpoint.mark_done(f"Pipeline completed: {len(steps)} steps")
        return result

    # --- Delegation protocol ---
    DELEGATE_PATTERN = re.compile(r'\[DELEGATE:\s*(\w+):\s*(.+?)\]', re.DOTALL)

    async def delegate_task(self, from_agent: str, to_agent: str, task: str) -> Optional[str]:
        """Delegate a task from one agent to another.
        Saves delegation marker to checkpoint and routes task to target agent."""
        to_chat = self.get_chat(to_agent)
        if not to_chat:
            self._checkpoint.save(
                agent=from_agent,
                goal=f"DELEGATE to {to_agent}: {task[:100]}",
                status="failed",
                notes=f"Target agent '{to_agent}' not found",
                successors=[to_agent],
            )
            return f"[Error] Agent '{to_agent}' not found"

        # Save delegation marker
        self._checkpoint.save(
            agent=to_agent,
            goal=f"[Delegated from {from_agent}]: {task[:120]}",
            status="in_progress",
            progress_pct=0,
            context={
                "delegated_from": from_agent,
                "original_task": task[:500],
                "timestamp": datetime.now().isoformat(),
            },
            notes=f"Task delegated from {from_agent} to {to_agent}",
            successors=[from_agent],
        )

        # Process the task with target agent
        full_output = ""
        async with self._semaphore:
            async for chunk in self._process_with_plugins(to_chat, task):
                full_output += chunk
            self._save_history(to_agent, to_chat)

        self._checkpoint.mark_done(f"Delegated task from {from_agent} -> {to_agent} completed")
        return full_output

    async def detect_delegations(self, agent_name: str, output: str) -> List[Dict]:
        """Scan output for [DELEGATE:agent:task] markers and return parsed delegations"""
        matches = self.DELEGATE_PATTERN.findall(output)
        delegations = []
        for target_agent, task in matches:
            delegations.append({
                "from": agent_name,
                "to": target_agent.strip().lower(),
                "task": task.strip(),
            })
        return delegations

    # --- Webhook handler ---
    async def webhook(self, data: Dict) -> Dict:
        """API gateway: accepts agent tasks, returns result"""
        agent_name = data.get("agent", "researcher")
        message = data.get("message", "")
        if not message:
            return {"error": "No message provided"}

        # Check cache
        cached = self._cache.get(agent_name, message)
        if cached:
            return {"agent": agent_name, "cached": True, "result": cached}

        # Webhook can use pipeline
        if "pipeline" in data:
            result = await self.pipeline(data["pipeline"])
        else:
            chat = self.get_chat(agent_name)
            if not chat:
                return {"error": f"Unknown agent: {agent_name}"}
            full_output = ""
            async with self._semaphore:
                async for chunk in self._process_with_plugins(chat, message):
                    full_output += chunk
            # Save to cache
            self._cache.set(agent_name, message, full_output)

        return {
            "agent": agent_name,
            "cached": False,
            "result": full_output,
            "status": "ok",
        }

    # --- Status ---
    async def get_status(self) -> Dict:
        import psutil
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory().percent
        except Exception:
            cpu = mem = 0
        avg_time = 0
        if self._task_times:
            avg_time = sum(self._task_times.values()) / len(self._task_times)
        return {
            "active_chats": len(self.chats),
            "queue_size": self._queue.qsize(),
            "concurrent_workers": self._workers,
            "semaphore_available": self._semaphore._value,
            "cpu_percent": cpu,
            "memory_percent": mem,
            "cache_size": self._cache.size,
            "avg_task_time_sec": round(avg_time, 2),
        }

    async def cleanup_idle(self, max_idle_minutes: int = 5):
        now = datetime.now()
        idle_names = []
        for name, chat in self.chats.items():
            if not chat.messages:
                continue
            last_msg = chat.messages[-1]
            try:
                ts = datetime.fromisoformat(last_msg["timestamp"])
                if (now - ts).total_seconds() > max_idle_minutes * 60:
                    idle_names.append(name)
            except Exception:
                continue
        for name in idle_names:
            chat = self.chats.pop(name, None)
            if chat:
                self._save_history(name, chat)
                await chat.close()

    async def background_mode(self):
        """Process queue continuously without UI"""
        while True:
            if not self._queue.empty():
                agent_name, message = await self._queue.get()
                chat = self.get_chat(agent_name)
                if chat:
                    async with self._semaphore:
                        async for _ in self._process_with_plugins(chat, message):
                            pass
                        self._save_history(agent_name, chat)
                self._queue.task_done()
            else:
                await asyncio.sleep(1)

    async def close_all(self):
        self.save_all_histories()
        for chat in self.chats.values():
            try:
                await chat.close()
            except AttributeError:
                pass
        # Stop llama.cpp server if running
        if self._llm:
            try:
                if hasattr(self._llm, '_llama_server') and self._llm._llama_server:
                    await self._llm._llama_server.stop()
            except Exception:
                pass


DEFAULT_AGENTS = {
    "researcher": AgentConfig(
        name="researcher",
        model="tinyllama",
        system_prompt=(
            "You are a research specialist. "
            "Use 'search <query>' to find information online. "
            "Be concise and cite sources. "
            "You can also inspect images (image info/analyze), videos (video info/frame), "
            "and GIFs (gif frames) to extract visual data. "
            "You can create: 'draw <desc>', 'create gif <desc>', 'create video <desc>', "
            "'create pdf <title> with <content>', 'compose <style>', 'draw diagram <type>'."
        ),
    ),
    "engineer": AgentConfig(
        name="engineer",
        model="tinyllama",
        system_prompt=(
            "You are a systems engineer. "
            "Use 'run <command>' to execute shell commands. "
            "Use git clone/status/commit/push for git operations. Be precise and safe. "
            "You can view images (image info/analyze/thumb) and videos (video info/frame/frames). "
            "Generate: 'draw <desc>', 'create gif <desc>', 'create video <desc>', "
            "'create pdf <title> with <content>', 'compose <style>', 'draw diagram <type>', "
            "'create gost <title>' for technical docs."
        ),
    ),
    "analyst": AgentConfig(
        name="analyst",
        model="tinyllama",
        system_prompt=(
            "You are a data analyst. "
            "Combine web search with local analysis. "
            "Use 'search <query>' and 'run <cmd>' as needed. "
            "Analyze images (image info/analyze), videos (video info/frame), "
            "PDFs (pdf all/page/range), and GIFs (gif frames). "
            "Generate: 'draw <desc>', 'create pdf <title> with <content>', "
            "'draw diagram gantt', 'create gost <title>'."
        ),
    ),
    "navigator": AgentConfig(
        name="navigator",
        model="tinyllama",
        system_prompt=(
            "You specialize in web navigation and user-agent handling. "
            "Use 'user agent get/set' to manage browser identity. "
            "You can also capture and analyze images from the web. "
            "Generate: 'draw <desc>', 'create gif <desc>', 'create video <desc>'."
        ),
    ),
    "file_manager": AgentConfig(
        name="file_manager",
        model="tinyllama",
        system_prompt=(
            "You manage files. "
            "Use 'read file <path>', 'write file <path> with <content>', "
            "'list files [path]' to manage files. "
            "View images (image info), videos (video info), PDFs (pdf all/page), "
            "and extract GIF frames (gif frames). "
            "Generate: 'draw <desc>', 'create gif <desc>', 'create pdf <title> with <content>', "
            "'create video <desc>', 'compose <style>', 'draw diagram <type>', 'create gost <title>'."
        ),
    ),
    "devops": AgentConfig(
        name="devops",
        model="tinyllama",
        system_prompt=(
            "You are a DevOps engineer. "
            "Use git clone/push/pull/commit, run <cmd>, "
            "process list/output/kill to manage infrastructure. "
            "You can inspect images (image info), videos (video info), "
            "and read PDFs (pdf all/page). "
            "Generate diagrams: 'draw diagram architecture', "
            "'draw diagram flowchart', 'create gost <title>'."
        ),
    ),
    "coder": AgentConfig(
        name="coder",
        model="tinyllama",
        system_prompt=(
            "You are a senior software engineer. "
            "Write clean, well-structured code. "
            "Plan architecture, create project structure, implement module by module. "
            "Always output complete, runnable code. "
            "You can work with images (image info/analyze), videos (video info/frame), "
            "PDFs (pdf all/page/range), and GIFs (gif frames). "
            "Generate: 'draw <desc>', 'create gif <desc>', 'create video <desc>', "
            "'create pdf <title> with <content>', 'compose <style>', 'draw diagram <type>', "
            "'create gost <title>'."
        ),
    ),
    "doc_agent": AgentConfig(
        name="doc_agent",
        model="tinyllama",
        system_prompt=(
            "You are a document, PDF, image and video specialist. "
            "Commands: read file <path>, pdf all/page/range/info, "
            "summary, search docs, create/edit/list docs, "
            "image info/analyze/thumb, gif frames, video info/frame/frames. "
            "Generation: draw <desc> [WxH], create gif/video/pdf, "
            "compose <style>, draw diagram <type>, create gost <title>."
        ),
    ),
    "agent_maker": AgentConfig(
        name="agent_maker",
        model="tinyllama",
        system_prompt=(
            "You create new AI agents. "
            "Use 'create agent <description> with <tools>' to build a new agent Python module. "
            "Describe what the agent should do. Restart the server after creation to activate. "
            "You can also: draw <desc>, create pdf/gif/video/diagram/uml/compose."
        ),
    ),
    "uml_designer": AgentConfig(
        name="uml_designer",
        model="tinyllama",
        system_prompt=(
            "You design UML diagrams. "
            "Commands: draw uml class/sequence/use case/activity, "
            "draw diagram flowchart/architecture/gantt. "
            "Also: create pdf, create gif, create video, compose music."
        ),
    ),
    "game_dev": AgentConfig(
        name="game_dev",
        model="tinyllama",
        system_prompt=(
            "You create games. "
            "Commands: create game snake/pong/tetris, make game <desc>. "
            "Games saved to generated/ with launcher. "
            "Also: draw <desc>, create gif/video/pdf/diagram, compose music."
        ),
    ),
    "search_agent": AgentConfig(
        name="search_agent",
        model="tinyllama",
        system_prompt=(
            "You are an internet search specialist. "
            "Use 'search <query>' to find information on the web. "
            "Use 'find <query>' as an alternative. "
            "Summarize search results clearly with source citations. "
            "You can also: read file <path>, image info/analyze, video info/frame, pdf all/page. "
            "Generate: draw <desc>, create gif <desc>, create pdf <title> with <content>."
        ),
    ),
    "pr_agent": AgentConfig(
        name="pr_agent",
        model="tinyllama",
        system_prompt=(
            "You are a PR and marketing specialist. "
            "Create promotional content:\n"
            "- draw <desc> [WxH] — generate promotional image\n"
            "- create gif <desc> [N frames] — animated ad GIF\n"
            "- create video <desc> [Ns] — promotional video\n"
            "- create pdf <title> with <content> — press release / brochure PDF\n"
            "- draw diagram gantt — campaign timeline\n"
            "- compose <style> [Ns] — background music\n"
            "- create gost <title> — formal report\n"
            "Also: search <query>, run <cmd>, read file <path>."
        ),
    ),
    "tinyllama": AgentConfig(
        name="tinyllama",
        model="tinyllama",
        system_prompt=(
            "You are TinyLlama — 1.1B parameter model, runs fully offline without internet. "
            "Know English well, can teach English, computers, and chemistry. "
            "Use: search <query>, run <cmd>, read file <path>, draw <desc>, "
            "create gif/video/pdf/diagram, compose music, create gost. "
            "Commands always work without internet."
        ),
    ),
    "coder_agent": AgentConfig(
        name="coder_agent",
        model="tinyllama",
        system_prompt=(
            "You write code for Windows (PowerShell/bat) and Linux (bash). "
            "Output complete runnable scripts. "
            "Commands: run <cmd>, read/write file, git, search, "
            "draw diagram, create pdf/gif/video."
        ),
    ),
    "offline_helper": AgentConfig(
        name="offline_helper",
        model="tinyllama",
        system_prompt=(
            "You are the Offline Helper. "
            "You work WITHOUT internet using only local tools.\n"
            "Commands that always work offline:\n"
            "- run <cmd> — shell commands\n"
            "- read file <path> — read text/PDF/image info\n"
            "- write file <path> with <content> — create/edit files\n"
            "- list files [path]\n"
            "- draw <desc> [WxH] — generate images\n"
            "- create gif <desc> [N frames] — animated GIF\n"
            "- create video <desc> [Ns] — video generation\n"
            "- create pdf <title> with <content> — PDF documents\n"
            "- compose <style> [Ns] — music (WAV)\n"
            "- draw diagram <type> — flowcharts/gantt/architecture\n"
            "- draw uml <type> — UML diagrams\n"
            "- create game snake/pong/tetris\n"
            "- create gost <title> — technical docs\n"
            "- create agent <desc> with <tools> — create new agents\n"
            "You are also a Windows and Linux expert."
        ),
    ),
    "code_dev": AgentConfig(
        name="code_dev",
        model="tinyllama",
        system_prompt=(
            "You are a software engineer. You write Python/JS/batch scripts and run them. "
            "Commands:\n"
            "- write code <desc> — generate code, save to file, and execute (via 'write code <desc>')\n"
            "- write script <name.py> with <code> — save file then 'run python <file>'\n"
            "- create game <type> — snake/pong/arkanoid/tetris (saves to generated/)\n"
            "- run <cmd> — execute shell commands\n"
            "- read file <path>, write file <path> with <content>\n"
            "- draw <desc> [WxH], create pdf/gif/video/diagram/gost\n"
            "Always output complete, runnable code. Use short variable names for TinyLlama context."
        ),
    ),
}


class DocumentTools:
    """Document processing tools for doc_agent"""

    TEXT_EXTS = {
        ".txt", ".md", ".py", ".json", ".csv", ".log",
        ".html", ".xml", ".yaml", ".yml", ".cfg", ".ini",
        ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go", ".rs",
        ".sql", ".sh", ".bat", ".ps1", ".toml", ".css",
    }
    PDF_EXTS = {".pdf"}
    SUPPORTED_EXTS = TEXT_EXTS | PDF_EXTS

    def __init__(self, work_dir: str = None):
        self.work_dir = Path(work_dir or os.getcwd())

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.work_dir / p
        return p

    def _is_supported(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTS

    def _is_text(self, path: Path) -> bool:
        return path.suffix.lower() in self.TEXT_EXTS

    def _is_pdf(self, path: Path) -> bool:
        return path.suffix.lower() in self.PDF_EXTS

    def _read_pdf_text(self, path: Path, page_start: int = 0, page_end: int = None) -> Dict:
        """Extract text from PDF using pymupdf"""
        try:
            import fitz
            doc = fitz.open(str(path))
            total_pages = len(doc)
            if page_end is None:
                page_end = total_pages
            page_start = max(0, page_start)
            page_end = min(total_pages, page_end)

            pages_text = []
            for i in range(page_start, page_end):
                page = doc[i]
                text = page.get_text("text")
                pages_text.append({"page": i + 1, "text": text})

            doc.close()
            return {
                "path": str(path),
                "total_pages": total_pages,
                "pages_read": f"{page_start + 1}-{page_end}",
                "pages": pages_text,
            }
        except Exception as e:
            return {"error": f"PDF read error: {e}"}

    def _pdf_metadata(self, path: Path) -> Dict:
        """Get PDF metadata"""
        try:
            import fitz
            doc = fitz.open(str(path))
            meta = doc.metadata or {}
            info = {
                "path": str(path),
                "total_pages": len(doc),
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "subject": meta.get("subject", ""),
                "creator": meta.get("creator", ""),
                "size": path.stat().st_size,
            }
            doc.close()
            return info
        except Exception as e:
            return {"error": str(e)}

    async def read_doc(self, path: str, offset: int = 0, limit: int = 500) -> Dict:
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        if not self._is_supported(p):
            return {"error": f"Unsupported file type: {p.suffix}"}

        # PDF handling
        if self._is_pdf(p):
            meta = self._pdf_metadata(p)
            if "error" in meta:
                return meta
            # Read first N pages based on limit (approx 50 lines per page)
            pages_to_read = max(1, limit // 50)
            result = self._read_pdf_text(p, page_start=0, page_end=pages_to_read)
            if "error" in result:
                return result
            text = "\n\n".join(
                f"--- Page {pg['page']} ---\n{pg['text']}" for pg in result["pages"]
            )
            return {
                "path": str(path),
                "type": "pdf",
                "total_pages": meta["total_pages"],
                "showing_pages": pages_to_read,
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "content": text[:5000],
                "size": meta["size"],
            }

        # Text file handling
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            total_lines = len(lines)
            selected = lines[offset : offset + limit]
            return {
                "path": str(path),
                "type": "text",
                "total_lines": total_lines,
                "offset": offset,
                "showing": len(selected),
                "content": "\n".join(selected),
                "size": p.stat().st_size,
            }
        except Exception as e:
            return {"error": str(e)}

    async def read_pdf_page(self, path: str, page: int) -> Dict:
        """Read a specific page from PDF"""
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        if not self._is_pdf(p):
            return {"error": f"Not a PDF: {path}"}
        result = self._read_pdf_text(p, page_start=page - 1, page_end=page)
        if "error" in result:
            return result
        if result["pages"]:
            return {
                "path": str(path),
                "page": page,
                "total_pages": result["total_pages"],
                "text": result["pages"][0]["text"],
            }
        return {"error": f"Page {page} not found"}

    async def read_pdf_range(self, path: str, start: int, end: int) -> Dict:
        """Read page range from PDF"""
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        if not self._is_pdf(p):
            return {"error": f"Not a PDF: {path}"}
        result = self._read_pdf_text(p, page_start=start - 1, page_end=end)
        if "error" in result:
            return result
        text = "\n\n".join(
            f"--- Page {pg['page']} ---\n{pg['text']}" for pg in result["pages"]
        )
        return {
            "path": str(path),
            "pages": f"{start}-{end}",
            "total_pages": result["total_pages"],
            "content": text[:5000],
        }

    async def create_doc(self, path: str, content: str) -> Dict:
        p = self._resolve(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {
                "path": str(path),
                "lines": len(content.split("\n")),
                "size": len(content),
                "status": "created",
            }
        except Exception as e:
            return {"error": str(e)}

    async def edit_doc(self, path: str, find: str, replace: str) -> Dict:
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            count = content.count(find)
            if count == 0:
                return {"error": f"Text not found: '{find[:50]}'"}
            new_content = content.replace(find, replace)
            p.write_text(new_content, encoding="utf-8")
            return {
                "path": str(path),
                "replacements": count,
                "status": "edited",
            }
        except Exception as e:
            return {"error": str(e)}

    async def search_docs(self, query: str, path: str = ".", max_results: int = 20) -> Dict:
        search_dir = self._resolve(path)
        if not search_dir.is_dir():
            return {"error": f"Not a directory: {path}"}
        results = []
        query_lower = query.lower()
        try:
            for f in search_dir.rglob("*"):
                if not f.is_file() or not self._is_supported(f):
                    continue
                if f.stat().st_size > 2_000_000:
                    continue
                try:
                    # Text files
                    if self._is_text(f):
                        content = f.read_text(encoding="utf-8", errors="replace")
                        for i, line in enumerate(content.split("\n")):
                            if query_lower in line.lower():
                                results.append({
                                    "file": str(f.relative_to(search_dir)),
                                    "line": i + 1,
                                    "text": line.strip()[:200],
                                })
                                if len(results) >= max_results:
                                    return {"query": query, "results": results, "total": len(results)}
                    # PDF files
                    elif self._is_pdf(f):
                        pdf_result = self._read_pdf_text(f, page_start=0, page_end=50)
                        if "pages" in pdf_result:
                            for pg in pdf_result["pages"]:
                                for i, line in enumerate(pg["text"].split("\n")):
                                    if query_lower in line.lower():
                                        results.append({
                                            "file": str(f.relative_to(search_dir)),
                                            "line": pg["page"],
                                            "page": pg["page"],
                                            "text": line.strip()[:200],
                                        })
                                        if len(results) >= max_results:
                                            return {"query": query, "results": results, "total": len(results)}
                except Exception:
                    continue
            return {"query": query, "results": results, "total": len(results)}
        except Exception as e:
            return {"error": str(e)}

    async def summary(self, path: str) -> Dict:
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}

        # PDF summary
        if self._is_pdf(p):
            meta = self._pdf_metadata(p)
            if "error" in meta:
                return meta
            # Read first few pages for word analysis
            pdf_data = self._read_pdf_text(p, page_start=0, page_end=min(10, meta["total_pages"]))
            all_text = "\n".join(pg["text"] for pg in pdf_data.get("pages", []))
            words = all_text.split()
            word_freq = {}
            for w in words:
                wl = w.lower().strip(".,;:!?\"'()[]{}")
                if len(wl) > 2:
                    word_freq[wl] = word_freq.get(wl, 0) + 1
            top_words = sorted(word_freq.items(), key=lambda x: -x[1])[:10]
            return {
                "path": str(path),
                "type": "pdf",
                "total_pages": meta["total_pages"],
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "total_words": len(words),
                "total_chars": len(all_text),
                "size": meta["size"],
                "top_words": top_words,
                "preview": all_text[:500],
            }

        # Text summary
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            words = content.split()
            non_empty = [l for l in lines if l.strip()]

            word_freq = {}
            for w in words:
                wl = w.lower().strip(".,;:!?\"'()[]{}")
                if len(wl) > 2:
                    word_freq[wl] = word_freq.get(wl, 0) + 1
            top_words = sorted(word_freq.items(), key=lambda x: -x[1])[:10]

            return {
                "path": str(path),
                "type": "text",
                "total_lines": len(lines),
                "non_empty_lines": len(non_empty),
                "total_words": len(words),
                "total_chars": len(content),
                "size": p.stat().st_size,
                "extension": p.suffix,
                "top_words": top_words,
                "preview": "\n".join(lines[:20]),
            }
        except Exception as e:
            return {"error": str(e)}

    async def list_docs(self, path: str = ".") -> Dict:
        d = self._resolve(path)
        if not d.is_dir():
            return {"error": f"Not a directory: {path}"}
        items = []
        try:
            for item in sorted(d.iterdir()):
                if item.is_dir():
                    items.append({"name": item.name, "type": "dir"})
                elif self._is_supported(item):
                    items.append({
                        "name": item.name,
                        "type": "file",
                        "size": item.stat().st_size,
                        "lines": None,
                    })
            return {"path": str(path), "items": items[:50]}
        except Exception as e:
            return {"error": str(e)}


class ImageTools:
    """Image analysis tools"""

    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".ico", ".svg"}

    def __init__(self, work_dir: str = None):
        self.work_dir = Path(work_dir or os.getcwd())

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.work_dir / p
        return p

    def _is_image(self, path: Path) -> bool:
        return path.suffix.lower() in self.IMAGE_EXTS

    async def image_info(self, path: str) -> Dict:
        from PIL import Image
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        try:
            img = Image.open(str(p))
            info = {
                "path": str(path),
                "format": img.format,
                "mode": img.mode,
                "width": img.width,
                "height": img.height,
                "size": p.stat().st_size,
                "has_animated": hasattr(img, "n_frames") and img.n_frames > 1,
            }
            if hasattr(img, "n_frames"):
                info["frames"] = img.n_frames
            if img.format == "GIF" and hasattr(img, "info"):
                info["duration"] = img.info.get("duration", 0)
                info["loop"] = img.info.get("loop", 0)
            img.close()
            return info
        except Exception as e:
            return {"error": str(e)}

    async def image_thumbnail(self, path: str, max_size: int = 256) -> Dict:
        """Generate base64 thumbnail for web display"""
        from PIL import Image
        import base64
        from io import BytesIO
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        try:
            img = Image.open(str(p))
            img.thumbnail((max_size, max_size))
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (13, 17, 23))
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=80)
            b64 = base64.b64encode(buf.getvalue()).decode()
            img.close()
            return {
                "path": str(path),
                "thumbnail": f"data:image/jpeg;base64,{b64}",
                "width": img.width if img else max_size,
                "height": img.height if img else max_size,
            }
        except Exception as e:
            return {"error": str(e)}

    async def image_analyze(self, path: str) -> Dict:
        """Analyze image colors, dominant, histogram"""
        from PIL import Image
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        try:
            img = Image.open(str(p))
            original = img.copy()
            info = {
                "path": str(path),
                "format": img.format,
                "mode": img.mode,
                "width": img.width,
                "height": img.height,
                "size": p.stat().st_size,
            }

            # Convert to RGB for analysis
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (13, 17, 23))
                bg.paste(img, mask=img.split()[3])
                rgb = bg
            elif img.mode != "RGB":
                rgb = img.convert("RGB")
            else:
                rgb = img.copy()

            # Resize for color analysis
            small = rgb.copy()
            small.thumbnail((100, 100))
            pixels = list(small.getdata())

            # Count colors (quantize)
            color_count = {}
            for p_rgb in pixels:
                # Round to nearest 16
                q = tuple((c // 16) * 16 for c in p_rgb)
                color_count[q] = color_count.get(q, 0) + 1
            top_colors = sorted(color_count.items(), key=lambda x: -x[1])[:5]
            info["top_colors"] = [
                {"rgb": c, "hex": "#{:02x}{:02x}{:02x}".format(*c), "count": n}
                for c, n in top_colors
            ]

            # Brightness
            gray = rgb.convert("L")
            hist = gray.histogram()
            total = sum(hist)
            brightness = sum(i * v for i, v in enumerate(hist)) / total / 255
            info["brightness"] = round(brightness, 3)
            info["brightness_label"] = (
                "dark" if brightness < 0.33
                else "medium" if brightness < 0.66
                else "bright"
            )

            # Aspect ratio
            info["aspect_ratio"] = round(img.width / img.height, 2) if img.height > 0 else 0

            img.close()
            rgb.close()
            small.close()
            return info
        except Exception as e:
            return {"error": str(e)}

    async def gif_extract_frames(self, path: str, max_frames: int = 20) -> Dict:
        """Extract frames from GIF as base64 thumbnails"""
        from PIL import Image
        import base64
        from io import BytesIO
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        try:
            img = Image.open(str(p))
            if not hasattr(img, "n_frames") or img.n_frames <= 1:
                return {"error": "Not an animated GIF"}
            frames = []
            n = min(img.n_frames, max_frames)
            for i in range(n):
                img.seek(i)
                frame = img.copy()
                frame.thumbnail((128, 128))
                if frame.mode == "RGBA":
                    bg = Image.new("RGB", frame.size, (13, 17, 23))
                    bg.paste(frame, mask=frame.split()[3])
                    frame = bg
                elif frame.mode != "RGB":
                    frame = frame.convert("RGB")
                buf = BytesIO()
                frame.save(buf, format="JPEG", quality=70)
                b64 = base64.b64encode(buf.getvalue()).decode()
                frames.append({
                    "index": i,
                    "thumbnail": f"data:image/jpeg;base64,{b64}",
                })
                frame.close()
            img.close()
            return {
                "path": str(path),
                "total_frames": img.n_frames if hasattr(img, "n_frames") else 0,
                "extracted": len(frames),
                "frames": frames,
            }
        except Exception as e:
            return {"error": str(e)}

    async def list_images(self, path: str = ".") -> Dict:
        d = self._resolve(path)
        if not d.is_dir():
            return {"error": f"Not a directory: {path}"}
        items = []
        try:
            for item in sorted(d.iterdir()):
                if item.is_file() and self._is_image(item):
                    items.append({
                        "name": item.name,
                        "size": item.stat().st_size,
                        "ext": item.suffix.lower(),
                    })
            return {"path": str(path), "images": items[:50], "total": len(items)}
        except Exception as e:
            return {"error": str(e)}


class VideoTools:
    """Video and GIF frame extraction using OpenCV"""

    VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".3gp"}
    GIF_EXTS = {".gif"}

    def __init__(self, work_dir: str = None):
        self.work_dir = Path(work_dir or os.getcwd())

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.work_dir / p
        return p

    def _is_video(self, path: Path) -> bool:
        return path.suffix.lower() in self.VIDEO_EXTS

    def _is_gif(self, path: Path) -> bool:
        return path.suffix.lower() in self.GIF_EXTS

    def _is_supported(self, path: Path) -> bool:
        return self._is_video(path) or self._is_gif(path)

    async def video_info(self, path: str) -> Dict:
        import cv2
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        try:
            cap = cv2.VideoCapture(str(p))
            if not cap.isOpened():
                return {"error": f"Cannot open video: {path}"}
            fps = cap.get(cv2.CAP_PROP_FPS)
            frames_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            codec = int(cap.get(cv2.CAP_PROP_FOURCC))
            codec_str = "".join([chr((codec >> 8 * i) & 0xFF) for i in range(4)])
            duration = frames_count / fps if fps > 0 else 0
            cap.release()
            return {
                "path": str(path),
                "format": p.suffix.lower(),
                "width": width,
                "height": height,
                "fps": round(fps, 2),
                "total_frames": frames_count,
                "codec": codec_str,
                "duration_sec": round(duration, 2),
                "duration_fmt": f"{int(duration//60)}:{int(duration%60):02d}",
                "size": p.stat().st_size,
            }
        except Exception as e:
            return {"error": str(e)}

    async def video_frame(self, path: str, time_sec: float = 0) -> Dict:
        """Extract a single frame as base64 thumbnail"""
        import cv2
        import base64
        from io import BytesIO
        from PIL import Image
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        try:
            cap = cv2.VideoCapture(str(p))
            if not cap.isOpened():
                return {"error": f"Cannot open: {path}"}
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_num = int(time_sec * fps) if fps > 0 else 0
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            cap.release()
            if not ret:
                return {"error": f"Cannot read frame at {time_sec}s"}
            # Resize for thumbnail
            h, w = frame.shape[:2]
            max_dim = 256
            if max(h, w) > max_dim:
                scale = max_dim / max(h, w)
                frame = cv2.resize(frame, None, fx=scale, fy=scale)
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode()
            img.close()
            return {
                "path": str(path),
                "time_sec": time_sec,
                "frame_num": frame_num,
                "thumbnail": f"data:image/jpeg;base64,{b64}",
                "width": w,
                "height": h,
            }
        except Exception as e:
            return {"error": str(e)}

    async def video_frames(self, path: str, count: int = 5) -> Dict:
        """Extract multiple evenly-spaced frames"""
        import cv2
        import base64
        from io import BytesIO
        from PIL import Image
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        try:
            cap = cv2.VideoCapture(str(p))
            if not cap.isOpened():
                return {"error": f"Cannot open: {path}"}
            fps = cap.get(cv2.CAP_PROP_FPS)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total / fps if fps > 0 else 0
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            count = min(count, 20)
            interval = total / count if count > 0 else 1
            frames = []
            for i in range(count):
                frame_num = int(i * interval)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                if not ret:
                    continue
                # Resize
                max_dim = 192
                fh, fw = frame.shape[:2]
                if max(fh, fw) > max_dim:
                    scale = max_dim / max(fh, fw)
                    frame = cv2.resize(frame, None, fx=scale, fy=scale)
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=70)
                b64 = base64.b64encode(buf.getvalue()).decode()
                time_sec = frame_num / fps if fps > 0 else 0
                frames.append({
                    "index": i,
                    "time_sec": round(time_sec, 2),
                    "time_fmt": f"{int(time_sec//60)}:{int(time_sec%60):02d}",
                    "thumbnail": f"data:image/jpeg;base64,{b64}",
                })
                img.close()
            cap.release()
            return {
                "path": str(path),
                "width": w,
                "height": h,
                "fps": round(fps, 2),
                "duration_sec": round(duration, 2),
                "extracted": len(frames),
                "frames": frames,
            }
        except Exception as e:
            return {"error": str(e)}

    async def gif_info(self, path: str) -> Dict:
        """Get detailed GIF info"""
        from PIL import Image
        p = self._resolve(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        try:
            img = Image.open(str(p))
            info = {
                "path": str(path),
                "format": "GIF",
                "width": img.width,
                "height": img.height,
                "mode": img.mode,
                "size": p.stat().st_size,
            }
            if hasattr(img, "n_frames"):
                info["frames"] = img.n_frames
            if hasattr(img, "info"):
                info["duration_ms"] = img.info.get("duration", 0)
                info["loop"] = img.info.get("loop", 0)
                if info.get("duration_ms") and info.get("frames"):
                    total_ms = info["duration_ms"] * info["frames"]
                    info["total_duration_sec"] = round(total_ms / 1000, 2)
            img.close()
            return info
        except Exception as e:
            return {"error": str(e)}


# --- OpenAI-compatible /v1/chat/completions (for opencode.ai) ---

_TOOL_CALL_RE = re.compile(
    r'<tool_call>\s*<name>\s*(\w+)\s*</name>\s*<arguments>\s*(\{.*?\})\s*</arguments>\s*</tool_call>',
    re.DOTALL
)

async def handle_v1_chat(request):
    """OpenAI-compatible chat completions endpoint wrapping TinyLlama."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    messages = data.get("messages", [])
    if not messages:
        return web.json_response({"error": "no messages"}, status=400)

    stream = data.get("stream", False)
    tools = data.get("tools", [])
    orch = request.app["orchestrator"]
    llm = orch._llm

    if not llm:
        return web.json_response({"error": "no LLM backend"}, status=503)

    # Build structured prompt from messages
    prompt_parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            prompt_parts.append(f"System: {content}")
        elif role == "user":
            prompt_parts.append(f"User: {content}")
        elif role == "assistant":
            prompt_parts.append(f"Assistant: {content}")

    # If tools are provided, inject them as instructions
    if tools:
        tool_desc = []
        for t in tools:
            if t.get("type") == "function":
                fn = t.get("function", {})
                name = fn.get("name", "unknown")
                desc = fn.get("description", "")
                params = fn.get("parameters", {})
                props = params.get("properties", {})
                args_desc = "; ".join(
                    f"{k}: {v.get('description', v.get('type', '?'))}" for k, v in props.items()
                )
                tool_desc.append(f"- {name}: {desc} | args: {args_desc}")
        if tool_desc:
            tool_block = (
                "Available tools — you MUST use them when asked to modify files:\n"
                + "\n".join(tool_desc)
                + "\n\n"
                "To call a tool, output XML like this:\n"
                "<tool_call>\n<name>tool_name</name>\n<arguments>{json args}</arguments>\n</tool_call>\n"
                "Then the tool will be executed automatically."
            )
            # Inject after last system message or as new system message
            prompt_parts.insert(0, f"System: {tool_block}")

    prompt_parts.append("Assistant:")
    prompt = "\n\n".join(prompt_parts)

    max_tokens = min(data.get("max_tokens", 2048), 2048)  # TinyLlama max = 2048
    temperature = data.get("temperature", 0.7)
    try:
        text = llm.generate(prompt, max_tokens=max_tokens, temperature=temperature)
        text = text.strip().lstrip("Assistant:").strip()
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

    # Check for tool calls in output
    tool_calls = []
    for m in _TOOL_CALL_RE.finditer(text):
        name = m.group(1)
        args_str = m.group(2)
        try:
            args = json.loads(args_str)
        except json.JSONDecodeError:
            args = {"raw": args_str}
        tool_calls.append({
            "id": f"call_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        })
        # Remove tool call XML from visible text
        text = text[:m.start()] + text[m.end():]

    text = text.strip()
    finish_reason = "tool_calls" if tool_calls else "stop"

    if stream:
        resp = web.StreamResponse(
            status=200,
            headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
        )
        await resp.prepare(request)
        if tool_calls:
            # Stream tool call as a single chunk
            delta = {"role": "assistant", "content": None, "tool_calls": tool_calls}
            sse = f"data: {json.dumps({'choices':[{'delta':delta,'index':0,'finish_reason':'tool_calls'}]})}\n\n"
            await resp.write(sse.encode("utf-8"))
        else:
            for chunk in [text[i:i+5] for i in range(0, len(text), 5)]:
                delta = {"content": chunk}
                await resp.write(f"data: {json.dumps({'choices':[{'delta':delta,'index':0}]})}\n\n".encode("utf-8"))
                await asyncio.sleep(0.01)
        await resp.write(b"data: [DONE]\n\n")
        return resp

    msg = {"role": "assistant", "content": text if text else None}
    if tool_calls:
        msg["tool_calls"] = tool_calls

    return web.json_response({
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": msg, "finish_reason": finish_reason}],
        "model": "tinyllama-local",
    })

# --- Web handlers ---

async def handle_agents(request):
    orch = request.app["orchestrator"]
    agents = {}
    for name, cfg in DEFAULT_AGENTS.items():
        agents[name] = {
            "model": cfg.model,
            "description": cfg.system_prompt[:100],
        }
    return web.json_response({"agents": agents, "active": list(orch.chats.keys())})


async def handle_chat(request):
    data = await request.json()
    agent_name = data.get("agent", "researcher")
    message = data.get("message", "")

    orch = request.app["orchestrator"]
    chat = orch.get_chat(agent_name)
    if not chat:
        if agent_name in DEFAULT_AGENTS:
            chat = orch.create_chat(agent_name, DEFAULT_AGENTS[agent_name])
        else:
            return web.json_response({"error": f"Unknown agent: {agent_name}"}, status=400)

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "application/x-ndjson",
            "Cache-Control": "no-cache",
        },
    )
    await resp.prepare(request)

    try:
        # First round: process with initial agent
        current_agent = agent_name
        current_chat = chat
        current_message = message
        max_delegations = 5  # prevent infinite delegation loops

        for delegation_round in range(max_delegations):
            full_output = ""
            async for chunk in orch._process_with_plugins(current_chat, current_message):
                full_output += chunk
                await resp.write(chunk.encode("utf-8"))

            # Check for delegation markers
            delegations = await orch.detect_delegations(current_agent, full_output)
            if not delegations:
                break  # no delegation, done

            delegation = delegations[0]
            target = delegation["to"]
            task = delegation["task"]

            # Save delegation to checkpoint
            orch._checkpoint.save(
                agent=target,
                goal=f"[Delegated from {current_agent}]: {task[:120]}",
                status="in_progress",
                context={"delegated_from": current_agent, "original_task": task[:500]},
                notes=f"Auto-routed delegation: {current_agent} -> {target}",
            )

            await resp.write((json.dumps({
                "delegation": {"from": current_agent, "to": target, "task": task[:200]}
            }) + "\n").encode("utf-8"))

            # Route to target agent
            target_chat = orch.get_chat(target)
            if not target_chat and target in DEFAULT_AGENTS:
                target_chat = orch.create_chat(target, DEFAULT_AGENTS[target])

            if not target_chat:
                await resp.write((json.dumps({"error": f"Cannot delegate to '{target}': not found"}) + "\n").encode("utf-8"))
                break

            current_agent = target
            current_chat = target_chat
            current_message = f"[Continuation from {delegation['from']}]: {task}"

        orch._checkpoint.mark_done(f"Chat: {agent_name} -> ... -> {current_agent}")

    except Exception as e:
        orch._checkpoint.mark_failed(f"Chat error: {e}")
        await resp.write((json.dumps({"error": str(e)}) + "\n").encode("utf-8"))
    finally:
        await resp.write_eof()

    return resp


async def handle_history(request):
    agent_name = request.query.get("agent", "researcher")
    orch = request.app["orchestrator"]
    chat = orch.get_chat(agent_name)
    if not chat:
        return web.json_response({"history": []})
    return web.json_response({"history": chat.get_history()})


async def handle_new_agent(request):
    data = await request.json()
    name = data.get("name", "").strip()
    model = data.get("model", "tinyllama")
    prompt = data.get("system_prompt", "")
    if not name or name in DEFAULT_AGENTS:
        return web.json_response({"error": "Invalid or duplicate name"}, status=400)
    orch = request.app["orchestrator"]
    config = AgentConfig(name=name, model=model, system_prompt=prompt)
    orch.create_chat(name, config)
    DEFAULT_AGENTS[name] = config
    return web.json_response({"status": "created", "name": name})


async def handle_llm_status(request):
    """GET /api/llm/status — current LLM backend info"""
    orch = request.app["orchestrator"]
    llm = orch._llm
    if llm is None:
        return web.json_response({"backend": "none", "status": "unavailable"})
    return web.json_response({
        "backend": llm.backend_type.value,
        "model": llm.model_name or "default",
        "has_api_key": bool(llm.api_key),
        "status": "active",
    })


async def handle_llm_switch(request):
    """POST /api/llm/switch — switch LLM backend at runtime

    Body: {"backend": "gpt4all|tinyllama|openai|claude|gemini", "api_key": "...", "model": "..."}
    """
    data = await request.json()
    backend = data.get("backend", "gpt4all").strip().lower()
    api_key = data.get("api_key", os.environ.get("OPENAI_API_KEY", ""))
    model = data.get("model", "")

    orch = request.app["orchestrator"]
    try:
        new_llm = LLMBackend(backend, api_key=api_key, model_name=model)
        # Quick test
        test_prompt = "Say OK"
        result = new_llm.generate(test_prompt, max_tokens=5)
        orch._llm = new_llm
        # Re-create all chats to use new backend
        for name, chat in list(orch.chats.items()):
            chat.llm = new_llm
        return web.json_response({
            "status": "switched",
            "backend": backend,
            "test": result,
            "note": "All agents updated to new backend. API key is kept in memory only.",
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def handle_guest_import(request):
    """POST /api/guest-import — import an agent from another orchestrator"""
    data = await request.json()
    url = data.get("url", "").strip()
    agent_name = data.get("agent", "").strip()
    if not url or not agent_name:
        return web.json_response({"error": "url and agent required"}, status=400)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as sess:
            async with sess.get(url) as resp:
                remote = await resp.json()
        if agent_name not in remote.get("agents", {}):
            return web.json_response({"error": f"Agent '{agent_name}' not found at remote"}, status=404)
        cfg = remote["agents"][agent_name]
        local_name = f"guest_{agent_name}"
        config = AgentConfig(
            name=local_name,
            model=cfg.get("model", "tinyllama"),
            system_prompt=cfg.get("system_prompt", cfg.get("description", "")),
            role=cfg.get("role", f"imported from {url}"),
        )
        orch = request.app["orchestrator"]
        orch.create_chat(local_name, config)
        DEFAULT_AGENTS[local_name] = config
        return web.json_response({"status": "imported", "local_name": local_name, "source": url})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_agent_role(request):
    """POST /api/agent-role — set custom role/profile for an agent"""
    data = await request.json()
    agent_name = data.get("agent", "").strip()
    role = data.get("role", "").strip()
    if not agent_name or agent_name not in DEFAULT_AGENTS:
        return web.json_response({"error": "Unknown agent"}, status=404)
    cfg = DEFAULT_AGENTS[agent_name]
    cfg.role = role
    orch = request.app["orchestrator"]
    # Re-create chat with updated config
    orch.chats.pop(agent_name, None)
    orch.create_chat(agent_name, cfg)
    return web.json_response({"status": "role_updated", "agent": agent_name, "role": role})


async def handle_consilium(request):
    """POST /api/consilium — multi-agent round-table discussion with PDF protocol"""
    data = await request.json()
    topic = data.get("topic", "").strip()
    agent_names = data.get("agents", [])
    context = data.get("context", "")
    if not topic or len(agent_names) < 2:
        return web.json_response({"error": "topic and at least 2 agents required"}, status=400)
    orch = request.app["orchestrator"]
    opinions = {}
    full_history = ""
    norm_names = []
    for name in agent_names:
        # match by prefix if full name not found
        match = None
        if name in DEFAULT_AGENTS:
            match = name
        else:
            for k in DEFAULT_AGENTS:
                if k.startswith(name.lower()) or name.lower().startswith(k):
                    match = k
                    break
        norm_names.append(match or name)
    agent_names = norm_names

    async def get_opinion(name: str) -> Tuple[str, str]:
        chat = orch.get_chat(name)
        if not chat:
            if name in DEFAULT_AGENTS:
                chat = orch.create_chat(name, DEFAULT_AGENTS[name])
            else:
                return name, f"Agent '{name}' not found"
        # Use fallback response directly (avoids up to 2 min LLM wait per agent)
        role = DEFAULT_AGENTS.get(name, chat.config).role or name
        try:
            async for chunk in chat.process(prompt):
                pass
            opinion = chat.messages[-1]["content"][:2000] if chat.messages else "No opinion"
        except Exception as e:
            opinion = f"Fallback ({name}, {role}): opinion based on context. Context: {context[:200]}"
        return name, opinion

    # Run all agents in parallel
    tasks = [get_opinion(name) for name in agent_names]
    for future in asyncio.as_completed(tasks):
        name, opinion = await future
        opinions[name] = opinion
        full_history += f"\n--- {name} ---\n{opinion}\n"

    # Generate PDF protocol
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = Path.cwd() / "generated" / f"consilium_{ts}.pdf"
    pdf_path.parent.mkdir(exist_ok=True)
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Courier", size=10)
    pdf.multi_cell(0, 5, f"PROTOCOL OF CONSILIUM\nTopic: {topic}\nDate: {datetime.now().isoformat()}\nParticipants: {', '.join(agent_names)}\n", align="C")
    pdf.ln(5)
    for name, opinion in opinions.items():
        pdf.set_font("Courier", "B", 10)
        pdf.cell(0, 5, f"--- {name} ---", ln=True)
        pdf.set_font("Courier", size=9)
        for line in opinion.split("\n"):
            pdf.multi_cell(0, 4, line[:120])
        pdf.ln(3)
    pdf.output(str(pdf_path))

    return web.json_response({
        "status": "completed",
        "topic": topic,
        "participants": agent_names,
        "opinions": opinions,
        "protocol": str(pdf_path),
    })


async def handle_cleanup(request):
    minutes = int(request.query.get("minutes", 5))
    orch = request.app["orchestrator"]
    before = len(orch.chats)
    await orch.cleanup_idle(max_idle_minutes=minutes)
    return web.json_response({"cleaned": before - len(orch.chats), "remaining": len(orch.chats)})


async def handle_status(request):
    orch = request.app["orchestrator"]
    status = await orch.get_status()
    return web.json_response(status)


async def handle_ui(request):
    return web.FileResponse(Path(__file__).parent / "static" / "dashboard.html")


async def handle_webhook(request):
    data = await request.json()
    orch = request.app["orchestrator"]
    result = await orch.webhook(data)
    return web.json_response(result)


async def handle_pipeline(request):
    data = await request.json()
    steps = data.get("steps", [])
    if not steps:
        return web.json_response({"error": "No pipeline steps"}, status=400)
    orch = request.app["orchestrator"]
    result = await orch.pipeline(steps)
    return web.json_response({"pipeline": steps, "result": result[:5000]})


async def handle_cache(request):
    orch = request.app["orchestrator"]
    return web.json_response({"cache_size": orch._cache.size})


async def handle_night_mode(request):
    """GET /api/night-mode — get current night mode settings"""
    orch = request.app["orchestrator"]
    return web.json_response(orch.get_night_mode())


async def handle_night_mode_set(request):
    """POST /api/night-mode — update night mode settings"""
    orch = request.app["orchestrator"]
    data = await request.json()
    orch.set_night_mode(data)
    return web.json_response({"status": "ok", **orch.get_night_mode()})


async def handle_history_save(request):
    orch = request.app["orchestrator"]
    orch.save_all_histories()
    return web.json_response({"saved": True})


async def handle_history_search(request):
    """GET /api/history/search?q=<query>&agent=<name>"""
    orch = request.app["orchestrator"]
    query = request.query.get("q", "")
    agent = request.query.get("agent", None)
    if not query:
        return web.json_response({"error": "Missing 'q' parameter"}, status=400)
    results = await orch.search_history(query, agent)
    return web.json_response({"query": query, "agent": agent or "all", "count": len(results), "results": results})


async def handle_history_export(request):
    """GET /api/history/export?agent=<name>&format=json|csv|md"""
    orch = request.app["orchestrator"]
    agent = request.query.get("agent", None)
    fmt = request.query.get("format", "json")
    if fmt not in ("json", "csv", "md"):
        return web.json_response({"error": "Invalid format. Use json, csv, or md"}, status=400)
    content = await orch.export_history(agent, fmt)
    content_type = {
        "json": "application/json",
        "csv": "text/csv",
        "md": "text/markdown",
    }[fmt]
    filename = f"history_{agent or 'all'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}"
    return web.Response(
        body=content,
        content_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def handle_history_reset(request):
    """POST /api/history/reset?agent=<name> — reset history for one or all agents"""
    orch = request.app["orchestrator"]
    data = await request.json()
    agent = data.get("agent", None)
    count = await orch.reset_history(agent)
    return web.json_response({"reset": count, "agent": agent or "all"})


async def handle_plugins_list(request):
    """GET /api/plugins — list all loaded plugins"""
    orch = request.app["orchestrator"]
    if not orch._plugin_mgr:
        return web.json_response({"plugins": [], "enabled": False})
    return web.json_response({
        "plugins": orch._plugin_mgr.list_plugins(),
        "count": orch._plugin_mgr.total_plugins(),
        "enabled": True,
    })


async def handle_plugin_reload(request):
    """POST /api/plugin/reload — reload a specific plugin (or all if no name)"""
    orch = request.app["orchestrator"]
    if not orch._plugin_mgr:
        return web.json_response({"error": "Plugin system not available"}, status=503)
    data = {}
    if request.body_exists:
        try:
            data = await request.json()
        except Exception:
            pass
    name = data.get("name", "")
    if name:
        ok = orch._plugin_mgr.reload(name)
        return web.json_response({"reloaded": name, "success": ok, "error": orch._plugin_mgr.get_plugin(name) is None})
    count = orch._plugin_mgr.reload_all()
    return web.json_response({"reloaded_all": True, "count": count})


async def handle_plugin_upload(request):
    """POST /api/plugin/upload — upload a new plugin .py file"""
    orch = request.app["orchestrator"]
    if not orch._plugin_mgr:
        return web.json_response({"error": "Plugin system not available"}, status=503)
    reader = await request.multipart()
    field = await reader.next()
    if not field or not field.filename:
        return web.json_response({"error": "No file uploaded"}, status=400)
    filename = field.filename
    if not filename.endswith(".py"):
        return web.json_response({"error": "Only .py files allowed"}, status=400)
    content = await field.read()
    dest = orch._plugin_mgr.plugins_dir / filename
    dest.write_bytes(content)
    ok = orch._plugin_mgr.load(filename[:-3])
    return web.json_response({"uploaded": filename, "loaded": ok})


async def handle_checkpoint(request):
    """GET /api/checkpoint — view current checkpoint status"""
    orch = request.app["orchestrator"]
    cp = orch._checkpoint
    data = cp.load()
    orphaned = cp.is_orphaned()
    sos = cp.check_sos()
    return web.json_response({
        "exists": data is not None,
        "orphaned": orphaned,
        "sos": sos is not None,
        "sos_data": sos,
        "checkpoint": data,
    })


async def handle_checkpoint_adopt(request):
    """POST /api/checkpoint/adopt — adopt orphaned checkpoint"""
    orch = request.app["orchestrator"]
    cp = orch._checkpoint
    if not cp.is_orphaned():
        return web.json_response({"error": "No orphaned checkpoint to adopt"}, status=404)
    data = cp.adopt_orphan()
    cp.save(
        agent=data["agent"],
        goal=data.get("goal", ""),
        status="in_progress",
        progress_pct=data.get("progress_pct", 0),
        task_plan=data.get("task_plan", []),
        context=data.get("context", {}),
        notes=data.get("notes", "") + "\n[Adopted via API]",
        successors=data.get("successors_available", []),
    )
    return web.json_response({"adopted": True, "checkpoint": data})


async def handle_checkpoint_done(request):
    """POST /api/checkpoint/done — mark current checkpoint as done"""
    orch = request.app["orchestrator"]
    data = await request.json()
    orch._checkpoint.mark_done(data.get("result", ""))
    return web.json_response({"status": "done"})


async def handle_checkpoint_fail(request):
    """POST /api/checkpoint/fail — mark current checkpoint as failed"""
    orch = request.app["orchestrator"]
    data = await request.json()
    orch._checkpoint.mark_failed(data.get("error", "Unknown"))
    return web.json_response({"status": "failed"})


async def _bg_saver(app):
    """Save histories + heartbeat every 30 seconds"""
    orch = app["orchestrator"]
    while True:
        await asyncio.sleep(30)
        orch.save_all_histories()
        cp = orch._checkpoint
        cp.checkpoint_path().touch(exist_ok=True)


def create_app() -> web.Application:
    app = web.Application()
    app["orchestrator"] = Orchestrator()

    orch = app["orchestrator"]
    for name, cfg in DEFAULT_AGENTS.items():
        orch.create_chat(name, cfg)

    static_dir = Path(__file__).parent / "static"

    app.router.add_get("/", lambda r: web.FileResponse(static_dir / "index.html"))
    app.router.add_get("/api/agents", handle_agents)
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_get("/api/history", handle_history)
    app.router.add_post("/api/agent/new", handle_new_agent)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/cleanup", handle_cleanup)
    app.router.add_get("/api/cache", handle_cache)
    app.router.add_get("/api/history/save", handle_history_save)
    app.router.add_get("/api/history/search", handle_history_search)
    app.router.add_get("/api/history/export", handle_history_export)
    app.router.add_post("/api/history/reset", handle_history_reset)
    app.router.add_post("/api/webhook", handle_webhook)
    app.router.add_post("/api/pipeline", handle_pipeline)
    app.router.add_get("/dashboard", handle_ui)
    app.router.add_get("/api/plugins", handle_plugins_list)
    app.router.add_post("/api/plugin/reload", handle_plugin_reload)
    app.router.add_post("/api/plugin/upload", handle_plugin_upload)
    app.router.add_get("/api/night-mode", handle_night_mode)
    app.router.add_post("/api/night-mode", handle_night_mode_set)
    app.router.add_get("/api/checkpoint", handle_checkpoint)
    app.router.add_post("/api/checkpoint/adopt", handle_checkpoint_adopt)
    app.router.add_post("/api/checkpoint/done", handle_checkpoint_done)
    app.router.add_post("/api/checkpoint/fail", handle_checkpoint_fail)
    app.router.add_get("/api/llm/status", handle_llm_status)
    app.router.add_post("/api/llm/switch", handle_llm_switch)
    app.router.add_post("/api/guest-import", handle_guest_import)
    app.router.add_post("/api/agent-role", handle_agent_role)
    app.router.add_post("/api/consilium", handle_consilium)
    app.router.add_post("/v1/chat/completions", handle_v1_chat)
    app.router.add_static("/static/", static_dir)

    async def startup(app):
        orch = app["orchestrator"]
        asyncio.create_task(_bg_saver(app))

        # Start night mode checker (enabled by default)
        orch.start_night_mode()

        # Check for orphaned checkpoints on startup
        cp = orch._checkpoint
        orphaned = cp.is_orphaned()
        sos = cp.check_sos()
        if orphaned:
            checkpoint_data = cp.load()
            print(f"[CHECKPOINT] Orphaned checkpoint detected! Agent: {checkpoint_data.get('agent', '?')}", file=sys.stderr)
            print(f"[CHECKPOINT] Goal: {checkpoint_data.get('goal', '?')[:120]}", file=sys.stderr)
            print(f"[CHECKPOINT] Use POST /api/checkpoint/adopt to resume", file=sys.stderr)
        if sos:
            print(f"[CHECKPOINT] SOS signal found: {sos.get('error', 'unknown')}", file=sys.stderr)

    async def cleanup(app):
        orch = app["orchestrator"]
        cp = orch._checkpoint
        cp.save(agent="system", goal="Server shutdown", status="orphaned", notes="Server stopping")
        cp.create_sos("Server shutdown")
        cp.stop_heartbeat()
        await orch.close_all()

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)

    return app


if __name__ == "__main__":
    static = Path(__file__).parent / "static"
    static.mkdir(exist_ok=True)
    port = 8080
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    if "--background" in sys.argv:
        app = create_app()
        app["orchestrator"]._background_task = asyncio.create_task(
            app["orchestrator"].background_mode()
        )
        web.run_app(app, host="127.0.0.1", port=port)
    else:
        web.run_app(create_app(), host="127.0.0.1", port=port)
