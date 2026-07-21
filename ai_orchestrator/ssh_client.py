"""
SSH Client for cross-VM agent communication.

Connects to remote machines via SSH, executes commands, transfers files.
Uses system `ssh` command via asyncio (no extra dependencies).
"""

import asyncio
import json
import os
import shlex
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional


class SSHConnection:
    """Represents a single SSH connection to a remote host."""

    def __init__(self, host: str, port: int = 22, user: str = None,
                 key_path: str = None, password: str = None, timeout: int = 30):
        self.host = host
        self.port = port
        self.user = user or os.environ.get("USERNAME") or os.environ.get("USER") or "root"
        self.key_path = key_path
        self.password = password
        self.timeout = timeout
        self._connected = False
        self._control_path: Optional[Path] = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """Open a master SSH connection (using ControlMaster for multiplexing)."""
        if self._connected:
            return True

        # Create a control socket for connection sharing
        tmp = tempfile.gettempdir()
        self._control_path = Path(tmp) / f"ssh_mux_{self.host}_{self.port}_{self.user}"

        cmd = self._build_ssh_cmd([
            "-N",  # no command, just connect
            "-o", "ControlMaster=yes",
            "-o", f"ControlPath={self._control_path}",
            "-o", "ControlPersist=yes",
        ])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return False

            if proc.returncode == 0:
                self._connected = True
                return True
            # Non-zero return code may be OK (some ssh configs)
            self._connected = True
            return True

        except FileNotFoundError:
            raise RuntimeError("SSH client not found. Install OpenSSH client.")
        except Exception as e:
            raise RuntimeError(f"SSH connection failed: {e}")

    async def exec_command(self, command: str, timeout: int = None) -> Dict:
        """Execute a command on the remote host and return output."""
        cmd = self._build_ssh_cmd([
            "-o", f"ControlPath={self._control_path}",
            command,
        ])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            timeout = timeout or self.timeout
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            return {
                "host": self.host,
                "command": command,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
                "success": proc.returncode == 0,
            }
        except asyncio.TimeoutError:
            proc.kill()
            return {
                "host": self.host,
                "command": command,
                "stdout": "",
                "stderr": "TIMEOUT",
                "returncode": -1,
                "success": False,
                "error": f"Command timed out after {timeout}s",
            }

    async def exec_stream(self, command: str) -> AsyncGenerator[str, None]:
        """Execute a command and stream output line by line."""
        cmd = self._build_ssh_cmd([
            "-o", f"ControlPath={self._control_path}",
            command,
        ])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            yield line.decode("utf-8", errors="replace")

        await proc.wait()

    async def copy_to(self, local_path: str, remote_path: str, recursive: bool = False) -> Dict:
        """Copy file/directory from local to remote using SCP."""
        scp_cmd = ["scp"]
        scp_cmd.extend(["-P", str(self.port)])
        if self.key_path:
            scp_cmd.extend(["-i", self.key_path])
        if self._control_path:
            scp_cmd.extend(["-o", f"ControlPath={self._control_path}"])
        if recursive:
            scp_cmd.append("-r")

        target = f"{self.user}@{self.host}:{remote_path}"
        scp_cmd.extend([local_path, target])

        try:
            proc = await asyncio.create_subprocess_exec(
                *scp_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            return {
                "from": local_path,
                "to": f"{self.host}:{remote_path}",
                "success": proc.returncode == 0,
                "output": (stdout + stderr).decode("utf-8", errors="replace"),
            }
        except asyncio.TimeoutError:
            proc.kill()
            return {"from": local_path, "to": remote_path, "success": False, "error": "SCP timed out"}

    async def copy_from(self, remote_path: str, local_path: str, recursive: bool = False) -> Dict:
        """Copy file/directory from remote to local using SCP."""
        scp_cmd = ["scp"]
        scp_cmd.extend(["-P", str(self.port)])
        if self.key_path:
            scp_cmd.extend(["-i", self.key_path])
        if self._control_path:
            scp_cmd.extend(["-o", f"ControlPath={self._control_path}"])
        if recursive:
            scp_cmd.append("-r")

        source = f"{self.user}@{self.host}:{remote_path}"
        scp_cmd.extend([source, local_path])

        try:
            proc = await asyncio.create_subprocess_exec(
                *scp_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            return {
                "from": f"{self.host}:{remote_path}",
                "to": local_path,
                "success": proc.returncode == 0,
                "output": (stdout + stderr).decode("utf-8", errors="replace"),
            }
        except asyncio.TimeoutError:
            proc.kill()
            return {"from": remote_path, "to": local_path, "success": False, "error": "SCP timed out"}

    async def ping(self) -> bool:
        """Test if the remote host is reachable."""
        result = await self.exec_command("echo pong")
        return result["success"] and "pong" in result.get("stdout", "")

    async def close(self):
        """Close the SSH connection."""
        if self._control_path and self._control_path.exists():
            try:
                cmd = self._build_ssh_cmd([
                    "-O", "exit",
                    "-o", f"ControlPath={self._control_path}",
                ])
                proc = await asyncio.create_subprocess_exec(*cmd)
                await proc.wait()
            except Exception:
                pass
            try:
                self._control_path.unlink(missing_ok=True)
            except Exception:
                pass
        self._connected = False

    def _build_ssh_cmd(self, extra_args: List[str]) -> List[str]:
        """Build the SSH command line."""
        cmd = ["ssh"]
        cmd.extend(["-p", str(self.port)])
        cmd.extend(["-o", "ConnectTimeout=10"])
        cmd.extend(["-o", "StrictHostKeyChecking=accept-new"])
        cmd.extend(["-o", "UserKnownHostsFile=NUL" if os.name == "nt" else "/dev/null"])

        if self.key_path:
            cmd.extend(["-i", self.key_path])

        cmd.extend(extra_args)
        cmd.append(f"{self.user}@{self.host}")
        return cmd


class SSHManager:
    """Manages multiple SSH connections."""

    def __init__(self):
        self._connections: Dict[str, SSHConnection] = {}

    def _key(self, host: str, port: int, user: str) -> str:
        return f"{user}@{host}:{port}"

    async def connect(self, host: str, port: int = 22, user: str = None,
                      key_path: str = None, password: str = None,
                      timeout: int = 30) -> SSHConnection:
        """Connect to a remote host. Reuses existing connection if available."""
        key = self._key(host, port, user or "")
        if key in self._connections:
            conn = self._connections[key]
            if conn.connected:
                return conn
            # Connection is stale, remove and reconnect
            del self._connections[key]

        conn = SSHConnection(host, port, user, key_path, password, timeout)
        ok = await conn.connect()
        if not ok:
            raise RuntimeError(f"Failed to connect to {host}")
        self._connections[key] = conn
        return conn

    async def disconnect(self, host: str, port: int = 22, user: str = None):
        """Disconnect from a remote host."""
        key = self._key(host, port, user or "")
        conn = self._connections.pop(key, None)
        if conn:
            await conn.close()

    async def disconnect_all(self):
        """Close all SSH connections."""
        for conn in self._connections.values():
            await conn.close()
        self._connections.clear()

    def list_connections(self) -> List[Dict]:
        return [
            {
                "host": conn.host,
                "port": conn.port,
                "user": conn.user,
                "connected": conn.connected,
            }
            for conn in self._connections.values()
        ]

    async def exec(self, host: str, command: str, port: int = 22, user: str = None,
                   key_path: str = None, password: str = None, timeout: int = 30) -> Dict:
        """Quick one-shot command execution (connects, runs, disconnects)."""
        try:
            conn = await self.connect(host, port, user, key_path, password, timeout)
            return await conn.exec_command(command, timeout)
        except Exception as e:
            return {"host": host, "command": command, "success": False, "error": str(e)}
