"""Built-in tools for the agent"""

import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agent import Tool, ToolResult, AgentContext


class ShellTool(Tool):
    """Execute shell commands"""

    def __init__(self):
        super().__init__(
            name="shell",
            description="Execute a shell command and return output",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute"},
                    "cwd": {"type": "string", "description": "Working directory (optional)"},
                    "timeout": {"type": "number", "description": "Timeout in seconds (default: 30)"},
                    "shell": {"type": "boolean", "description": "Run in shell (default: true)"}
                },
                "required": ["command"]
            }
        )

    async def execute(self, arguments: Dict[str, Any], context: AgentContext) -> ToolResult:
        command = arguments["command"]
        cwd = arguments.get("cwd", str(Path.cwd()))
        timeout = arguments.get("timeout", 30)
        shell = arguments.get("shell", True)

        try:
            if shell:
                if sys.platform == "win32":
                    cmd = ["powershell", "-Command", command]
                else:
                    cmd = ["bash", "-c", command]
            else:
                cmd = shlex.split(command)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    tool_call_id=context.metadata.get("tool_call_id", ""),
                    name=self.name,
                    result=None,
                    error=f"Command timed out after {timeout}s"
                )

            output = stdout.decode('utf-8', errors='replace')
            error_output = stderr.decode('utf-8', errors='replace')

            result = {
                "stdout": output,
                "stderr": error_output,
                "returncode": proc.returncode,
                "command": command
            }

            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result=result,
                error=error_output if proc.returncode != 0 else None
            )

        except Exception as e:
            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result=None,
                error=str(e)
            )


class FileReadTool(Tool):
    """Read file contents"""

    def __init__(self):
        super().__init__(
            name="file_read",
            description="Read contents of a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "encoding": {"type": "string", "description": "File encoding (default: utf-8)"},
                    "offset": {"type": "integer", "description": "Line offset to start reading"},
                    "limit": {"type": "integer", "description": "Maximum lines to read"}
                },
                "required": ["path"]
            }
        )

    async def execute(self, arguments: Dict[str, Any], context: AgentContext) -> ToolResult:
        path = Path(arguments["path"])
        encoding = arguments.get("encoding", "utf-8")
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit")

        try:
            if not path.exists():
                return ToolResult(
                    tool_call_id=context.metadata.get("tool_call_id", ""),
                    name=self.name,
                    result=None,
                    error=f"File not found: {path}"
                )

            if not path.is_file():
                return ToolResult(
                    tool_call_id=context.metadata.get("tool_call_id", ""),
                    name=self.name,
                    result=None,
                    error=f"Not a file: {path}"
                )

            with open(path, 'r', encoding=encoding) as f:
                lines = f.readlines()

            if offset > 0:
                lines = lines[offset:]
            if limit:
                lines = lines[:limit]

            content = "".join(lines)

            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result={"content": content, "path": str(path), "lines": len(lines)},
                error=None
            )

        except Exception as e:
            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result=None,
                error=str(e)
            )


class FileWriteTool(Tool):
    """Write file contents"""

    def __init__(self):
        super().__init__(
            name="file_write",
            description="Write content to a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                    "encoding": {"type": "string", "description": "File encoding (default: utf-8)"},
                    "create_dirs": {"type": "boolean", "description": "Create parent directories (default: true)"}
                },
                "required": ["path", "content"]
            }
        )

    async def execute(self, arguments: Dict[str, Any], context: AgentContext) -> ToolResult:
        path = Path(arguments["path"])
        content = arguments["content"]
        encoding = arguments.get("encoding", "utf-8")
        create_dirs = arguments.get("create_dirs", True)

        try:
            if create_dirs:
                path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, 'w', encoding=encoding) as f:
                f.write(content)

            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result={"path": str(path), "bytes": len(content.encode(encoding)), "lines": content.count('\n') + 1},
                error=None
            )

        except Exception as e:
            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result=None,
                error=str(e)
            )


class FileEditTool(Tool):
    """Edit file with string replacement"""

    def __init__(self):
        super().__init__(
            name="file_edit",
            description="Edit a file by replacing text",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit"},
                    "old_string": {"type": "string", "description": "String to replace"},
                    "new_string": {"type": "string", "description": "String to replace with"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences (default: false)"}
                },
                "required": ["path", "old_string", "new_string"]
            }
        )

    async def execute(self, arguments: Dict[str, Any], context: AgentContext) -> ToolResult:
        path = Path(arguments["path"])
        old_string = arguments["old_string"]
        new_string = arguments["new_string"]
        replace_all = arguments.get("replace_all", False)

        try:
            if not path.exists():
                return ToolResult(
                    tool_call_id=context.metadata.get("tool_call_id", ""),
                    name=self.name,
                    result=None,
                    error=f"File not found: {path}"
                )

            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            if old_string not in content:
                return ToolResult(
                    tool_call_id=context.metadata.get("tool_call_id", ""),
                    name=self.name,
                    result=None,
                    error=f"String not found in file: {old_string[:50]}..."
                )

            if replace_all:
                new_content = content.replace(old_string, new_string)
                count = content.count(old_string)
            else:
                new_content = content.replace(old_string, new_string, 1)
                count = 1

            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result={"path": str(path), "replacements": count},
                error=None
            )

        except Exception as e:
            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result=None,
                error=str(e)
            )


class FileListTool(Tool):
    """List directory contents"""

    def __init__(self):
        super().__init__(
            name="file_list",
            description="List files in a directory",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"},
                    "recursive": {"type": "boolean", "description": "List recursively (default: false)"},
                    "pattern": {"type": "string", "description": "Glob pattern (optional)"},
                    "include_hidden": {"type": "boolean", "description": "Include hidden files (default: false)"}
                },
                "required": ["path"]
            }
        )

    async def execute(self, arguments: Dict[str, Any], context: AgentContext) -> ToolResult:
        path = Path(arguments["path"])
        recursive = arguments.get("recursive", False)
        pattern = arguments.get("pattern")
        include_hidden = arguments.get("include_hidden", False)

        try:
            if not path.exists():
                return ToolResult(
                    tool_call_id=context.metadata.get("tool_call_id", ""),
                    name=self.name,
                    result=None,
                    error=f"Path not found: {path}"
                )

            if not path.is_dir():
                return ToolResult(
                    tool_call_id=context.metadata.get("tool_call_id", ""),
                    name=self.name,
                    result=None,
                    error=f"Not a directory: {path}"
                )

            if pattern:
                if recursive:
                    files = list(path.rglob(pattern))
                else:
                    files = list(path.glob(pattern))
            else:
                if recursive:
                    files = list(path.rglob("*"))
                else:
                    files = list(path.iterdir())

            if not include_hidden:
                files = [f for f in files if not f.name.startswith('.')]

            result = []
            for f in sorted(files):
                stat = f.stat()
                result.append({
                    "name": f.name,
                    "path": str(f),
                    "type": "directory" if f.is_dir() else "file",
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })

            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result={"files": result, "count": len(result)},
                error=None
            )

        except Exception as e:
            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result=None,
                error=str(e)
            )


class FileGlobTool(Tool):
    """Find files matching a glob pattern"""

    def __init__(self):
        super().__init__(
            name="file_glob",
            description="Find files matching a glob pattern",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern"},
                    "root": {"type": "string", "description": "Root directory (default: cwd)"}
                },
                "required": ["pattern"]
            }
        )

    async def execute(self, arguments: Dict[str, Any], context: AgentContext) -> ToolResult:
        pattern = arguments["pattern"]
        root = Path(arguments.get("root", Path.cwd()))

        try:
            files = list(root.rglob(pattern))
            result = []
            for f in sorted(files):
                if f.is_file():
                    stat = f.stat()
                    result.append({
                        "name": f.name,
                        "path": str(f),
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    })

            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result={"files": result, "count": len(result)},
                error=None
            )

        except Exception as e:
            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result=None,
                error=str(e)
            )


class FileGrepTool(Tool):
    """Search for text in files"""

    def __init__(self):
        super().__init__(
            name="file_grep",
            description="Search for text pattern in files",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search"},
                    "path": {"type": "string", "description": "Path to search (default: cwd)"},
                    "include": {"type": "string", "description": "File pattern to include (optional)"},
                    "exclude": {"type": "string", "description": "File pattern to exclude (optional)"},
                    "max_results": {"type": "integer", "description": "Maximum results (default: 100)"},
                    "context_lines": {"type": "integer", "description": "Lines of context (default: 2)"}
                },
                "required": ["pattern"]
            }
        )

    async def execute(self, arguments: Dict[str, Any], context: AgentContext) -> ToolResult:
        pattern = arguments["pattern"]
        path = Path(arguments.get("path", Path.cwd()))
        include = arguments.get("include")
        exclude = arguments.get("exclude")
        max_results = arguments.get("max_results", 100)
        context_lines = arguments.get("context_lines", 2)

        try:
            regex = re.compile(pattern)
            files = []

            if path.is_file():
                files = [path]
            else:
                for f in path.rglob("*"):
                    if f.is_file():
                        if include and not f.match(include):
                            continue
                        if exclude and f.match(exclude):
                            continue
                        files.append(f)

            results = []
            for f in files:
                try:
                    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
                        lines = fp.readlines()
                    for i, line in enumerate(lines):
                        if regex.search(line):
                            start = max(0, i - context_lines)
                            end = min(len(lines), i + context_lines + 1)
                            results.append({
                                "file": str(f),
                                "line": i + 1,
                                "match": line.rstrip(),
                                "context": "".join(lines[start:end]).rstrip()
                            })
                            if len(results) >= max_results:
                                break
                except Exception:
                    continue
                if len(results) >= max_results:
                    break

            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result={"matches": results, "count": len(results)},
                error=None
            )

        except Exception as e:
            return ToolResult(
                tool_call_id=context.metadata.get("tool_call_id", ""),
                name=self.name,
                result=None,
                error=str(e)
            )


def register_builtin_tools(registry):
    """Register all built-in tools"""
    tools = [
        ShellTool(),
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        FileListTool(),
        FileGlobTool(),
        FileGrepTool(),
    ]

    for tool in tools:
        registry.register(tool, category="builtin")

    return tools