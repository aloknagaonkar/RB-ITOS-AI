#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(__file__).resolve().parent
FILES = (
    "backend/market_lab/hilega_wma_gap_historical_v1.py",
    "scripts/research_hilega_wma_gap_first_touch.py",
    "tests/test_hilega_wma_gap_historical_v1.py",
    "tests/test_research_hilega_wma_gap_first_touch.py",
)


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    python = ROOT / ".venv/bin/python"
    if not python.is_file():
        raise SystemExit("STOP: activate/create the repository .venv first")
    backup = ROOT / "data/backups" / (
        "hilega-wma-gap-first-touch-" +
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    copied: list[tuple[Path, bool]] = []
    try:
        for relative in FILES:
            source = BUNDLE / "files" / relative
            target = ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            existed = target.is_file()
            if existed:
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append((target, existed))
        run([str(python), "-m", "pytest", "-q",
             "tests/test_research_hilega_wma_gap_first_touch.py",
             "tests/test_hilega_wma_gap_historical_v1.py",
             "tests/test_hilega_historical_ui_api_v1.py",
             "tests/test_backtest_hilega_wma_gap_490.py"])
        run([str(python), "-m", "py_compile",
             "backend/market_lab/hilega_wma_gap_historical_v1.py",
             "scripts/research_hilega_wma_gap_first_touch.py"])
        run(["git", "diff", "--check"])
    except Exception as exc:
        for target, existed in copied:
            relative = target.relative_to(ROOT)
            saved = backup / relative
            if existed and saved.is_file():
                shutil.copy2(saved, target)
            elif not existed and target.is_file():
                target.unlink()
        raise SystemExit(f"STOP: validation failed; installed source restored: {exc}")
    print("PASS: causal first-touch WMA-gap research installed.")
    print("Live Hilega rules, orders, quantity, exits and frozen evidence unchanged.")
    print("Backup:", backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
