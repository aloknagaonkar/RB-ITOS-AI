#!/usr/bin/env python3
"""Install causal pre-entry health observation and historical reporting."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(__file__).resolve().parent / "files"
FILES = (
    Path("backend/market_lab/midpoint_strategy/entry_health_live_v1.py"),
    Path("backend/market_lab/midpoint_strategy/config.py"),
    Path("backend/market_lab/midpoint_strategy/workspace_contract.py"),
    Path("backend/market_lab/midpoint_strategy/live_shadow_v1.py"),
    Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py"),
    Path("scripts/research_midpoint_entry_health_v1.py"),
    Path("scripts/report_midpoint_preentry_health_outcomes.py"),
    Path("tests/test_midpoint_t5_live_shadow_candidates.py"),
)


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "data/backups" / f"midpoint-preentry-health-{stamp}"
    copied: list[Path] = []
    try:
        for relative in FILES:
            source, target = BUNDLE / relative, ROOT / relative
            if not source.exists():
                raise FileNotFoundError(source)
            if target.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative)
        python = ROOT / ".venv/bin/python"
        executable = str(python if python.exists() else Path(sys.executable))
        run([executable, "-m", "pytest", "-q",
             "tests/test_midpoint_t5_live_shadow_candidates.py",
             "tests/test_midpoint_m3b_live_shadow_v1.py",
             "tests/test_midpoint_normal_b_proved_live_shadow.py",
             "tests/test_storage_api.py"])
        run([executable, "-m", "py_compile",
             "backend/market_lab/midpoint_strategy/entry_health_live_v1.py",
             "backend/market_lab/midpoint_strategy/live_shadow_v1.py",
             "scripts/research_midpoint_entry_health_v1.py",
             "scripts/report_midpoint_preentry_health_outcomes.py"])
        run(["git", "diff", "--check"])
    except Exception:
        for relative in reversed(copied):
            target, saved = ROOT / relative, backup / relative
            if saved.exists():
                shutil.copy2(saved, target)
            elif target.exists():
                target.unlink()
        print("STOP: validation failed; installed files restored.", file=sys.stderr)
        raise
    print("PASS: pre-entry health observation installed and validated.")
    print("Live events: PRE_ENTRY_HEALTH_SNAPSHOT and ENTRY_HEALTH_SNAPSHOT.")
    print("No entry veto, authoritative exit, order or quantity was added.")
    print("API and workers were not restarted.")
    if backup.exists():
        print("Backup:", backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
