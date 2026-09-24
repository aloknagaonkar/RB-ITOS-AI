#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import argparse, shutil

OLD = """const direction=(r:DirectionalCandleOverlayRow):'BULLISH'|'BEARISH'|null=>{
  const a=String(r.action??'').toUpperCase()
  if(a.startsWith('BEARISH_'))return 'BEARISH'
  if(a.startsWith('BULLISH_'))return 'BULLISH'
  if(r.owner_after==='BEARISH'||r.owner_before==='BEARISH')return 'BEARISH'
  if(r.owner_after==='BULLISH'||r.owner_before==='BULLISH')return 'BULLISH'
  const events=list(r.accepted_events).map(x=>x.toUpperCase())
  if(events.some(x=>x.includes('BEARISH')))return 'BEARISH'
  if(events.some(x=>x.startsWith('ENTRY_')||x.includes('RSI_CROSS_BELOW_WMA21')))return 'BULLISH'
  if(r.bearish_armed===true||String(r.bearish_state??'').includes('BEARISH_ACTIVE'))return 'BEARISH'
  if(r.bullish_armed===true||String(r.bullish_state??'').includes('BULLISH_ACTIVE'))return 'BULLISH'
  return null
}"""

NEW = """const direction=(r:DirectionalCandleOverlayRow):'BULLISH'|'BEARISH'|null=>{
  const a=String(r.action??'').toUpperCase()
  const events=list(r.accepted_events).map(x=>x.toUpperCase())

  // Candidate/ARMED direction must come from the candidate evidence itself,
  // not from the current trade owner. Opposite-side ARMED is informational
  // and may coexist while the other side remains ACTIVE.
  if(events.some(x=>x.includes('BEARISH')))return 'BEARISH'
  if(events.some(x=>x.includes('PATH1_ARMED_RSI_CROSS_EMA3_UP')))return 'BULLISH'
  if(a==='ARMED_INFORMATION'){
    if(r.bearish_armed===true)return 'BEARISH'
    if(r.bullish_armed===true)return 'BULLISH'
  }

  if(a.startsWith('BEARISH_'))return 'BEARISH'
  if(a.startsWith('BULLISH_'))return 'BULLISH'

  if(r.bearish_armed===true && r.bullish_armed!==true)return 'BEARISH'
  if(r.bullish_armed===true && r.bearish_armed!==true)return 'BULLISH'

  // Owner determines direction only after candidate-specific evidence has
  // been considered.
  if(r.owner_after==='BEARISH'||r.owner_before==='BEARISH')return 'BEARISH'
  if(r.owner_after==='BULLISH'||r.owner_before==='BULLISH')return 'BULLISH'

  if(String(r.bearish_state??'').includes('BEARISH_ACTIVE'))return 'BEARISH'
  if(String(r.bullish_state??'').includes('BULLISH_ACTIVE'))return 'BULLISH'
  return null
}"""

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo",required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=ap.parse_args()

    repo=Path(a.repo).resolve()
    target=repo/"frontend/src/hilegaDirectionalAuditOverlay.ts"
    if not target.is_file():
        raise SystemExit(f"BLOCKED: missing {target}")

    text=target.read_text()
    if NEW in text:
        print("ALREADY PATCHED")
        return
    if OLD not in text:
        raise SystemExit("BLOCKED: expected direction() block not found; source differs from v5")

    print("READY")
    print("  - fixes bearish candidate direction while bullish owner is active")
    print("  - candidate ARMED evidence now takes priority over trade owner")
    print("  - preserves existing Hilega UI")
    print("  - frontend-only; no API/worker restart")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-bearish-candidate-direction-fix-v6-backup"/stamp/target.relative_to(repo)
    backup.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(target,backup)

    target.write_text(text.replace(OLD,NEW,1))
    print("APPLY PASS")
    print("Backup:",backup)
    print("Next: cd frontend && npm run build")
    print("Then hard refresh browser.")
    print("No API restart required.")
    print("Do not restart Hilega worker.")

if __name__=="__main__":
    main()
