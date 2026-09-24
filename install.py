#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

FILES = [
    Path("backend/market_lab/hilega_milega_pe_option_candidate_v1.py"),
    Path("backend/market_lab/hilega_milega_pe_option_shadow_lifecycle_v1.py"),
    Path("backend/market_lab/hilega_directional_pe_historical_shadow_v1.py"),
    Path("backend/market_lab/hilega_directional_pe_historical_shadow_cli_v1.py"),
    Path("tests/test_hilega_directional_pe_historical_shadow_v1.py"),
    Path("docs/strategies/HILEGA_DIRECTIONAL_MASTER_CHECKLIST_V1.md"),
]

def main():
    ap = argparse.ArgumentParser(description="Install Hilega PE ATM±2 historical shadow v1")
    ap.add_argument("--repo", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    root = Path(__file__).resolve().parent

    required = [
        repo/"backend/market_lab/hilega_directional_historical_replay_v1.py",
        repo/"backend/market_lab/historical_option_ohlc_adapter_v1.py",
        repo/"backend/market_lab/live_option_minute_source_v1.py",
    ]
    missing = [str(x) for x in required if not x.is_file()]
    if missing:
        print("BLOCKED: required baseline files missing:")
        for x in missing:
            print(" ", x)
        raise SystemExit(2)

    for rel in FILES:
        if not (root/"files"/rel).is_file():
            print("BLOCKED: patch payload missing:", rel)
            raise SystemExit(2)

    print("READY")
    print("  - adds bearish PE ATM-2..ATM+2 candidate builder")
    print("  - tracks all 5 PE legs independently")
    print("  - exact 1m OPEN at causal entry boundary")
    print("  - exact 1m OPEN at causal exit boundary")
    print("  - MFE/MAE + points/% per leg")
    print("  - no nearest-strike/minute fallback")
    print("  - no single PE selection")
    print("  - no quantity / rupee P&L / execution / paper order")
    print("  - uses historical option OHLC cache only")
    print("  - missing exact data stays UNAVAILABLE/INCOMPLETE")
    print("  - no live worker/API/UI integration")
    print("  - no restart required")
    if a.check:
        print("CHECK PASS")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = repo/".hilega-pe-atm2-historical-shadow-v1-backup"/stamp
    for rel in FILES:
        src = root/"files"/rel
        dst = repo/rel
        if dst.exists():
            b = backup_root/rel
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, b)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    print("APPLY PASS")
    print("Backup root:", backup_root)
    print("No API/worker restart required.")

if __name__ == "__main__":
    main()
