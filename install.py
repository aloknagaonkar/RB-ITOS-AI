#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

FILES = [
    Path("backend/market_lab/hilega_milega_bearish_strategy_v1.py"),
    Path("backend/market_lab/hilega_milega_bearish_historical_replay_v1.py"),
    Path("backend/market_lab/hilega_milega_bearish_historical_replay_cli_v1.py"),
    Path("tests/test_hilega_milega_bearish_strategy_v1.py"),
    Path("tests/test_hilega_milega_bearish_historical_replay_v1.py"),
    Path("docs/strategies/HILEGA_DIRECTIONAL_MASTER_CHECKLIST_V1.md"),
]

def main():
    ap=argparse.ArgumentParser(description="Install Hilega bearish Phase B3 historical replay")
    ap.add_argument("--repo",required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=ap.parse_args()

    repo=Path(a.repo).resolve()
    root=Path(__file__).resolve().parent

    bullish=repo/"backend/market_lab/hilega_milega_historical_replay_v1.py"
    if not bullish.is_file():
        print("BLOCKED: bullish historical replay baseline is missing.")
        raise SystemExit(2)

    for rel in FILES:
        if not (root/"files"/rel).is_file():
            print("BLOCKED: payload missing:",rel)
            raise SystemExit(2)

    print("READY")
    print("  - keeps bullish strategy/replay unchanged")
    print("  - adds separate bearish historical replay + CLI")
    print("  - reuses exact 1m cache and exact 5m aggregation")
    print("  - writes append-only bearish step audit per session")
    print("  - writes bearish trades / signal decisions / candle-by-candle audit")
    print("  - writes bearish-manual-validation.txt for human review")
    print("  - rules remain CANDIDATE_MIRROR_UNDER_VALIDATION")
    print("  - no PE option lifecycle and no live integration yet")
    if a.check:
        print("CHECK PASS"); return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root=repo/".hilega-bearish-b3-backup"/stamp
    for rel in FILES:
        src=root/"files"/rel
        dst=repo/rel
        if dst.exists():
            b=backup_root/rel
            b.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dst,b)
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)

    print("APPLY PASS")
    print("Backup root:",backup_root)
    print("No API/worker restart required; this phase is historical/research only.")

if __name__=="__main__":
    main()
