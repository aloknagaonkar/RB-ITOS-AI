#!/usr/bin/env python3
"""Copy the full current-strategy backtest into the repository."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent
RELATIVE = Path("scripts/backtest_midpoint_current_strategy.py")
SOURCE = BUNDLE / "files" / RELATIVE
TARGET = ROOT / RELATIVE


def main() -> int:
    if not (ROOT / "pyproject.toml").exists():
        raise SystemExit(f"STOP: place this bundle directly inside repository: {ROOT}")
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=ROOT, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    if branch != "feature/pcr-foundation":
        raise SystemExit(
            f"STOP: expected feature/pcr-foundation, found {branch!r}"
        )
    if not SOURCE.is_file():
        raise SystemExit(f"STOP: payload missing: {SOURCE}")
    python = ROOT / ".venv/bin/python"
    if not python.exists():
        raise SystemExit(f"STOP: virtualenv Python missing: {python}")

    if TARGET.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = (
            ROOT / "data/backups" / f"midpoint-current-backtest-{stamp}" /
            RELATIVE
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TARGET, backup)
        print(f"Backup: {backup}")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, TARGET)
    subprocess.run(
        [str(python), "-m", "py_compile", str(RELATIVE)],
        cwd=ROOT,
        check=True,
    )
    print(f"PASS: installed {RELATIVE}")
    print("No service, live audit, configuration, order or quantity changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
