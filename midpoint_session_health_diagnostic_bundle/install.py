#!/usr/bin/env python3
"""Install and validate the read-only Midpoint session health diagnostic."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).resolve().parent / "files"
FILES = (
    Path("scripts/diagnose_midpoint_session_health.py"),
    Path("tests/test_diagnose_midpoint_session_health.py"),
)


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "data" / "backups" / f"midpoint-session-health-{stamp}"
    copied: list[Path] = []
    try:
        for relative in FILES:
            source = BUNDLE / relative
            target = ROOT / relative
            if not source.exists():
                raise FileNotFoundError(source)
            if target.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative)
        python = ROOT / ".venv" / "bin" / "python"
        python_command = str(python if python.exists() else Path(sys.executable))
        run(
            [
                python_command,
                "-m",
                "pytest",
                "-q",
                "tests/test_diagnose_midpoint_session_health.py",
                "tests/test_midpoint_t5_live_shadow_candidates.py",
            ]
        )
        run(
            [
                python_command,
                "-m",
                "py_compile",
                "scripts/diagnose_midpoint_session_health.py",
            ]
        )
        run(["git", "diff", "--check"])
    except Exception:
        for relative in reversed(copied):
            target = ROOT / relative
            saved = backup / relative
            if saved.exists():
                shutil.copy2(saved, target)
            elif target.exists():
                target.unlink()
        print("STOP: validation failed; installed files restored.", file=sys.stderr)
        raise
    print("PASS: read-only Midpoint session health diagnostic installed.")
    print("No service restart is required.")
    print("No live audit, configuration, entry, exit, order or quantity changed.")
    if backup.exists():
        print("Backup:", backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
