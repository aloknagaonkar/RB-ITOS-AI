#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import argparse, shutil

OLD = """const reportDirection=(r:HilegaAudit):'BULLISH'|'BEARISH'=>{
  const explicit=String(r.strategy?.direction??'').toUpperCase()
  if(explicit==='BEARISH')return 'BEARISH'
  const action=String(r.strategy?.directional_action??'').toUpperCase()
  if(action.startsWith('BEARISH_'))return 'BEARISH'
  const events=list(r.strategy?.events_emitted).map(x=>String(x).toUpperCase())
  if(events.some(x=>x.includes('BEARISH')))return 'BEARISH'
  const states=[r.strategy?.state_before,r.strategy?.state_after,r.strategy?.bearish_state].map(x=>String(x??'').toUpperCase())
  if(states.some(x=>x.includes('BEARISH_ACTIVE')))return 'BEARISH'
  return 'BULLISH'
}"""

NEW = """const reportDirection=(r:HilegaAudit):'BULLISH'|'BEARISH'=>{
  const ownerAfter=String(r.strategy?.owner_after??'').toUpperCase()
  const ownerBefore=String(r.strategy?.owner_before??'').toUpperCase()
  const stateAfter=String(r.strategy?.state_after??'').toUpperCase()
  const action=String(r.strategy?.directional_action??'').toUpperCase()

  // Visible decision direction follows the exclusive active owner first.
  // Opposite-side ARMED state may remain preserved internally, but it must not
  // replace the displayed active trade with an opposite candidate.
  if(stateAfter==='BULLISH_ACTIVE'||ownerAfter==='BULLISH')return 'BULLISH'
  if(stateAfter==='BEARISH_ACTIVE'||ownerAfter==='BEARISH')return 'BEARISH'

  // On exit owner_after is NONE, so use the recorded exit action / prior owner.
  if(action.startsWith('BULLISH_'))return 'BULLISH'
  if(action.startsWith('BEARISH_'))return 'BEARISH'
  if(ownerBefore==='BULLISH'&&action.includes('EXIT'))return 'BULLISH'
  if(ownerBefore==='BEARISH'&&action.includes('EXIT'))return 'BEARISH'

  // When no trade is active, candidate direction comes from the recorded
  // directional evidence.
  const explicit=String(r.strategy?.direction??'').toUpperCase()
  if(explicit==='BEARISH')return 'BEARISH'
  if(explicit==='BULLISH')return 'BULLISH'
  const events=list(r.strategy?.events_emitted).map(x=>String(x).toUpperCase())
  if(events.some(x=>x.includes('BEARISH')))return 'BEARISH'
  if(events.some(x=>x.includes('BULLISH')||x.startsWith('ENTRY_PATH1_')))return 'BULLISH'
  const bearishState=String(r.strategy?.bearish_state??'').toUpperCase()
  if(bearishState.includes('BEARISH_ACTIVE')||bearishState.includes('BEARISH_PATH1_ARMED'))return 'BEARISH'
  return 'BULLISH'
}"""

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
    if NEW in text:
        print("ALREADY PATCHED")
        return
    if OLD not in text:
        raise SystemExit("BLOCKED: expected reportDirection block not found")

    print("READY")
    print("  - active owner has display priority over opposite ARMED state")
    print("  - during BULLISH_ACTIVE, rows remain BULLISH_CONTINUATION")
    print("  - during BEARISH_ACTIVE, rows remain BEARISH_CONTINUATION")
    print("  - opposite candidate is shown only when there is no active owner")
    print("  - internal ARMED evidence is not deleted")
    print("  - frontend-only; no API/worker restart")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-active-owner-display-priority-v9-backup"/stamp/target.relative_to(repo)
    backup.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(target,backup)

    target.write_text(text.replace(OLD,NEW,1))

    print("APPLY PASS")
    print("Backup:",backup)
    print("Next: cd frontend && npm run build")
    print("Then hard refresh browser.")
    print("No API restart required.")
    print("Do not restart Hilega live-shadow worker.")

if __name__=="__main__":
    main()
