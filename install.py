#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import argparse
import shutil


FILES = [
    "backend/market_lab/hilega_current_day_directional_recovery_v1.py",
    "backend/market_lab/hilega_current_day_directional_recovery_cli_v1.py",
    "tests/test_hilega_current_day_directional_recovery_v1.py",
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = p.parse_args()

    repo = Path(a.repo).resolve()
    payload = Path(__file__).resolve().parent / "files"

    required = [
        repo / "backend/market_lab/hilega_directional_coordinator_v1.py",
        repo / "backend/market_lab/hilega_directional_historical_replay_v1.py",
        repo / "backend/market_lab/hilega_milega_historical_replay_v1.py",
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"BLOCKED: required source missing: {path}")

    print("READY")
    print("  - adds Phase 6.3 current-day directional recovery core")
    print("  - source is recorded UNDERLYING_5M_BUILD evidence only")
    print("  - same HilegaDirectionalCoordinatorV1 is replayed")
    print("  - warmup is cache-only; no broker historical fallback")
    print("  - recovered rows are written to normal directional replay path")
    print("  - no strategy rules, UI, options or execution behavior changed")
    if a.check:
        print("CHECK PASS")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = repo / ".hilega-current-day-directional-recovery-phase6-3a-backup" / stamp

    for rel in FILES:
        src = payload / rel
        dst = repo / rel
        if dst.exists():
            backup = backup_root / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    print("APPLY PASS")
    print("Backup root:", backup_root)
    print("Next:")
    print("  PYTHONPATH=backend python -m pytest tests/test_hilega_current_day_directional_recovery_v1.py -q")
    print("Then recover Sep 24 with the CLI.")
    print("No API or Hilega worker restart is required for recovery generation.")


if __name__ == "__main__":
    main()
