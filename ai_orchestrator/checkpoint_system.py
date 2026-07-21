"""
Checkpoint System — resilience layer for AI orchestration.

If the AI process crashes/disconnects/is killed, the checkpoint file
preserves the full task state so another instance can resume.

Checkpoint file: .opencode/checkpoint.json
Heartbeat file:  .opencode/alive (timestamp, updated every 30s)
SOS file:        .opencode/SOS.flg (created on abort)

Manual trigger:  touch .opencode/SOS.flg → any AI can pick up
"""

import json
import os
import sys
import time
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class Checkpoint:
    """
    Saves and restores full session state.

    Structure of checkpoint.json:
    {
      "version": 2,
      "pid": 12345,
      "created_at": "2026-07-20T16:53:00Z",
      "last_heartbeat": "2026-07-20T16:53:30Z",
      "agent": "engineer",
      "goal": "deploy service X to production",
      "status": "in_progress",        # in_progress | done | failed | orphaned
      "progress_pct": 65,
      "task_plan": [
        {"step": 1, "desc": "git clone repo", "done": true},
        {"step": 2, "desc": "build binary", "done": true},
        {"step": 3, "desc": "restart daemon", "done": false},
        {"step": 4, "desc": "health check", "done": false}
      ],
      "context": {
        "cwd": "C:\\path\\to\\project",
        "branch": "main",
        "last_command": "git push origin main",
        "last_output": "Everything up-to-date\n",
        "history": [
          {"role": "user", "content": "deploy service"},
          {"role": "assistant", "content": "Cloning repo..."},
          {"role": "tool", "content": "$ git clone ...\nCloning into..."}
        ],
        "files_created": [],
        "files_modified": ["config.yml", "deploy.sh"]
      },
      "notes": "Waiting for health check response",
      "error": null,
      "successors_available": ["researcher", "analyst"]
    }

    SOS file: .opencode/SOS.flg
    - Created when process is killed or detects fatal error
    - Any AI/orchestrator can watch for this file
    - Content: JSON with last checkpoint path + error info
    """

    VERSION = 2

    def __init__(self, project_dir: str = None):
        self.project_dir = Path(project_dir or os.getcwd())
        self.opencode_dir = self.project_dir / ".opencode"
        self.opencode_dir.mkdir(parents=True, exist_ok=True)
        self._heartbeat_timer = None
        self._running = False

    # ── paths ──
    def checkpoint_path(self) -> Path:
        return self.opencode_dir / "checkpoint.json"

    def alive_path(self) -> Path:
        return self.opencode_dir / "alive"

    def sos_path(self) -> Path:
        return self.opencode_dir / "SOS.flg"

    # ── checkpoint I/O ──
    def save(self,
             agent: str = "unknown",
             goal: str = "",
             status: str = "in_progress",
             progress_pct: int = 0,
             task_plan: List[Dict] = None,
             context: Dict = None,
             notes: str = "",
             error: str = None,
             successors: List[str] = None,
             ) -> Dict:
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "version": self.VERSION,
            "pid": os.getpid(),
            "created_at": now,
            "last_heartbeat": now,
            "agent": agent,
            "goal": goal,
            "status": status,
            "progress_pct": progress_pct,
            "task_plan": task_plan or [],
            "context": context or {},
            "notes": notes,
            "error": error,
            "successors_available": successors or [],
        }
        path = self.checkpoint_path()
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data

    def load(self) -> Optional[Dict]:
        path = self.checkpoint_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def is_orphaned(self, max_age_sec: int = 120) -> bool:
        """Check if checkpoint exists but the owning PID is dead or heartbeat is stale"""
        cp = self.load()
        if not cp:
            return False

        # PID check
        pid = cp.get("pid")
        if pid and self._pid_exists(pid):
            return False  # still alive

        # Heartbeat check
        hb = cp.get("last_heartbeat")
        if hb:
            try:
                hb_time = datetime.fromisoformat(hb)
                age = (datetime.now(timezone.utc) - hb_time).total_seconds()
                if age < max_age_sec:
                    return False  # recent heartbeat
            except Exception:
                pass

        return True

    def adopt_orphan(self, new_agent: str = None) -> Optional[Dict]:
        """Take over orphaned checkpoint. Returns the checkpoint data."""
        cp = self.load()
        if not cp:
            return None
        cp["status"] = "orphaned"
        cp["notes"] = (cp.get("notes", "") +
                       f"\n[Adopted by PID {os.getpid()} at {datetime.now(timezone.utc).isoformat()}]")
        if new_agent:
            cp["agent"] = new_agent
        cp["pid"] = os.getpid()
        cp["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        return cp

    def mark_done(self, result: str = ""):
        cp = self.load() or {}
        cp["status"] = "done"
        cp["progress_pct"] = 100
        cp["notes"] = result
        cp["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        self.checkpoint_path().write_text(json.dumps(cp, indent=2, ensure_ascii=False), encoding="utf-8")
        self.remove_sos()

    def mark_failed(self, error: str):
        cp = self.load() or {}
        cp["status"] = "failed"
        cp["error"] = error
        cp["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        self.checkpoint_path().write_text(json.dumps(cp, indent=2, ensure_ascii=False), encoding="utf-8")
        self.create_sos(error)

    # ── Heartbeat ──
    def start_heartbeat(self, interval_sec: int = 30):
        """Background thread: updates alive file + checkpoint heartbeat every N sec"""
        if self._running:
            return
        self._running = True

        def _beat():
            while self._running:
                try:
                    now = datetime.now(timezone.utc).isoformat()
                    # Update alive file
                    self.alive_path().write_text(now, encoding="utf-8")
                    # Update checkpoint heartbeat if exists
                    cp = self.load()
                    if cp:
                        cp["last_heartbeat"] = now
                        self.checkpoint_path().write_text(
                            json.dumps(cp, indent=2, ensure_ascii=False), encoding="utf-8"
                        )
                except Exception:
                    pass
                time.sleep(interval_sec)

        self._heartbeat_timer = threading.Thread(target=_beat, daemon=True)
        self._heartbeat_timer.start()

    def stop_heartbeat(self):
        self._running = False

    # ── SOS ──
    def create_sos(self, error: str = "Unknown failure"):
        """Create SOS.flg so other instances know something went wrong"""
        try:
            sos = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "error": error,
                "checkpoint": str(self.checkpoint_path()),
            }
            self.sos_path().write_text(json.dumps(sos, indent=2), encoding="utf-8")
        except Exception:
            pass

    def remove_sos(self):
        try:
            if self.sos_path().exists():
                self.sos_path().unlink()
        except Exception:
            pass

    def check_sos(self) -> Optional[Dict]:
        """Check if SOS.flg exists and return its content"""
        if not self.sos_path().exists():
            return None
        try:
            return json.loads(self.sos_path().read_text(encoding="utf-8"))
        except Exception:
            return {"error": "unreadable SOS"}

    def list_active_checkpoints(self, dirs: List[str] = None) -> List[Dict]:
        """Scan multiple project dirs for active checkpoints"""
        results = []
        for d in dirs or [str(self.project_dir)]:
            cp_path = Path(d) / ".opencode" / "checkpoint.json"
            if cp_path.exists():
                try:
                    data = json.loads(cp_path.read_text(encoding="utf-8"))
                    data["_dir"] = d
                    results.append(data)
                except Exception:
                    pass
        return results

    # ── helpers ──
    @staticmethod
    def _pid_exists(pid: int) -> bool:
        """Check if process with given PID is alive (cross-platform)"""
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x400, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def cleanup(self):
        self.stop_heartbeat()


# ── Signal handler: auto-save checkpoint on SIGTERM/SIGINT ──

_checkpoint_instance: Optional[Checkpoint] = None


def _signal_handler(signum, frame):
    global _checkpoint_instance
    if _checkpoint_instance:
        cp = _checkpoint_instance.load()
        if cp:
            cp["status"] = "orphaned"
            cp["error"] = f"Killed by signal {signum}"
            _checkpoint_instance.checkpoint_path().write_text(
                json.dumps(cp, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            _checkpoint_instance.create_sos(f"Signal {signum}")
    sys.exit(signum)


def install_signal_handler(cp: Checkpoint):
    global _checkpoint_instance
    _checkpoint_instance = cp
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


# ── CLI ──
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Checkpoint system for AI orchestration")
    parser.add_argument("action", choices=["save", "load", "status", "adopt", "done", "sos", "scan", "watch"])
    parser.add_argument("--agent", default="unknown")
    parser.add_argument("--goal", default="")
    parser.add_argument("--dir", default=os.getcwd())
    parser.add_argument("--error")
    parser.add_argument("--note")
    args = parser.parse_args()

    cp = Checkpoint(args.dir)

    if args.action == "save":
        data = cp.save(agent=args.agent, goal=args.goal, notes=args.note or "")
        print(json.dumps(data, indent=2))

    elif args.action == "load":
        data = cp.load()
        if data:
            print(json.dumps(data, indent=2))
        else:
            print("No checkpoint found", file=sys.stderr)
            sys.exit(1)

    elif args.action == "status":
        orphaned = cp.is_orphaned()
        data = cp.load()
        print(json.dumps({
            "exists": data is not None,
            "orphaned": orphaned,
            "sos_exists": cp.sos_path().exists(),
            "data": data,
        }, indent=2, ensure_ascii=False))

    elif args.action == "adopt":
        if cp.is_orphaned():
            data = cp.adopt_orphan(args.agent)
            cp.save(
                agent=data["agent"],
                goal=data.get("goal", ""),
                status="in_progress",
                progress_pct=data.get("progress_pct", 0),
                task_plan=data.get("task_plan", []),
                context=data.get("context", {}),
                notes=data.get("notes", ""),
                successors=data.get("successors_available", []),
            )
            print(f"Adopted orphan checkpoint, agent={data['agent']}")
        else:
            print("No orphaned checkpoint to adopt", file=sys.stderr)
            sys.exit(1)

    elif args.action == "done":
        cp.mark_done(args.note or "")
        print("Checkpoint marked done")

    elif args.action == "sos":
        if args.error:
            cp.create_sos(args.error)
        else:
            data = cp.check_sos()
            print(json.dumps(data, indent=2) if data else "No SOS")

    elif args.action == "scan":
        results = cp.list_active_checkpoints(
            dirs=args.dir.split(",") if "," in args.dir else [args.dir]
        )
        print(json.dumps(results, indent=2, ensure_ascii=False))

    elif args.action == "watch":
        """Watch for SOS/orphaned checkpoints every 10 seconds"""
        print(f"Watching {args.dir}/.opencode for SOS/orphaned signals...")
        while True:
            sos = cp.check_sos()
            if sos:
                print(f"[SOS] {json.dumps(sos)}")
                cp.remove_sos()
            if cp.is_orphaned():
                data = cp.load()
                if data:
                    print(f"[ORPHAN] {data.get('agent')}: {data.get('goal', '')[:80]}")
            time.sleep(10)
