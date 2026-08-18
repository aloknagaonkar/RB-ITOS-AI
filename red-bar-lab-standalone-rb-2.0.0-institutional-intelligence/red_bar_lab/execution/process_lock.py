from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
from typing import Any


class WorkerAlreadyRunning(RuntimeError):
    pass


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@dataclass
class ProcessLock:
    path: Path
    name: str
    acquired: bool = False

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": self.name,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
        }
        while True:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                existing = self._read()
                try:
                    existing_pid = int(existing.get("pid") or 0)
                except (TypeError, ValueError):
                    existing_pid = 0
                if _pid_is_alive(existing_pid):
                    raise WorkerAlreadyRunning(
                        f"{self.name} is already running with PID {existing_pid}."
                    )
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            self.acquired = True
            return

    def release(self) -> None:
        if not self.acquired:
            return
        existing = self._read()
        try:
            owner_pid = int(existing.get("pid") or 0)
        except (TypeError, ValueError):
            owner_pid = 0
        if owner_pid in {0, os.getpid()}:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self.acquired = False

    def __enter__(self) -> "ProcessLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


__all__ = ["WorkerAlreadyRunning", "ProcessLock"]
