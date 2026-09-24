#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

FILES = [
    Path("backend/market_lab/hilega_directional_coordinator_v1.py"),
    Path("tests/test_hilega_directional_coordinator_v1.py"),
    Path("docs/strategies/HILEGA_DIRECTIONAL_MASTER_CHECKLIST_V1.md"),
]

def main():
    ap = argparse.ArgumentParser(description="Install isolated Hilega Directional Coordinator v1")
    ap.add_argument("--repo", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    root = Path(__file__).resolve().parent

    required = [
        repo/"backend/market_lab/hilega_milega_strategy_v1.py",
        repo/"backend/market_lab/hilega_milega_bearish_strategy_v1.py",
    ]
    missing = [str(x) for x in required if not x.is_file()]
    if missing:
        print("BLOCKED: required strategy modules missing:")
        for x in missing:
            print(" ", x)
        raise SystemExit(2)

    for rel in FILES:
        if not (root/"files"/rel).is_file():
            print("BLOCKED: patch payload missing:", rel)
            raise SystemExit(2)

    print("READY")
    print("  - adds isolated HilegaDirectionalCoordinatorV1")
    print("  - keeps bullish and bearish strategy rules unchanged")
    print("  - ACTIVE owner exclusive")
    print("  - opposite ARMED remains informational")
    print("  - blocks opposite entry while owner ACTIVE")
    print("  - blocks same-candle reversal")
    print("  - allows preserved ARMED to continue next completed candle")
    print("  - DOES NOT wire into live worker/API/UI")
    print("  - no restart required")
    if a.check:
        print("CHECK PASS")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = repo/".hilega-directional-coordinator-v1-backup"/stamp
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
