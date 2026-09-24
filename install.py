#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import shutil


OLD_STATE = """export function deriveDecisionRows(reports:HilegaAudit[]):DecisionRow[] {
  let active=false,origin:string|null=null,originRoute:string|null=null,entryNifty:number|null=null,sessionDate:string|null=null
  return [...reports].sort((a,b)=>a.checkpoint.localeCompare(b.checkpoint)).map(report=>{"""

NEW_STATE = """export function deriveDecisionRows(reports:HilegaAudit[]):DecisionRow[] {
  let active=false,activeDirection:'BULLISH'|'BEARISH'|null=null,origin:string|null=null,originRoute:string|null=null,entryNifty:number|null=null,sessionDate:string|null=null
  return [...reports].sort((a,b)=>a.checkpoint.localeCompare(b.checkpoint)).map(report=>{"""

OLD_RESET = """    if(sessionDate!==date){active=false;origin=null;originRoute=null;entryNifty=null;sessionDate=date}"""
NEW_RESET = """    if(sessionDate!==date){active=false;activeDirection=null;origin=null;originRoute=null;entryNifty=null;sessionDate=date}"""

OLD_ENTRY = """        active=true
        origin=report.checkpoint"""
NEW_ENTRY = """        active=true
        activeDirection=reportDirection(report)
        origin=report.checkpoint"""

OLD_ACTIVE_BRANCH = """    }else if(active){
      if(String(report.strategy?.state_after??'').toUpperCase()==='SESSION_LOCKED'){
        displayKind='REVIEW'
        lifecycleIssue='SESSION_LOCKED_WITHOUT_BULLISH_EXIT'
      }else{
        // Once entered, every completed candle is continuation until a genuine
        // recorded exit, regardless of unrelated candidate/rejection fragments.
        displayKind='ACTIVE'
      }
    }else if(rawKind==='ACTIVE'){"""

NEW_ACTIVE_BRANCH = """    }else if(active){
      const rowDirection=reportDirection(report)
      if(rawKind==='DETECTED' && activeDirection!==null && rowDirection!==activeDirection){
        // Opposite-side ARMED/candidate information is allowed to coexist with
        // the active trade owner. Preserve it as DETECTED instead of flattening
        // it into the active owner's continuation row.
        displayKind='DETECTED'
      }else if(String(report.strategy?.state_after??'').toUpperCase()==='SESSION_LOCKED'){
        displayKind='REVIEW'
        lifecycleIssue=`SESSION_LOCKED_WITHOUT_${activeDirection??'ACTIVE'}_EXIT`
      }else{
        displayKind='ACTIVE'
      }
    }else if(rawKind==='ACTIVE'){"""

OLD_LINK_ACTIVE = """        active=true
        origin=linked"""
NEW_LINK_ACTIVE = """        active=true
        activeDirection=reportDirection(report)
        origin=linked"""

OLD_EXIT_RESET = """      active=false
      origin=null"""
NEW_EXIT_RESET = """      active=false
      activeDirection=null
      origin=null"""

OLD_REVIEW_RESET = """      active=false
      origin=null"""
NEW_REVIEW_RESET = """      active=false
      activeDirection=null
      origin=null"""

# Optional direction-aware DETECTED labels if prior v2 patch is present.
OLD_DISPLAY = """export function displayDecisionText(kind:DisplayKind,direction:'BULLISH'|'BEARISH'='BULLISH'):string {
  switch(kind){
    case 'ENTRY':return `${direction}_ENTRY`
    case 'ACTIVE':return `${direction}_CONTINUATION`
    case 'EXIT':return `${direction}_EXIT`
    case 'DETECTED':return 'ARMED / OPENING CANDIDATE'"""
NEW_DISPLAY = """export function displayDecisionText(kind:DisplayKind,direction:'BULLISH'|'BEARISH'='BULLISH'):string {
  switch(kind){
    case 'ENTRY':return `${direction}_ENTRY`
    case 'ACTIVE':return `${direction}_CONTINUATION`
    case 'EXIT':return `${direction}_EXIT`
    case 'DETECTED':return `${direction}_CANDIDATE / ARMED`"""

OLD_DECISION = """export function decisionText(r:HilegaAudit):string {
  const direction=reportDirection(r)
  switch(eventKind(r)) {
    case 'ENTRY':return `${direction}_ENTRY`
    case 'ACTIVE':return `${direction}_CONTINUATION`
    case 'EXIT':return `${direction}_EXIT`
    case 'DETECTED':return 'ARMED / OPENING CANDIDATE'"""
NEW_DECISION = """export function decisionText(r:HilegaAudit):string {
  const direction=reportDirection(r)
  switch(eventKind(r)) {
    case 'ENTRY':return `${direction}_ENTRY`
    case 'ACTIVE':return `${direction}_CONTINUATION`
    case 'EXIT':return `${direction}_EXIT`
    case 'DETECTED':return `${direction}_CANDIDATE / ARMED`"""


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"BLOCKED: {label} block not found")
    return text.replace(old, new, 1)


def patch(text: str) -> str:
    if "const reportDirection=" not in text:
        raise SystemExit("BLOCKED: direction-aware UI patch is not installed")

    text = replace_required(text, OLD_STATE, NEW_STATE, "derive state")
    text = replace_required(text, OLD_RESET, NEW_RESET, "session reset")
    text = replace_required(text, OLD_ENTRY, NEW_ENTRY, "entry active direction")
    text = replace_required(text, OLD_ACTIVE_BRANCH, NEW_ACTIVE_BRANCH, "active/candidate branch")
    text = replace_required(text, OLD_LINK_ACTIVE, NEW_LINK_ACTIVE, "linked active direction")

    # There are two reset sites with identical old text. Replace each remaining
    # occurrence only where activeDirection reset is not already present.
    if OLD_EXIT_RESET in text:
        text = text.replace(OLD_EXIT_RESET, NEW_EXIT_RESET, 1)
    if OLD_REVIEW_RESET in text:
        text = text.replace(OLD_REVIEW_RESET, NEW_REVIEW_RESET, 1)

    if OLD_DISPLAY in text:
        text = text.replace(OLD_DISPLAY, NEW_DISPLAY, 1)
    if OLD_DECISION in text:
        text = text.replace(OLD_DECISION, NEW_DECISION, 1)

    return text


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

    original=target.read_text()
    patched=patch(original)

    print("READY")
    print("  - preserves existing HilegaDecisionTable UI/CSS")
    print("  - tracks active trade direction explicitly")
    print("  - preserves opposite-side ARMED/candidate rows while a trade is active")
    print("  - labels DETECTED rows as BULLISH_CANDIDATE / ARMED or BEARISH_CANDIDATE / ARMED")
    print("  - no backend, strategy, coordinator, CE/PE or API changes")
    print("  - frontend-only; no API/worker restart")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-bearish-candidate-preserve-v5-backup"/stamp/target.relative_to(repo)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)

    target.write_text(patched)

    print("APPLY PASS")
    print("Backup:", backup)
    print("Next: cd frontend && npm run build")
    print("Then hard refresh browser.")
    print("No API restart required.")
    print("Do not restart Hilega live-shadow worker.")


if __name__=="__main__":
    main()
