#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).resolve().parent
RELATIVE = (
    "backend/market_lab/hilega_wma_gap_historical_v1.py",
    "backend/market_lab/hilega_historical_ui_api_v1.py",
    "frontend/src/hilegaDecisionTable.tsx",
    "frontend/src/hilegaHistoricalReplay.tsx",
    "frontend/src/hilegaHistoricalReplay.css",
    "tests/test_hilega_wma_gap_historical_v1.py",
)


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    backup = ROOT / "data/backups" / (
        "hilega-wma-gap-historical-ui-" +
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    installed: list[Path] = []
    try:
        for name in RELATIVE:
            source = BUNDLE / "files" / name
            destination = ROOT / name
            if not source.is_file():
                raise FileNotFoundError(source)
            if destination.exists():
                saved = backup / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            installed.append(destination)

        python = ROOT / ".venv/bin/python"
        run([str(python), "-m", "pytest", "-q",
             "tests/test_hilega_wma_gap_historical_v1.py",
             "tests/test_hilega_historical_ui_api_v1.py",
             "tests/test_hilega_same_page_historical_replay.py"])
        run([str(python), "-m", "py_compile",
             "backend/market_lab/hilega_wma_gap_historical_v1.py",
             "backend/market_lab/hilega_historical_ui_api_v1.py"])
        run(["npm", "--prefix", "frontend", "run", "build"])
        run(["git", "diff", "--check"])
    except Exception as exc:
        for destination in installed:
            saved = backup / destination.relative_to(ROOT)
            if saved.exists():
                shutil.copy2(saved, destination)
            elif destination.exists():
                destination.unlink()
        print(f"STOP: validation failed; installed source restored: {exc}")
        return 1

    print("PASS: WMA-gap Historical Replay and daily metrics installed.")
    if backup.exists():
        print("Backup:", backup)
    print("Restart is required. Live strategy, audit, orders and quantity unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
