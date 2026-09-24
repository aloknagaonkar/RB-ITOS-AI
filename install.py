#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

REL = Path("frontend/src/hilegaDecisionTable.tsx")

OLD_HEADER = """<th>Date / Time (IST)</th><th>Strategy rule / decision</th><th>Nifty Δ from entry</th><th>Opening path / Route A / Route B</th>"""
NEW_HEADER = """<th>Date / Time (IST)</th><th>Strategy rule / decision</th><th>NIFTY O → C / Δ from entry</th><th>Opening path / Route A / Route B</th>"""

OLD_RENDER = """<td><span>{timing.window}</span>{timing.processed&&<small>{timing.label} {timing.processed}</small>}</td><td><strong>{shortRuleText(r,k,lifecycleIssue)}</strong>{lifecycleIssue&&<small className="hd-lifecycle-issue">{lifecycleIssue}</small>}</td><td className={color(niftyPoints)}>{niftyPoints===null?'—':`${niftyPoints>0?'+':''}${money(niftyPoints)} pts`}</td>"""

NEW_RENDER = """<td><span>{timing.window}</span>{timing.processed&&<small>{timing.label==='recovered'?`recovered ${timing.processed}`:timing.processed}</small>}</td><td><strong>{shortRuleText(r,k,lifecycleIssue)}</strong>{lifecycleIssue&&<small className="hd-lifecycle-issue">{lifecycleIssue}</small>}</td><td><span>O {money(r.bar?.open)} → C {money(r.bar?.close)}</span><small className={color(niftyPoints)}>{niftyPoints===null?'—':`${niftyPoints>0?'+':''}${money(niftyPoints)} pts`}</small></td>"""

def replace_once(text, old, new, label):
    if new in text:
        return text, False
    if old not in text:
        raise RuntimeError(f"BLOCKED: expected block not found: {label}")
    return text.replace(old, new, 1), True

def main():
    ap=argparse.ArgumentParser(description="Hilega NIFTY O→C + entry delta and cleaner timing")
    ap.add_argument("--repo",required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=ap.parse_args()

    repo=Path(a.repo).resolve()
    p=repo/REL
    if not p.is_file():
        print("BLOCKED: missing",REL)
        raise SystemExit(2)

    text=p.read_text(encoding="utf-8")
    try:
        text,c1=replace_once(text,OLD_HEADER,NEW_HEADER,"table header")
        text,c2=replace_once(text,OLD_RENDER,NEW_RENDER,"table row rendering")
    except RuntimeError as e:
        print(e)
        print("No files changed.")
        raise SystemExit(2)

    if not (c1 or c2):
        print("ALREADY_PATCHED")
        return

    print("READY:",REL)
    print("  - removes the literal word 'processed' from normal live rows")
    print("  - keeps actual processing time, e.g. 11:10:33")
    print("  - keeps 'recovered' only for bootstrap-recovered provenance")
    print("  - shows NIFTY candle Open → Close on every row")
    print("  - keeps Δ from trade entry on the second line")
    print("  - no backend, strategy, worker, or evidence changes")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-nifty-oc-time-ui-backup"/stamp/REL
    backup.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(p,backup)
    p.write_text(text,encoding="utf-8")
    print("APPLY PASS")
    print("Backup:",backup)
    print("Frontend-only patch: run npm build. No API or worker restart required.")

if __name__=="__main__":
    main()
