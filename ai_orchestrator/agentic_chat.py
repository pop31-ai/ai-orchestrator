"""
Agentic Chat System - 7 agents with tool execution, streaming, tabbed UI
"""
import asyncio
import json
import os
import re
import signal
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
from urllib.parse import quote_plus

import aiohttp
from aiohttp import web


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
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    max_steps: int = 10
    tools: list = field(default_factory=lambda: [
        "web_search", "shell", "git", "file", "process", "user_agent", "api_call"
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


class AgentChat:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.executor = ToolExecutor(config.user_agent)
        self.messages: List[Dict] = []
        self.session_id = str(uuid.uuid4())[:8]
        self.step_count = 0
        self.max_steps = config.max_steps
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

        step = 0
        while self.step_count < self.max_steps:
            self.step_count += 1
            step += 1

            tool_results = await self._execute_tools(user_input if step == 1 else "")
            if tool_results:
                tool_msg = "Tool results:\n" + "\n".join(tool_results)
                self.messages.append({
                    "role": "tool",
                    "content": tool_msg,
                    "timestamp": datetime.now().isoformat(),
                })
                yield json.dumps({"tool_results": tool_results}) + "\n"

            should_continue = self._should_continue()
            if not should_continue:
                break

        response = self._build_response(user_input)
        self.messages.append({
            "role": "assistant",
            "content": response,
            "timestamp": datetime.now().isoformat(),
        })

        for i in range(0, len(response), 50):
            yield json.dumps({"token": response[i : i + 50]}) + "\n"
            await asyncio.sleep(0.01)

        yield json.dumps({"done": True}) + "\n"

    async def _execute_tools(self, text: str) -> List[str]:
        results = []
        t = text.lower().strip()

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

        return results

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

    def _should_continue(self) -> bool:
        if not self.messages:
            return False
        return self.messages[-1].get("role") == "tool" and self.step_count < self.max_steps

    def _build_response(self, task: str) -> str:
        t = task.lower()
        if any(k in t for k in ["search", "find", "look"]):
            return "Search completed. Results shown above."
        if any(k in t for k in ["run", "execute", "shell", "cmd"]):
            return "Command executed. Output shown above."
        if "git" in t:
            return "Git operation completed. Output shown above."
        if any(k in t for k in ["read doc", "create doc", "edit doc", "summary", "summarize"]):
            return "Document operation completed. Results shown above."
        if any(k in t for k in ["file", "read", "write", "list"]):
            return "File operation completed."
        if "user agent" in t:
            return "User agent updated."
        if "process" in t:
            return "Process operation completed."
        return f"Task processed: {task}"

    def get_history(self):
        return [m for m in self.messages if m["role"] != "system"]

    async def close(self):
        await self.executor.close()


class Orchestrator:
    def __init__(self):
        self.chats: Dict[str, AgentChat] = {}
        self._semaphore = asyncio.Semaphore(4)  # Max 4 concurrent tasks
        self._queue = asyncio.Queue()
        self._workers = 0
        self._worker_tasks = []

    def create_chat(self, name: str, config: AgentConfig) -> AgentChat:
        self.chats[name] = AgentChat(config)
        return self.chats[name]

    def get_chat(self, name: str) -> Optional[AgentChat]:
        return self.chats.get(name)

    def list_chats(self) -> List[str]:
        return list(self.chats.keys())

    async def enqueue(self, agent_name: str, message: str):
        """Queue a task for async dispatch"""
        await self._queue.put((agent_name, message))
        if self._workers < 4:
            self._workers += 1
            task = asyncio.create_task(self._worker_loop())
            self._worker_tasks.append(task)

    async def _worker_loop(self):
        """Worker: pulls tasks from queue, runs with semaphore"""
        while not self._queue.empty():
            agent_name, message = await self._queue.get()
            chat = self.get_chat(agent_name)
            if not chat:
                continue
            async with self._semaphore:
                async for _ in chat.process(message):
                    pass
            self._queue.task_done()
        self._workers -= 1

    async def get_status(self) -> Dict:
        """Resource usage and queue status"""
        import psutil
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory().percent
        except Exception:
            cpu = mem = 0
        return {
            "active_chats": len(self.chats),
            "queue_size": self._queue.qsize(),
            "concurrent_workers": self._workers,
            "semaphore_available": self._semaphore._value,
            "cpu_percent": cpu,
            "memory_percent": mem,
        }

    async def cleanup_idle(self, max_idle_minutes: int = 5):
        """Remove idle agent chats to free memory"""
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
                await chat.close()

    async def close_all(self):
        for chat in self.chats.values():
            await chat.close()


DEFAULT_AGENTS = {
    "researcher": AgentConfig(
        name="researcher",
        model="tinyllama",
        system_prompt=(
            "You are a research specialist. "
            "Use 'search <query>' to find information online. "
            "Be concise and cite sources."
        ),
    ),
    "engineer": AgentConfig(
        name="engineer",
        model="tinyllama",
        system_prompt=(
            "You are a systems engineer. "
            "Use 'run <command>' to execute shell commands. "
            "Use git clone/status/commit/push for git operations. Be precise and safe."
        ),
    ),
    "analyst": AgentConfig(
        name="analyst",
        model="tinyllama",
        system_prompt=(
            "You are a data analyst. "
            "Combine web search with local analysis. "
            "Use 'search <query>' and 'run <cmd>' as needed."
        ),
    ),
    "navigator": AgentConfig(
        name="navigator",
        model="tinyllama",
        system_prompt=(
            "You specialize in web navigation and user-agent handling. "
            "Use 'user agent get/set' to manage browser identity."
        ),
    ),
    "file_manager": AgentConfig(
        name="file_manager",
        model="tinyllama",
        system_prompt=(
            "You manage files. "
            "Use 'read file <path>', 'write file <path> with <content>', "
            "'list files [path]' to manage files."
        ),
    ),
    "devops": AgentConfig(
        name="devops",
        model="tinyllama",
        system_prompt=(
            "You are a DevOps engineer. "
            "Use git clone/push/pull/commit, run <cmd>, "
            "process list/output/kill to manage infrastructure."
        ),
    ),
    "coder": AgentConfig(
        name="coder",
        model="tinyllama",
        system_prompt=(
            "You are a senior software engineer. "
            "Write clean, well-structured code. "
            "Plan architecture, create project structure, implement module by module. "
            "Always output complete, runnable code."
        ),
    ),
    "doc_agent": AgentConfig(
        name="doc_agent",
        model="tinyllama",
        system_prompt=(
            "You are a document and PDF specialist. "
            "Commands:\n"
            "- read file <path> — read text or PDF\n"
            "- pdf all <path> — read entire PDF\n"
            "- pdf page <path> <n> — read specific page\n"
            "- pdf range <path> 1-10 — read page range\n"
            "- pdf info <path> — PDF metadata\n"
            "- summary <path> — file statistics\n"
            "- search docs <query> — grep text and PDFs\n"
            "- create doc <path> with <content>\n"
            "- edit doc <path> find <old> replace <new>\n"
            "- list docs [path]"
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
        async for chunk in chat.process(message):
            await resp.write(chunk.encode("utf-8"))
    except Exception as e:
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
    app.router.add_get("/dashboard", handle_ui)
    app.router.add_static("/static/", static_dir)

    async def cleanup(app):
        await app["orchestrator"].close_all()
    app.on_cleanup.append(cleanup)

    return app


if __name__ == "__main__":
    static = Path(__file__).parent / "static"
    static.mkdir(exist_ok=True)
    web.run_app(create_app(), host="127.0.0.1", port=8080)
