"""Cross-platform process controller for Windows and POSIX systems."""

from __future__ import annotations

import ctypes
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ManagedProcess:
    """A tracked child process."""

    name: str
    pid: Optional[int] = None
    proc: Optional[subprocess.Popen] = None
    command: List[str] = None
    started_at: Optional[float] = None

    def __post_init__(self):
        if self.command is None:
            self.command = []


class ProcessController:
    """OS-abstracted process lifecycle manager."""

    def __init__(self):
        self._managed: Dict[str, ManagedProcess] = {}
        self._is_windows = sys.platform == "win32"

    @property
    def is_windows(self) -> bool:
        return self._is_windows

    def start(self, name: str, command: List[str], env_extras: Optional[dict] = None) -> ManagedProcess:
        """Start a child process with OS-appropriate process group settings."""
        env = dict(os.environ)
        if env_extras:
            env.update(env_extras)

        kwargs: dict = {
            "args": command,
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }

        if self._is_windows:
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True

        logger.info("Starting %s: %s", name, " ".join(command))
        proc = subprocess.Popen(**kwargs)

        managed = ManagedProcess(
            name=name,
            pid=proc.pid,
            proc=proc,
            command=command,
            started_at=time.time(),
        )
        self._managed[name] = managed
        return managed

    def stop(self, name: str, timeout: float = 10.0) -> bool:
        """Gracefully stop a child process. Returns True if stopped."""
        managed = self._managed.get(name)
        if managed is None or managed.proc is None:
            return True

        proc = managed.proc
        if proc.poll() is not None:
            return True

        try:
            if self._is_windows:
                self._stop_windows(managed, timeout)
            else:
                self._stop_posix(managed, timeout)
        except Exception as exc:
            logger.warning("Error stopping %s: %s", name, exc)
            self._force_kill(managed)

        stopped = proc.poll() is not None
        if stopped:
            logger.info("Stopped %s (pid=%s)", name, managed.pid)
        else:
            logger.warning("Failed to stop %s (pid=%s)", name, managed.pid)
        return stopped

    def stop_all(self, timeout: float = 10.0) -> Dict[str, bool]:
        """Stop all managed processes. Returns {name: success}."""
        results = {}
        for name in list(self._managed):
            results[name] = self.stop(name, timeout=timeout)
        return results

    def is_running(self, name: str) -> bool:
        """Check if a managed process is still running."""
        managed = self._managed.get(name)
        if managed is None or managed.proc is None:
            return False
        return managed.proc.poll() is None

    def get_exit_code(self, name: str) -> Optional[int]:
        managed = self._managed.get(name)
        if managed is None or managed.proc is None:
            return None
        return managed.proc.poll()

    def get_pid(self, name: str) -> Optional[int]:
        managed = self._managed.get(name)
        if managed is None:
            return None
        return managed.pid

    def _stop_windows(self, managed: ManagedProcess, timeout: float) -> None:
        proc = managed.proc

        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, ProcessLookupError):
            pass

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return
            time.sleep(0.25)

        logger.info("Graceful stop timed out for %s, using taskkill /F /T", managed.name)
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(managed.pid)],
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        deadline2 = time.monotonic() + 5.0
        while time.monotonic() < deadline2:
            if proc.poll() is not None:
                return
            time.sleep(0.25)

    def _stop_posix(self, managed: ManagedProcess, timeout: float) -> None:
        proc = managed.proc
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                proc.terminate()
            except (OSError, ProcessLookupError):
                return

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return
            time.sleep(0.25)

        self._force_kill(managed)

    def _force_kill(self, managed: ManagedProcess) -> None:
        proc = managed.proc
        if proc is None:
            return
        try:
            if self._is_windows:
                proc.kill()
            else:
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    proc.kill()
        except (OSError, ProcessLookupError):
            pass

    def cleanup(self) -> None:
        """Release references to managed processes."""
        self._managed.clear()
