#!/usr/bin/env python3
"""Install research-only Hilega RSI extreme-zone reversal exits."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).resolve().parent
FILES = {
    BUNDLE / "files/scripts/research_hilega_rsi_extreme_reversal_exits.py":
        ROOT / "scripts/research_hilega_rsi_extreme_reversal_exits.py",
    BUNDLE / "files/tests/test_research_hilega_rsi_extreme_reversal_exits.py":
        ROOT / "tests/test_research_hilega_rsi_extreme_reversal_exits.py",
}


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    prerequisites = [
        ROOT / "scripts/research_hilega_post_proof_mfe_exits.py",
        ROOT / "scripts/research_hilega_rsi14_extreme_exits.py",
        ROOT / "data/historical-evidence/hilega-wma-gap-capture-failures-490-v1/capture-trade-view.csv",
        ROOT / "data/historical-evidence/hilega-milega-underlying-cache-v1",
    ]
    missing = [path for path in prerequisites if not path.exists()]
    if missing:
        print("STOP: missing prerequisite(s):")
        for path in missing:
            print(" ", path.relative_to(ROOT))
        return 1
    backup = ROOT / "data/backups" / (
        "hilega-rsi-extreme-reversal-exit-"
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
            "tests/test_research_hilega_rsi_extreme_reversal_exits.py",
            "tests/test_research_hilega_rsi14_extreme_exits.py",
            "tests/test_research_hilega_post_proof_mfe_exits.py",
        ])
        run([
            str(python), "-m", "py_compile",
            "scripts/research_hilega_rsi_extreme_reversal_exits.py",
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
    print("PASS: installed Hilega RSI extreme-zone reversal-exit research.")
    if backup.exists():
        print("Backup:", backup)
    print("No live strategy, service, audit, order, paper order or quantity changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
