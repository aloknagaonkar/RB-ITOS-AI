#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

FILES = {
    Path("backend/market_lab/hilega_milega_bearish_strategy_v1.py"):
        Path("files/backend/market_lab/hilega_milega_bearish_strategy_v1.py"),
    Path("tests/test_hilega_milega_bearish_strategy_v1.py"):
        Path("files/tests/test_hilega_milega_bearish_strategy_v1.py"),
    Path("docs/strategies/HILEGA_DIRECTIONAL_MASTER_CHECKLIST_V1.md"):
        Path("files/docs/strategies/HILEGA_DIRECTIONAL_MASTER_CHECKLIST_V1.md"),
}

def main():
    ap = argparse.ArgumentParser(description="Install Hilega bearish Phase B1/B2")
    ap.add_argument("--repo", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    patch_root = Path(__file__).resolve().parent

    bullish = repo/"backend/market_lab/hilega_milega_strategy_v1.py"
    if not bullish.is_file():
        print("BLOCKED: current bullish strategy source is missing.")
        raise SystemExit(2)

    expected_markers = [
        "class HilegaMilegaBullishEngineV1",
        'STRATEGY_ID = "HILEGA_MILEGA_BULLISH_SHADOW_V1"',
        "class HilegaMilegaIndicatorEngineV1",
    ]
    text = bullish.read_text(encoding="utf-8")
    missing = [x for x in expected_markers if x not in text]
    if missing:
        print("BLOCKED: bullish baseline does not match expected architecture:", missing)
        raise SystemExit(2)

    for dest, src_rel in FILES.items():
        src = patch_root/src_rel
        if not src.is_file():
            print("BLOCKED: patch payload missing:", src_rel)
            raise SystemExit(2)

    print("READY")
    print("  - adds separate HilegaMilegaBearishEngineV1")
    print("  - reuses canonical RSI9/EMA3/WMA21 indicator engine")
    print("  - adds mirrored bearish Opening / Route A / Route B / exit / cutoff candidate rules")
    print("  - adds bearish unit/audit tests")
    print("  - adds updated directional master checklist")
    print("  - DOES NOT modify the working bullish engine")
    print("  - DOES NOT add live PE trading/shadow integration yet")
    print("  - execution remains disabled")
    if a.check:
        print("CHECK PASS")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = repo/".hilega-bearish-b1-b2-backup"/stamp

    for dest, src_rel in FILES.items():
        target = repo/dest
        src = patch_root/src_rel
        if target.exists():
            backup = backup_root/dest
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    print("APPLY PASS")
    print("Backup root:", backup_root)
    print("Run the bearish + bullish strategy tests before any replay integration.")

if __name__ == "__main__":
    main()
