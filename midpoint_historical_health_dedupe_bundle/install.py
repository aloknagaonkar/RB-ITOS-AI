#!/usr/bin/env python3
"""Install recorded-live-health preference for Historical Replay."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent
FILES = (
    Path("scripts/materialize_midpoint_historical_health.py"),
    Path("tests/test_midpoint_historical_health_dedupe.py"),
)


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    if not (ROOT / "pyproject.toml").exists():
        raise SystemExit(f"STOP: place bundle directly inside repository: {ROOT}")
    python = ROOT / ".venv/bin/python"
    if not python.exists():
        raise SystemExit(f"STOP: virtualenv Python missing: {python}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = ROOT / "data/backups" / f"midpoint-health-dedupe-{stamp}"
    copied: list[Path] = []
    try:
        for relative in FILES:
            source = BUNDLE / "files" / relative
            target = ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            if target.exists():
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative)

        run([
            str(python), "-m", "pytest", "-q",
            "tests/test_midpoint_historical_health_dedupe.py",
            "tests/test_midpoint_historical_health_replay.py",
            "tests/test_midpoint_health_audit_inspect.py",
        ])
        run([
            str(python), "-m", "py_compile",
            "scripts/materialize_midpoint_historical_health.py",
        ])
        run(["git", "diff", "--check"])
    except Exception:
        for relative in reversed(copied):
            target = ROOT / relative
            backup = backup_root / relative
            if backup.exists():
                shutil.copy2(backup, target)
            elif target.exists():
                target.unlink()
        print("STOP: validation failed; source files restored.", file=sys.stderr)
        raise

    print("PASS: historical health deduplication installed and validated.")
    print("Recorded live health is authoritative; overlay fills missing evidence only.")
    print("Services, workers, audits, strategy decisions and orders were untouched.")
    if backup_root.exists():
        print("Backup:", backup_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
