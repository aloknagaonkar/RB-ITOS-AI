from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from red_bar_lab.execution.process_lock import ProcessLock, WorkerAlreadyRunning


def test_process_lock_acquires_and_releases(tmp_path: Path):
    path = tmp_path / "worker.lock"
    lock = ProcessLock(path, "worker")

    lock.acquire()
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()

    lock.release()
    assert not path.exists()


def test_second_lock_rejects_live_owner(tmp_path: Path):
    path = tmp_path / "worker.lock"
    first = ProcessLock(path, "worker")
    second = ProcessLock(path, "worker")
    first.acquire()
    try:
        with pytest.raises(WorkerAlreadyRunning):
            second.acquire()
    finally:
        first.release()


def test_stale_lock_is_recovered(tmp_path: Path):
    path = tmp_path / "worker.lock"
    path.write_text(json.dumps({"pid": 99999999, "name": "old"}), encoding="utf-8")

    lock = ProcessLock(path, "worker")
    lock.acquire()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    lock.release()
