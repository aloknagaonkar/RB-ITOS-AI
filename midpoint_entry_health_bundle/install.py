#!/usr/bin/env python3
"""Install and validate the research-only Midpoint entry-health study."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).resolve().parent / "files"
FILES = (
    Path("scripts/research_midpoint_entry_health_v1.py"),
    Path("tests/test_research_midpoint_entry_health_v1.py"),
)


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "data" / "backups" / f"midpoint-entry-health-{stamp}"
    copied = []
    try:
        for relative in FILES:
            source, target = BUNDLE / relative, ROOT / relative
            if not source.exists():
                raise FileNotFoundError(source)
            if target.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative)
        python = str(ROOT / ".venv" / "bin" / "python")
        if not Path(python).exists():
            python = sys.executable
        run([python, "-m", "pytest", "-q", "tests/test_research_midpoint_entry_health_v1.py"])
        run([python, "-m", "py_compile", "scripts/research_midpoint_entry_health_v1.py"])
        run(["git", "diff", "--check"])
    except Exception:
        for relative in reversed(copied):
            target, saved = ROOT / relative, backup / relative
            if saved.exists():
                shutil.copy2(saved, target)
            elif target.exists():
                target.unlink()
        print("STOP: validation failed; installed files restored.", file=sys.stderr)
        raise
    print("PASS: installed MIDPOINT_ENTRY_HEALTH_V1 research files.")
    if backup.exists():
        print("Backup:", backup)
    print("No live gate, service, audit, entry, exit, order, paper order or quantity changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
