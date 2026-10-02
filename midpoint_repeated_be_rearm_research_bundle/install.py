#!/usr/bin/env python3
"""Install the repeated B/E rearm research replay."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent
FILES = (
    Path("scripts/backtest_midpoint_repeated_be_rearm.py"),
    Path("docs/MIDPOINT_INITIAL_RISK_RESEARCH_CHECKLIST.md"),
)


def main() -> int:
    if not (ROOT / "pyproject.toml").exists():
        raise SystemExit(f"STOP: place bundle directly inside repository: {ROOT}")
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=ROOT, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    if branch != "feature/pcr-foundation":
        raise SystemExit(f"STOP: expected feature/pcr-foundation, found {branch!r}")
    python = ROOT / ".venv/bin/python"
    if not python.exists():
        raise SystemExit(f"STOP: virtualenv Python missing: {python}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = ROOT / "data/backups" / f"midpoint-repeated-be-rearm-{stamp}"
    for relative in FILES:
        source = BUNDLE / "files" / relative
        target = ROOT / relative
        if not source.is_file():
            raise SystemExit(f"STOP: payload missing: {source}")
        if target.exists():
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    subprocess.run(
        [python, "-m", "py_compile", str(FILES[0])], cwd=ROOT, check=True
    )
    subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
    print("PASS: installed repeated B/E rearm research replay.")
    if backup_root.exists():
        print(f"Backup: {backup_root}")
    print("Live coordinator, configuration, services, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
