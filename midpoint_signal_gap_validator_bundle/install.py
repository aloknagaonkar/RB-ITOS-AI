#!/usr/bin/env python3
"""Install and validate the Midpoint live signal-gap validator."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(__file__).resolve().parent
FILES = (
    "scripts/validate_midpoint_signal_gap.py",
    "tests/test_validate_midpoint_signal_gap.py",
)


def main() -> int:
    backup = ROOT / "data" / "backups" / (
        "midpoint-signal-gap-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    changed = []
    for relative in FILES:
        # The source files are committed at their final repository paths.  The
        # installer remains a one-command validation entry point and preserves
        # any differing local copies before confirming them.
        source = ROOT / relative
        target = ROOT / relative
        if not source.exists():
            raise SystemExit(f"STOP: bundle file missing: {source}")
        if source.resolve() == target.resolve():
            continue
        if target.exists() and target.read_bytes() != source.read_bytes():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != source.read_bytes():
            shutil.copy2(source, target)
            changed.append(relative)

    commands = (
        [sys.executable, "-m", "pytest", "-q", "tests/test_validate_midpoint_signal_gap.py"],
        [sys.executable, "-m", "py_compile", "scripts/validate_midpoint_signal_gap.py"],
        ["git", "diff", "--check"],
    )
    for command in commands:
        print("Running:", " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)
    print("PASS: installed Midpoint live signal-gap validator.")
    if backup.exists():
        print("Backup:", backup)
    print("Files:", ", ".join(FILES))
    print("No service, live audit, gate, entry, exit, order or quantity changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
