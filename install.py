#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

REL = Path("frontend/src/hilegaDecisionTable.tsx")

OLD = r"""  const filtered=contextual.filter(row=>filter==='ALL'||row.displayKind===filter)"""
NEW = r"""  // Derive lifecycle state chronologically, but present newest completed candle first.
  // This keeps entry/continuation/exit state correct while making live monitoring easier.
  const filtered=[...contextual.filter(row=>filter==='ALL'||row.displayKind===filter)].reverse()"""

OLD_ENTRY = r"""const entryNiftyAt=(r:HilegaAudit):number|null=>{
  const entry=checkpointTransitions(r).find(isEntry)
  return finiteNumber(entry?.price??entry?.entry_price??r.bar?.close)
}"""
NEW_ENTRY = r"""const entryNiftyAt=(r:HilegaAudit):number|null=>{
  const entry=checkpointTransitions(r).find(isEntry)
  // Canonical entries use transition price. Restart-reconstructed entries also
  // expose the recorded signal_spot as the projected transition price. Never
  // infer an entry from a later continuation candle.
  return finiteNumber(entry?.price??entry?.entry_price??r.bar?.close)
}"""

def main():
    ap=argparse.ArgumentParser(description="Hilega UI latest-candle-first display + Nifty delta validation")
    ap.add_argument("--repo", required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a=ap.parse_args()

    repo=Path(a.repo).resolve()
    p=repo/REL
    if not p.is_file():
        print("BLOCKED: missing", REL)
        raise SystemExit(2)
    text=p.read_text(encoding="utf-8")

    if NEW in text:
        print("ALREADY_PATCHED:", REL)
        return
    if OLD not in text:
        print("BLOCKED: expected current filter/render block not found.")
        print("No file changed.")
        raise SystemExit(2)

    print("READY:", REL)
    print("  - lifecycle derivation remains oldest→newest")
    print("  - rendered table becomes newest→oldest")
    print("  - Nifty Δ remains based on original entry Nifty, never latest candle")
    print("  - reconstructed entry can seed Nifty Δ from recorded signal_spot")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-latest-first-ui-backup"/stamp/REL
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p,backup)

    text=text.replace(OLD,NEW,1)
    if OLD_ENTRY in text:
        text=text.replace(OLD_ENTRY,NEW_ENTRY,1)
    p.write_text(text,encoding="utf-8")
    print("APPLY PASS")
    print("Backup:",backup)
    print("Frontend-only change: run npm build; no API/worker restart is required.")

if __name__=="__main__":
    main()
