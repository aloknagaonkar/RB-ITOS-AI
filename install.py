#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import argparse, shutil

IMPORT = "import {overlayDirectionalTradeMarkers} from './hilegaDirectionalTradeMarkerOverlay'"

OLD_SET = "    setStatus(s);setRows(merged as AuditReport[]);setDashboard(d);setError('')"
NEW_SET = """    merged=overlayDirectionalTradeMarkers(merged,d.trades??[])
    setStatus(s);setRows(merged as AuditReport[]);setDashboard(d);setError('')"""


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo",required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=ap.parse_args()

    repo=Path(a.repo).resolve()
    live=repo/"frontend/src/hilegaMilegaShadow.tsx"
    helper_src=Path(__file__).resolve().parent/"files/frontend/src/hilegaDirectionalTradeMarkerOverlay.ts"
    helper_dst=repo/"frontend/src/hilegaDirectionalTradeMarkerOverlay.ts"

    if not live.is_file():
        raise SystemExit(f"BLOCKED: missing {live}")

    text=live.read_text()
    if OLD_SET not in text and NEW_SET not in text:
        raise SystemExit("BLOCKED: live merged-row set block not found")

    print("READY")
    print("  - keeps the existing HilegaDecisionTable UI unchanged")
    print("  - injects recorded ENTRY/EXIT markers directly into existing audit reports")
    print("  - uses trade signal_bar first, then signal_boundary-5m fallback")
    print("  - does not infer/recalculate strategy signals")
    print("  - no backend/API/worker restart")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-live-signal-marker-overlay-v4-backup"/stamp
    for p in (live,):
        dst=backup/p.relative_to(repo)
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dst)

    shutil.copy2(helper_src,helper_dst)

    text=live.read_text()
    if IMPORT not in text:
        anchor="import HilegaDecisionTable,{type HilegaAudit} from './hilegaDecisionTable'"
        if anchor not in text:
            raise SystemExit("BLOCKED: HilegaDecisionTable import anchor not found")
        text=text.replace(anchor,anchor+"\n"+IMPORT,1)

    if NEW_SET not in text:
        text=text.replace(OLD_SET,NEW_SET,1)

    live.write_text(text)

    print("APPLY PASS")
    print("Backup:",backup)
    print("Next: cd frontend && npm run build")
    print("Then hard refresh browser.")
    print("No API restart required.")
    print("Do not restart Hilega live-shadow worker.")

if __name__=="__main__":
    main()
