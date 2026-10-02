#!/usr/bin/env python3
"""Install the research-only DHANUSH 480-session scanner."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parent
PAYLOAD = BUNDLE / "files"
TARGETS = (
    "scripts/midpoint_dhanush_historical_scan.py",
    "tests/test_midpoint_dhanush_research.py",
)


def restore(backup: Path, existed: dict[str, bool]) -> None:
    for relative in TARGETS:
        target = ROOT / relative
        saved = backup / relative
        if existed[relative]:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, target)
        elif target.exists():
            target.unlink()


def main() -> int:
    if not (ROOT / "pyproject.toml").exists():
        raise SystemExit(f"STOP: bundle must be inside repository root: {ROOT}")
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=ROOT, check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    if branch != "feature/pcr-foundation":
        raise SystemExit(
            f"STOP: expected feature/pcr-foundation, found {branch!r}"
        )
    python = ROOT / ".venv/bin/python"
    if not python.exists():
        raise SystemExit(f"STOP: virtualenv Python unavailable: {python}")
    for relative in TARGETS:
        if not (PAYLOAD / relative).is_file():
            raise SystemExit(f"STOP: missing payload: {relative}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "data/backups" / f"midpoint-dhanush-research-{stamp}"
    existed = {}
    for relative in TARGETS:
        source = ROOT / relative
        existed[relative] = source.is_file()
        if source.is_file():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, saved)
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "manifest.json").write_text(
        json.dumps({"branch": branch, "files_existed": existed}, indent=2) + "\n"
    )

    try:
        for relative in TARGETS:
            target = ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PAYLOAD / relative, target)
        subprocess.run(
            [str(python), "-m", "pytest", "-q", TARGETS[1]],
            cwd=ROOT, check=True,
        )
        subprocess.run(
            [str(python), "-m", "py_compile", TARGETS[0]],
            cwd=ROOT, check=True,
        )
        subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
    except (subprocess.CalledProcessError, OSError) as error:
        restore(backup, existed)
        print(f"STOP: validation failed ({error}); source restored")
        return 1

    print("PASS: DHANUSH research scanner installed and validated.")
    print("No API, worker, live audit, configuration, order or quantity changed.")
    print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
