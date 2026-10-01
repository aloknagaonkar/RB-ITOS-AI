#!/usr/bin/env python3
"""Install deterministic chronological Midpoint option-tape selection."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = Path(__file__).resolve().parent / "files"
FILES = (
    Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py"),
    Path("backend/market_lab/midpoint_strategy/materialize_option_observation.py"),
    Path("tests/test_midpoint_option_tape_order.py"),
)


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "data/backups" / f"midpoint-option-tape-order-{stamp}"
    copied: list[Path] = []
    try:
        for relative in FILES:
            source, target = PAYLOAD / relative, ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            if target.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative)
        python = ROOT / ".venv/bin/python"
        subprocess.run([
            str(python), "-m", "pytest", "-q",
            "tests/test_midpoint_option_tape_order.py",
            "tests/test_midpoint_m25b_option_observation.py",
            "tests/test_midpoint_m3_live_shadow_ui.py",
        ], cwd=ROOT, check=True)
        subprocess.run([
            str(python), "-m", "py_compile",
            "backend/market_lab/midpoint_strategy/live_shadow_ui.py",
            "backend/market_lab/midpoint_strategy/materialize_option_observation.py",
        ], cwd=ROOT, check=True)
        subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
    except Exception:
        for relative in reversed(copied):
            target, saved = ROOT / relative, backup / relative
            if saved.exists():
                shutil.copy2(saved, target)
            elif target.exists():
                target.unlink()
        print("STOP: validation failed; source restored; services untouched")
        raise
    print("PASS: chronological option-tape selection installed.")
    print("Existing tape data was not changed. API and workers were not restarted.")
    print("Backup:", backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
