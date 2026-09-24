#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

REL = Path("frontend/src/hilegaMilegaShadow.tsx")

def main():
    ap=argparse.ArgumentParser(description="Adjust Phase 6 directional support into existing Hilega UI")
    ap.add_argument("--repo", required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    args=ap.parse_args()

    repo=Path(args.repo).resolve()
    root=Path(__file__).resolve().parent
    src=root/"files"/REL
    dst=repo/REL

    if not dst.is_file():
        raise SystemExit("BLOCKED: existing Hilega frontend file not found")
    if not src.is_file():
        raise SystemExit("BLOCKED: patch payload missing")

    print("READY")
    print("  - preserves existing Hilega page layout and styling")
    print("  - adds directional owner + bullish/bearish state into existing summary")
    print("  - reuses existing Active Trade section for CE or PE")
    print("  - reuses existing Exited Trades section for combined CE/PE")
    print("  - preserves existing candle-by-candle bullish audit section")
    print("  - removes the large coordinator activity table from the main UI")
    print("  - frontend only; no backend/strategy/worker change")
    if args.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-directional-ui-adjustment-v1-backup"/stamp/REL
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dst, backup)
    shutil.copy2(src, dst)
    print("APPLY PASS")
    print("Backup:", backup)
    print("Run: cd frontend && npm run build")
    print("No API or live-shadow worker restart required.")

if __name__=="__main__":
    main()
