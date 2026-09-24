#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import argparse, shutil

OLD = """export function eventKind(r:HilegaAudit):Kind {
  const t=checkpointTransitions(r)
  const events=list(r.strategy?.events_emitted).map(String)
  if(t.some(isEntry)||events.some(x=>x.startsWith('ENTRY_')))return 'ENTRY'
  if(t.some(isExit)||events.some(x=>x.includes('EXIT')))return 'EXIT'
  if(['BULLISH_ACTIVE','BEARISH_ACTIVE'].includes(String(r.strategy?.state_after??'').toUpperCase()))return 'ACTIVE'
  if(events.some(x=>x.includes('REJECTED')))return 'REJECTED'
  if(events.some(x=>/CANDIDATE|ARMED|DETECT|OPENING_HOLD/.test(x)) ||
     ['PATH1_ARMED','BEARISH_PATH1_ARMED'].includes(String(r.strategy?.state_after??'').toUpperCase()))return 'DETECTED'
  return 'NONE'
}"""

NEW = """export function eventKind(r:HilegaAudit):Kind {
  const t=checkpointTransitions(r)
  const events=list(r.strategy?.events_emitted).map(String)
  const directionalAction=String(r.strategy?.directional_action??'').toUpperCase()
  const bullishArmed=r.strategy?.bullish_armed===true
  const bearishArmed=r.strategy?.bearish_armed===true

  if(t.some(isEntry)||events.some(x=>x.startsWith('ENTRY_')))return 'ENTRY'
  if(t.some(isExit)||events.some(x=>x.includes('EXIT')))return 'EXIT'

  // Informational ARMED/candidate evidence may coexist with the opposite active
  // trade owner. Detect it before ACTIVE so it is not flattened into a
  // continuation row merely because state_after reflects the exclusive owner.
  if(
    directionalAction==='ARMED_INFORMATION' ||
    events.some(x=>/CANDIDATE|ARMED|DETECT|OPENING_HOLD/.test(x)) ||
    bullishArmed || bearishArmed ||
    ['PATH1_ARMED','BEARISH_PATH1_ARMED'].includes(String(r.strategy?.state_after??'').toUpperCase())
  )return 'DETECTED'

  if(['BULLISH_ACTIVE','BEARISH_ACTIVE'].includes(String(r.strategy?.state_after??'').toUpperCase()))return 'ACTIVE'
  if(events.some(x=>x.includes('REJECTED')))return 'REJECTED'
  return 'NONE'
}"""


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
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
        raise SystemExit("BLOCKED: expected eventKind block not found")

    print("READY")
    print("  - keeps existing Hilega UI unchanged")
    print("  - candidate/ARMED classification now takes precedence over ACTIVE continuation")
    print("  - preserves opposite-side candidate while owner remains exclusive")
    print("  - no strategy/coordinator/backend/API changes")
    print("  - frontend-only; no worker restart")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-directional-eventkind-precedence-v7-backup"/stamp/target.relative_to(repo)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)

    target.write_text(text.replace(OLD, NEW, 1))

    print("APPLY PASS")
    print("Backup:", backup)
    print("Next: cd frontend && npm run build")
    print("Then hard refresh browser.")
    print("No API restart required.")
    print("Do not restart Hilega live-shadow worker.")


if __name__=="__main__":
    main()
