#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import argparse, shutil

OLD_BADGE = """        const badge=k==='ENTRY'?'BULLISH_ENTRY':k==='EXIT'?'BULLISH_EXIT':k==='ACTIVE'?'BULLISH_CONTINUATION':k==='DETECTED'?'ARMED':k==='NONE'?'NO SIGNAL':k==='REVIEW'?'REVIEW REQUIRED':'REJECTED'"""
NEW_BADGE = """        const badge=k==='NONE'?'NO SIGNAL':k==='REVIEW'?'REVIEW REQUIRED':k==='REJECTED'?'REJECTED':displayDecisionText(k,reportDirection(r))"""

OLD_FILTER = """{({ALL:'All candles',DETECTED:'Armed / candidates',ENTRY:'Bullish entries',EXIT:'Bullish exits',ACTIVE:'Bullish continuations',REJECTED:'Rejected setups',REVIEW:'Review required'} as Record<Filter,string>)[k]}"""
NEW_FILTER = """{({ALL:'All candles',DETECTED:'Armed / candidates',ENTRY:'Directional entries',EXIT:'Directional exits',ACTIVE:'Directional continuations',REJECTED:'Rejected setups',REVIEW:'Review required'} as Record<Filter,string>)[k]}"""


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo",required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=ap.parse_args()

    repo=Path(a.repo).resolve()
    target=repo/"frontend/src/hilegaDecisionTable.tsx"
    if not target.is_file():
        raise SystemExit(f"BLOCKED: missing {target}")

    text=target.read_text()
    if "function displayDecisionText(kind:DisplayKind,direction:'BULLISH'|'BEARISH'" not in text:
        raise SystemExit("BLOCKED: direction-aware displayDecisionText not found")

    if NEW_BADGE in text:
        print("ALREADY PATCHED")
        return
    if OLD_BADGE not in text:
        raise SystemExit("BLOCKED: expected hard-coded badge line not found")

    print("READY")
    print("  - fixes Signal detected badge to use actual row direction")
    print("  - BEARISH_ENTRY / BEARISH_CONTINUATION / BEARISH_EXIT now render correctly")
    print("  - candidate badge becomes direction-aware too")
    print("  - existing table layout/CSS unchanged")
    print("  - frontend-only; no API/worker restart")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-directional-badge-label-fix-v8-backup"/stamp/target.relative_to(repo)
    backup.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(target,backup)

    text=text.replace(OLD_BADGE,NEW_BADGE,1)
    if OLD_FILTER in text:
        text=text.replace(OLD_FILTER,NEW_FILTER,1)
    target.write_text(text)

    print("APPLY PASS")
    print("Backup:",backup)
    print("Next: cd frontend && npm run build")
    print("Then hard refresh browser.")
    print("No API restart required.")
    print("Do not restart Hilega live-shadow worker.")

if __name__=="__main__":
    main()
