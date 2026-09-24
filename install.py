#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import argparse, shutil

IMPORT_OLD = "import {overlayDirectionalAuditReports} from './hilegaDirectionalAuditOverlay'"
IMPORT_NEW = "import {augmentDirectionalRowsWithTrades,overlayDirectionalAuditReports} from './hilegaDirectionalAuditOverlay'"

LIVE_OLD = """    let merged=a as HilegaAudit[]
    if(dr.ok){
      const directional=await dr.json()
      merged=overlayDirectionalAuditReports(a as HilegaAudit[],directional.rows??[])
    }
    setStatus(s);setRows(merged as AuditReport[]);setDashboard(d);setError('')"""

LIVE_NEW = """    let merged=a as HilegaAudit[]
    if(dr.ok){
      const directional=await dr.json()
      const directionalRows=augmentDirectionalRowsWithTrades(directional.rows??[],d.trades??[])
      merged=overlayDirectionalAuditReports(a as HilegaAudit[],directionalRows)
    }
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
    overlay_dst=repo/"frontend/src/hilegaDirectionalAuditOverlay.ts"
    overlay_src=Path(__file__).resolve().parent/"files/frontend/src/hilegaDirectionalAuditOverlay.ts"

    for p in (live,overlay_dst):
        if not p.is_file():
            raise SystemExit(f"BLOCKED: missing {p}")

    text=live.read_text()
    if IMPORT_OLD not in text and IMPORT_NEW not in text:
        raise SystemExit("BLOCKED: directional overlay import not found")
    if LIVE_OLD not in text and LIVE_NEW not in text:
        raise SystemExit("BLOCKED: live directional overlay block not found")

    print("READY")
    print("  - preserves existing HilegaDecisionTable UI")
    print("  - normalizes timestamps to epoch-minute before overlay")
    print("  - recovers missing live ENTRY/EXIT signals from directional trade dashboard")
    print("  - uses recorded trade signal_bar/source/exit evidence only")
    print("  - no backend/strategy/coordinator/option changes")
    print("  - frontend-only; no API or worker restart")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-directional-ui-signal-overlay-v3-backup"/stamp
    for p in (live,overlay_dst):
        dst=backup/p.relative_to(repo)
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dst)

    shutil.copy2(overlay_src,overlay_dst)

    text=live.read_text().replace(IMPORT_OLD,IMPORT_NEW,1)
    if LIVE_NEW not in text:
        text=text.replace(LIVE_OLD,LIVE_NEW,1)
    live.write_text(text)

    print("APPLY PASS")
    print("Backup:",backup)
    print("Next: cd frontend && npm run build")
    print("Then hard refresh.")
    print("No API restart required.")
    print("Do not restart Hilega live-shadow worker.")

if __name__=="__main__":
    main()
