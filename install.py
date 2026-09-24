#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

FILES = [
    Path("backend/market_lab/historical_option_ohlc_sidecar.py"),
    Path("tests/test_historical_option_ohlc_sidecar.py"),
]

def main():
    ap = argparse.ArgumentParser(description="Install source-aware historical option sidecar fix v1")
    ap.add_argument("--repo", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    root = Path(__file__).resolve().parent

    required = [
        repo/"backend/market_lab/historical_option_ohlc_sidecar.py",
        repo/"backend/market_lab/gateways.py",
        repo/"backend/market_lab/historical.py",
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
    print("  - expired expiries use historical_option_contracts + historical_option_candles")
    print("  - active/current expiries use active_option_contracts + active_option_historical_candles")
    print("  - zero-contract or zero-row sessions become UNAVAILABLE with explicit issue")
    print("  - no date/strike/contract fallback")
    print("  - strategy/coordinator/PE lifecycle unchanged")
    print("  - no API/worker restart required")
    if a.check:
        print("CHECK PASS")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = repo/".historical-option-sidecar-active-expiry-fix-v1-backup"/stamp
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
