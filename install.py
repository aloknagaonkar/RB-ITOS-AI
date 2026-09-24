#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import shutil

OVERLAY_IMPORT = "import {overlayDirectionalAuditReports} from './hilegaDirectionalAuditOverlay'"
CUSTOM_IMPORT = "import HilegaDirectionalCandleTable from './hilegaDirectionalCandleTable'"

LIVE_REFRESH_OLD = """  const refresh=async()=>{
    const [s,a,d]=await Promise.all([
      getDirectional<DirectionalStatus>('/status'),
      getBullish<AuditReport[]>('/audit-index?limit=200'),
      getDirectional<Dashboard>('/trade-dashboard'),
    ])
    setStatus(s);setRows(a);setDashboard(d);setError('')
  }"""

LIVE_REFRESH_NEW = """  const refresh=async()=>{
    const [s,a,d,dr]=await Promise.all([
      getDirectional<DirectionalStatus>('/status'),
      getBullish<AuditReport[]>('/audit-index?limit=200'),
      getDirectional<Dashboard>('/trade-dashboard'),
      fetch('/api/live-shadow/hilega-directional-candles/live'),
    ])
    let merged=a as HilegaAudit[]
    if(dr.ok){
      const directional=await dr.json()
      merged=overlayDirectionalAuditReports(a as HilegaAudit[],directional.rows??[])
    }
    setStatus(s);setRows(merged as AuditReport[]);setDashboard(d);setError('')
  }"""

LIVE_TABLE_OLD = """      <HilegaDirectionalCandleTable mode="LIVE" />"""
LIVE_TABLE_NEW = """      <HilegaDecisionTable reports={rows as HilegaAudit[]} mode="LIVE"
        fetchDetail={detailedAudit}
        emptyMessage="No completed live strategy checkpoints available yet." />"""

HIST_LOAD_OLD = """      const r=await fetch(`/api/live-shadow/hilega-historical/session?session_date=${encodeURIComponent(selectedDate)}`)
      if(!r.ok)throw new Error(`Session HTTP ${r.status}: ${await r.text()}`)
      setData(await r.json() as Response)"""

HIST_LOAD_NEW = """      const [r,dr]=await Promise.all([
        fetch(`/api/live-shadow/hilega-historical/session?session_date=${encodeURIComponent(selectedDate)}`),
        fetch(`/api/live-shadow/hilega-directional-candles/historical?session_date=${encodeURIComponent(selectedDate)}`),
      ])
      if(!r.ok)throw new Error(`Session HTTP ${r.status}: ${await r.text()}`)
      const body=await r.json() as Response
      if(dr.ok){
        const directional=await dr.json()
        body.reports=overlayDirectionalAuditReports(body.reports??[],directional.rows??[])
        body.report_count=body.reports.length
      }
      setData(body)"""

HIST_TABLE_OLD = """      <HilegaDirectionalCandleTable mode="HISTORICAL" sessionDate={selectedDate} />"""
HIST_TABLE_NEW = """      <HilegaDecisionTable key={`${selectedDate}-${data.source}-${step?'step':'full'}`} reports={reports}
        mode="HISTORICAL" visibleUntil={until}
        emptyMessage="No Hilega strategy rows were recorded for this session."
        onSelected={setReviewCheckpoint}/>"""


def add_import(text: str, anchor: str) -> str:
    if OVERLAY_IMPORT in text:
        return text
    if anchor not in text:
        raise SystemExit(f"BLOCKED: import anchor missing: {anchor}")
    return text.replace(anchor, anchor + "\n" + OVERLAY_IMPORT, 1)


def patch_live(text: str) -> str:
    text = text.replace(CUSTOM_IMPORT + "\n", "").replace(CUSTOM_IMPORT, "")
    text = add_import(text, "import HilegaDecisionTable,{type HilegaAudit} from './hilegaDecisionTable'")

    if LIVE_REFRESH_NEW not in text:
        if LIVE_REFRESH_OLD not in text:
            raise SystemExit("BLOCKED: current live refresh block not found")
        text = text.replace(LIVE_REFRESH_OLD, LIVE_REFRESH_NEW, 1)

    if LIVE_TABLE_NEW not in text:
        if LIVE_TABLE_OLD not in text:
            raise SystemExit("BLOCKED: current live directional table block not found")
        text = text.replace(LIVE_TABLE_OLD, LIVE_TABLE_NEW, 1)

    return text


def patch_hist(text: str) -> str:
    text = text.replace(CUSTOM_IMPORT + "\n", "").replace(CUSTOM_IMPORT, "")
    text = add_import(text, "import HilegaDecisionTable,{type HilegaAudit} from './hilegaDecisionTable'")

    if HIST_LOAD_NEW not in text:
        if HIST_LOAD_OLD not in text:
            raise SystemExit("BLOCKED: current historical load block not found")
        text = text.replace(HIST_LOAD_OLD, HIST_LOAD_NEW, 1)

    if HIST_TABLE_NEW not in text:
        if HIST_TABLE_OLD not in text:
            raise SystemExit("BLOCKED: current historical directional table block not found")
        text = text.replace(HIST_TABLE_OLD, HIST_TABLE_NEW, 1)

    return text


def patch_table(text: str) -> str:
    helper = """const reportDirection=(r:HilegaAudit):'BULLISH'|'BEARISH'=>{
  const explicit=String(r.strategy?.direction??'').toUpperCase()
  if(explicit==='BEARISH')return 'BEARISH'
  const action=String(r.strategy?.directional_action??'').toUpperCase()
  if(action.startsWith('BEARISH_'))return 'BEARISH'
  const events=list(r.strategy?.events_emitted).map(x=>String(x).toUpperCase())
  if(events.some(x=>x.includes('BEARISH')))return 'BEARISH'
  const states=[r.strategy?.state_before,r.strategy?.state_after,r.strategy?.bearish_state].map(x=>String(x??'').toUpperCase())
  if(states.some(x=>x.includes('BEARISH_ACTIVE')))return 'BEARISH'
  return 'BULLISH'
}

"""
    marker = "export function eventKind(r:HilegaAudit):Kind {"
    if helper.strip() not in text:
        if marker not in text:
            raise SystemExit("BLOCKED: eventKind marker missing")
        text = text.replace(marker, helper + marker, 1)

    text = text.replace(
        "if(String(r.strategy?.state_after??'').toUpperCase()==='BULLISH_ACTIVE')return 'ACTIVE'",
        "if(['BULLISH_ACTIVE','BEARISH_ACTIVE'].includes(String(r.strategy?.state_after??'').toUpperCase()))return 'ACTIVE'",
        1,
    )
    text = text.replace(
        "String(r.strategy?.state_after??'').toUpperCase()==='PATH1_ARMED')return 'DETECTED'",
        "['PATH1_ARMED','BEARISH_PATH1_ARMED'].includes(String(r.strategy?.state_after??'').toUpperCase()))return 'DETECTED'",
        1,
    )

    old = """export function decisionText(r:HilegaAudit):string {
  switch(eventKind(r)) {
    case 'ENTRY':return 'BULLISH_ENTRY'
    case 'ACTIVE':return 'BULLISH_CONTINUATION'
    case 'EXIT':return 'BULLISH_EXIT'"""
    new = """export function decisionText(r:HilegaAudit):string {
  const direction=reportDirection(r)
  switch(eventKind(r)) {
    case 'ENTRY':return `${direction}_ENTRY`
    case 'ACTIVE':return `${direction}_CONTINUATION`
    case 'EXIT':return `${direction}_EXIT`"""
    if old in text:
        text = text.replace(old, new, 1)

    old = """export function displayDecisionText(kind:DisplayKind):string {
  switch(kind){
    case 'ENTRY':return 'BULLISH_ENTRY'
    case 'ACTIVE':return 'BULLISH_CONTINUATION'
    case 'EXIT':return 'BULLISH_EXIT'"""
    new = """export function displayDecisionText(kind:DisplayKind,direction:'BULLISH'|'BEARISH'='BULLISH'):string {
  switch(kind){
    case 'ENTRY':return `${direction}_ENTRY`
    case 'ACTIVE':return `${direction}_CONTINUATION`
    case 'EXIT':return `${direction}_EXIT`"""
    if old in text:
        text = text.replace(old, new, 1)

    text = text.replace(
        "Decision: {displayDecisionText(displayKind)}",
        "Decision: {displayDecisionText(displayKind,reportDirection(r))}",
    )
    text = text.replace(
        "<b>BULLISH_ENTRY confirmed by {pathText(r)}</b>",
        "<b>{displayDecisionText('ENTRY',reportDirection(r))} confirmed by {pathText(r)}</b>",
    )
    text = text.replace(
        "<b>BULLISH_CONTINUATION</b><p>Recorded state remains BULLISH_ACTIVE",
        "<b>{displayDecisionText('ACTIVE',reportDirection(r))}</b><p>Recorded state remains {val(r.strategy?.state_after)}",
    )
    text = text.replace(
        "<b>BULLISH_EXIT</b><p>Recorded exit:",
        "<b>{displayDecisionText('EXIT',reportDirection(r))}</b><p>Recorded exit:",
    )

    text = text.replace(
        "export function shortRuleText(r:HilegaAudit,kind:DisplayKind,lifecycleIssue?:string|null):string {\n  const path=pathText(r).toUpperCase()",
        "export function shortRuleText(r:HilegaAudit,kind:DisplayKind,lifecycleIssue?:string|null):string {\n  const direction=reportDirection(r)\n  const path=pathText(r).toUpperCase()",
    )
    text = text.replace(
        "if(path.includes('ROUTE A'))return 'ENTRY · RSI↑EMA + RSI>50 + RSI>WMA'",
        "if(path.includes('ROUTE A'))return direction==='BEARISH'?'ENTRY · RSI↓EMA + RSI<50 + RSI<WMA':'ENTRY · RSI↑EMA + RSI>50 + RSI>WMA'",
    )
    text = text.replace(
        "if(path.includes('ROUTE B'))return 'ENTRY · ARMED + (RSI>WMA OR EMA>WMA) + RSI↑ + EMA↑'",
        "if(path.includes('ROUTE B'))return direction==='BEARISH'?'ENTRY · ARMED + (RSI<WMA OR EMA<WMA) + RSI↓ + EMA↓':'ENTRY · ARMED + (RSI>WMA OR EMA>WMA) + RSI↑ + EMA↑'",
    )
    text = text.replace(
        "if(kind==='ACTIVE')return 'CONTINUE · BULLISH_ACTIVE'",
        "if(kind==='ACTIVE')return `CONTINUE · ${direction}_ACTIVE`",
    )
    text = text.replace(
        "if(label.includes('RSI_CROSS_BELOW_WMA21'))return 'EXIT · RSI↓WMA21'",
        "if(label.includes('RSI_CROSS_BELOW_WMA21'))return 'EXIT · RSI↓WMA21'\n    if(label.includes('BEARISH_RSI_CROSS_ABOVE_WMA21'))return 'EXIT · RSI↑WMA21'",
    )
    text = text.replace(
        "return 'ARMED · RSI↑EMA'",
        "return direction==='BEARISH'?'ARMED · RSI↓EMA':'ARMED · RSI↑EMA'",
    )
    return text


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo",required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=ap.parse_args()

    repo=Path(a.repo).resolve()
    payload=Path(__file__).resolve().parent/"files"
    live=repo/"frontend/src/hilegaMilegaShadow.tsx"
    hist=repo/"frontend/src/hilegaHistoricalReplay.tsx"
    table=repo/"frontend/src/hilegaDecisionTable.tsx"

    for p in (live,hist,table):
        if not p.is_file(): raise SystemExit(f"BLOCKED: missing {p}")

    # Validate exact current source before any write.
    patch_live(live.read_text())
    patch_hist(hist.read_text())
    patch_table(table.read_text())

    print("READY")
    print("  - restores original HilegaDecisionTable UI")
    print("  - keeps existing filters/cards/row expansion/CSS")
    print("  - overlays bearish directional events into existing audit rows")
    print("  - adds bearish entry/continuation/exit labels")
    print("  - no backend/strategy/coordinator/option changes")
    print("  - no API or Hilega worker restart")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-directional-ui-preserve-existing-v2-backup"/stamp
    for p in (live,hist,table):
        dst=backup/p.relative_to(repo)
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dst)

    overlay_src=payload/"frontend/src/hilegaDirectionalAuditOverlay.ts"
    overlay_dst=repo/"frontend/src/hilegaDirectionalAuditOverlay.ts"
    shutil.copy2(overlay_src,overlay_dst)

    live.write_text(patch_live(live.read_text()))
    hist.write_text(patch_hist(hist.read_text()))
    table.write_text(patch_table(table.read_text()))

    print("APPLY PASS")
    print("Backup:",backup)
    print("Next: cd frontend && npm run build")
    print("Then hard refresh the browser.")
    print("No API restart required.")
    print("Do not restart Hilega live-shadow worker.")


if __name__=="__main__":
    main()
