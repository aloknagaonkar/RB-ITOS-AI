#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import argparse, shutil

FILES = [
    "backend/market_lab/hilega_current_day_directional_recovery_v1.py",
    "backend/market_lab/hilega_current_day_directional_recovery_cli_v1.py",
    "tests/test_hilega_current_day_directional_recovery_v1.py",
]


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a=p.parse_args()

    repo=Path(a.repo).resolve()
    payload=Path(__file__).resolve().parent/"files"

    required=[
        repo/"backend/market_lab/hilega_current_day_directional_recovery_v1.py",
        repo/"backend/market_lab/hilega_current_day_directional_recovery_cli_v1.py",
        repo/"backend/market_lab/hilega_directional_coordinator_v1.py",
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"BLOCKED: required source missing: {path}")

    print("READY")
    print("  - Phase 6.3A2 supplements old 5m audit with recorded directional market evidence")
    print("  - accepts only exact target-session Nifty 1m candles")
    print("  - aggregates exact 1m -> 5m using existing aggregate_exact_5m")
    print("  - duplicate 1m or overlapping 5m conflicts fail closed")
    print("  - same HilegaDirectionalCoordinatorV1 remains the decision authority")
    print("  - no strategy/UI/option/execution rule changes")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root=repo/".hilega-current-day-directional-recovery-phase6-3a2-backup"/stamp
    for rel in FILES:
        src=payload/rel
        dst=repo/rel
        if dst.exists():
            backup=backup_root/rel
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dst,backup)
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)

    print("APPLY PASS")
    print("Backup root:", backup_root)
    print("Run focused tests, then recover 2026-09-24 with --force.")
    print("No API or Hilega worker restart is required.")


if __name__=="__main__":
    main()
