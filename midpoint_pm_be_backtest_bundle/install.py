#!/usr/bin/env python3
"""Install and validate the research-only PM B/E historical backtest."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


FILES = (
    "scripts/backtest_midpoint_pm_be.py",
    "tests/test_backtest_midpoint_pm_be.py",
)


def run(command: list[str], *, cwd: Path) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    bundle = Path(__file__).resolve().parent
    root = bundle.parent
    payload = bundle / "files"
    expected = root / "backend" / "market_lab" / "midpoint_strategy"
    if not expected.is_dir():
        raise SystemExit(
            "STOP: copy the bundle into the RB-ITOS-AI repository root first"
        )
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if branch != "feature/pcr-foundation":
        raise SystemExit(
            f"STOP: expected feature/pcr-foundation, current branch is {branch!r}"
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = root / "data" / "backups" / f"midpoint-pm-be-backtest-{stamp}"
    copied = 0
    for relative in FILES:
        source = payload / relative
        target = root / relative
        if not source.is_file():
            raise SystemExit(f"STOP: bundle payload missing: {relative}")
        if target.exists():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1

    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_backtest_midpoint_pm_be.py",
            "tests/test_midpoint_extended_entry_candidates.py",
            "tests/test_midpoint_c_pm_e_live_shadow.py",
        ],
        cwd=root,
    )
    run(
        [
            sys.executable,
            "-m",
            "py_compile",
            "scripts/backtest_midpoint_pm_be.py",
        ],
        cwd=root,
    )
    run(["git", "diff", "--check"], cwd=root)
    print(f"PASS: installed {copied} research-only files.")
    if backup.exists():
        print(f"Backup: {backup}")
    print("No live gate, service, audit, order, paper order or quantity changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
