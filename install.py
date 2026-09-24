#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime, timezone
import argparse, shutil

FILES = [
    Path("backend/market_lab/hilega_directional_coordinator_v1.py"),
    Path("backend/market_lab/hilega_directional_live_shadow_v1.py"),
    Path("backend/market_lab/live_shadow_worker_v1.py"),
    Path("tests/test_hilega_directional_live_shadow_v1.py"),
    Path("docs/strategies/HILEGA_DIRECTIONAL_LIVE_SHADOW_V1.md"),
]

REQUIRED = [
    Path("backend/market_lab/hilega_milega_strategy_v1.py"),
    Path("backend/market_lab/hilega_milega_bearish_strategy_v1.py"),
    Path("backend/market_lab/hilega_milega_option_shadow_lifecycle_v1.py"),
    Path("backend/market_lab/hilega_milega_pe_option_shadow_lifecycle_v1.py"),
    Path("backend/market_lab/hilega_milega_option_candidate_v1.py"),
    Path("backend/market_lab/hilega_milega_pe_option_candidate_v1.py"),
]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a=ap.parse_args()
    repo=Path(a.repo).resolve(); root=Path(__file__).resolve().parent
    missing=[str(repo/x) for x in REQUIRED if not (repo/x).is_file()]
    if missing:
        print("BLOCKED: required baseline files missing")
        for x in missing: print("  -",x)
        raise SystemExit(2)
    payload_missing=[str(root/'files'/x) for x in FILES if not (root/'files'/x).is_file()]
    if payload_missing:
        print("BLOCKED: patch payload incomplete")
        for x in payload_missing: print("  -",x)
        raise SystemExit(2)
    print("READY")
    print("  - adds isolated HILEGA_DIRECTIONAL_SHADOW_V1 live coordinator")
    print("  - frozen bullish rules unchanged")
    print("  - bearish candidate rules unchanged")
    print("  - exclusive directional owner; opposite ARMED may coexist")
    print("  - accepted bullish entry -> CE ATM±2 shadow")
    print("  - accepted bearish entry -> PE ATM±2 shadow")
    print("  - suppressed entries never start option shadow")
    print("  - no same-candle reversal")
    print("  - exact 14:55 directional cutoff coordination")
    print("  - observation only; no selector/quantity/orders/rupee P&L")
    print("  - existing bullish live strategy remains selectable and untouched")
    print("  - installation itself requires no restart")
    print("  - activation requires intentional Hilega live-shadow worker restart")
    if a.check:
        print("CHECK PASS"); return
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/'.hilega-directional-live-shadow-v1-backup'/stamp
    for rel in FILES:
        src=root/'files'/rel; dst=repo/rel
        if dst.exists():
            b=backup/rel; b.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(dst,b)
        dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    print("APPLY PASS")
    print("Backup root:", backup)
    print("No API/main-worker restart required.")
    print("Do not restart the Hilega live-shadow worker until intentionally activating the new selector.")

if __name__ == '__main__': main()
