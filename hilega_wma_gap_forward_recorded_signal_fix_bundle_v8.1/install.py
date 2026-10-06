#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(__file__).resolve().parent
FILES = (
    "scripts/hilega_wma_gap_forward_publisher.py",
    "frontend/src/hilegaHistoricalReplay.tsx",
    "tests/test_hilega_wma_gap_forward_publisher.py",
)


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    python = ROOT / ".venv/bin/python"
    if not python.is_file():
        raise SystemExit("STOP: activate/create the repository .venv first")
    backup = ROOT / "data/backups" / (
        "hilega-forward-recorded-signal-v8-" +
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    copied: list[Path] = []
    try:
        for relative in FILES:
            source = BUNDLE / "files" / relative
            target = ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            if target.is_file():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target)
        run([str(python), "-m", "pytest", "-q",
             "tests/test_hilega_wma_gap_forward_publisher.py",
             "tests/test_hilega_wma_gap_historical_v1.py",
             "tests/test_hilega_historical_ui_api_v1.py",
             "tests/test_backtest_hilega_wma_gap_490.py"])
        run([str(python), "-m", "py_compile",
             "scripts/hilega_wma_gap_forward_publisher.py"])
        run(["npm", "--prefix", "frontend", "run", "build"])
        run(["git", "diff", "--check"])
    except Exception as exc:
        for target in copied:
            relative = target.relative_to(ROOT)
            saved = backup / relative
            if saved.is_file():
                shutil.copy2(saved, target)
        raise SystemExit(f"STOP: validation failed; installed source restored: {exc}")
    print("PASS: recorded-live forward signals and V1/V2 audit UI installed.")
    print("Run the explicit --rebuild-date command from README.txt.")
    print("Live strategy, orders, quantity and frozen 490 sessions were untouched.")
    print("Backup:", backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
