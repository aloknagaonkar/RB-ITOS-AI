#!/usr/bin/env python3
"""Install the research-only Hilega clear loss diagnostic."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).resolve().parent
FILES = {
    BUNDLE / "files/scripts/analyze_hilega_wma_gap_clear_losses.py":
        ROOT / "scripts/analyze_hilega_wma_gap_clear_losses.py",
    BUNDLE / "files/tests/test_analyze_hilega_wma_gap_clear_losses.py":
        ROOT / "tests/test_analyze_hilega_wma_gap_clear_losses.py",
}


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    required = (
        ROOT / "scripts/backtest_hilega_wma_gap_490.py",
        ROOT / "scripts/research_hilega_wma_gap_confirmation_policies.py",
        ROOT / "scripts/validate_hilega_wma_delayed_confirmation.py",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        print("STOP: install prerequisite bundles first:", ", ".join(missing))
        return 1

    backup = ROOT / "data/backups" / (
        "hilega-wma-gap-clear-loss-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    installed: list[Path] = []
    try:
        for source, destination in FILES.items():
            if destination.exists():
                saved = backup / destination.relative_to(ROOT)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            installed.append(destination)
        python = ROOT / ".venv/bin/python"
        run([
            str(python), "-m", "pytest", "-q",
            "tests/test_analyze_hilega_wma_gap_clear_losses.py",
            "tests/test_research_hilega_wma_gap_confirmation_policies.py",
            "tests/test_backtest_hilega_wma_gap_490.py",
        ])
        run([
            str(python), "-m", "py_compile",
            "scripts/analyze_hilega_wma_gap_clear_losses.py",
        ])
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

    print("PASS: installed Hilega clear WMA-gap loss diagnostic.")
    if backup.exists():
        print("Backup:", backup)
    print("No live strategy, service, audit, order, paper order or quantity changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
