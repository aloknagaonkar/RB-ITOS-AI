#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import argparse, shutil

OVERLAY_IMPORT = "import {overlayDirectionalAuditReports} from './hilegaDirectionalAuditOverlay'"
CUSTOM_IMPORT = "import HilegaDirectionalCandleTable from './hilegaDirectionalCandleTable'"
ORIGINAL_HIST_TABLE = """      <HilegaDecisionTable key={`${selectedDate}-${data.source}-${step?'step':'full'}`} reports={reports}
        mode="HISTORICAL" visibleUntil={until}
        emptyMessage="No Hilega strategy rows were recorded for this session."
        onSelected={setReviewCheckpoint}/>"""
CUSTOM_HIST_TABLE = """      <HilegaDirectionalCandleTable mode="HISTORICAL" sessionDate={selectedDate} />"""
ORIGINAL_LIVE_TABLE = """      <HilegaDecisionTable reports={rows as HilegaAudit[]} mode="LIVE"
        fetchDetail={detailedAudit}
        emptyMessage="No completed live strategy checkpoints available yet." />"""
CUSTOM_LIVE_TABLE = """      <HilegaDirectionalCandleTable mode="LIVE" />"""


def ensure_import(text: str, anchor: str) -> str:
    if OVERLAY_IMPORT in text:
        return text
    if anchor not in text:
        raise SystemExit(f"BLOCKED: import anchor not found: {anchor}")
    return text.replace(anchor, anchor + "\n" + OVERLAY_IMPORT, 1)


def patch_historical(text: str) -> str:
    text = text.replace(CUSTOM_IMPORT + "\n", "").replace(CUSTOM_IMPORT, "")
    text = ensure_import(text, "import HilegaDecisionTable,{type HilegaAudit} from './hilegaDecisionTable'")
    if CUSTOM_HIST_TABLE in text:
        text = text.replace(CUSTOM_HIST_TABLE, ORIGINAL_HIST_TABLE, 1)
    elif ORIGINAL_HIST_TABLE not in text:
        raise SystemExit("BLOCKED: historical table block not found")

    old = """      const r=await fetch(`/api/live-shadow/hilega-historical/session?session_date=${encodeURIComponent(selectedDate)}`)
      if(!r.ok)throw new Error(`Session HTTP ${r.status}: ${await r.text()}`)
      setData(await r.json() as Response)"""
    new = """      const [r,dr]=await Promise.all([
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
    if new not in text:
        if old not in text:
            raise SystemExit("BLOCKED: historical load block not found")
        text = text.replace(old, new, 1)
    return text


def patch_live(text: str) -> str:
    text = text.replace(CUSTOM_IMPORT + "\n", "").replace(CUSTOM_IMPORT, "")
    text = ensure_import(text, "import HilegaDecisionTable,{type HilegaAudit} from './hilegaDecisionTable'")
    if CUSTOM_LIVE_TABLE in text:
        text = text.replace(CUSTOM_LIVE_TABLE, ORIGINAL_LIVE_TABLE, 1)
    elif ORIGINAL_LIVE_TABLE not in text:
        raise SystemExit("BLOCKED: live table block not found")

    old = """    const [s,a,d]=await Promise.all([get<Status>('/status'),get<AuditReport[]>('/audit-index?limit=200'),get<Dashboard>('/trade-dashboard')])
    setStatus(s);setRows(a);setDashboard(d);setError('')"""
    new = """    const [s,a,d,dr]=await Promise.all([
      get<Status>('/status'),
      get<AuditReport[]>('/audit-index?limit=200'),
      get<Dashboard>('/trade-dashboard'),
      fetch('/api/live-shadow/hilega-directional-candles/live'),
    ])
    let merged=a as HilegaAudit[]
    if(dr.ok){
      const directional=await dr.json()
      merged=overlayDirectionalAuditReports(a as HilegaAudit[],directional.rows??[])
    }
    setStatus(s);setRows(merged as AuditReport[]);setDashboard(d);setError('')"""
    if new not in text:
        if old not in text:
            raise SystemExit("BLOCKED: live refresh block not found")
        text = text.replace(old, new, 1)
    return text


def patch_decision_table(text: str) -> str:
    marker = "export function eventKind(r:HilegaAudit):Kind {"
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
    if helper.strip() not in text:
        if marker not in text:
            raise SystemExit("BLOCKED: eventKind marker missing")
        text = text.replace(marker, helper + marker, 1)

    text = text.replace(
        "if(String(r.strategy?.state_after??'').toUpperCase()==='BULLISH_ACTIVE')return 'ACTIVE'",
        "if(['BULLISH_ACTIVE','BEARISH_ACTIVE'].includes(String(r.strategy?.state_after??'').toUpperCase()))return 'ACTIVE'",
    )
    text = text.replace(
        "String(r.strategy?.state_after??'').toUpperCase()==='PATH1_ARMED')return 'DETECTED'",
        "['PATH1_ARMED','BEARISH_PATH1_ARMED'].includes(String(r.strategy?.state_after??'').toUpperCase()))return 'DETECTED'",
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

    text = text.replace("Decision: {displayDecisionText(displayKind)}", "Decision: {displayDecisionText(displayKind,reportDirection(r))}")
    text = text.replace("<b>BULLISH_ENTRY confirmed by {pathText(r)}</b>", "<b>{displayDecisionText('ENTRY',reportDirection(r))} confirmed by {pathText(r)}</b>")
    text = text.replace("<b>BULLISH_CONTINUATION</b><p>Recorded state remains BULLISH_ACTIVE", "<b>{displayDecisionText('ACTIVE',reportDirection(r))}</b><p>Recorded state remains {val(r.strategy?.state_after)}")
    text = text.replace("<b>BULLISH_EXIT</b><p>Recorded exit:", "<b>{displayDecisionText('EXIT',reportDirection(r))}</b><p>Recorded exit:")

    text = text.replace(
        "export function shortRuleText(r:HilegaAudit,kind:DisplayKind,lifecycleIssue?:string|null):string {\n  const path=pathText(r).toUpperCase()",
        "export function shortRuleText(r:HilegaAudit,kind:DisplayKind,lifecycleIssue?:string|null):string {\n  const direction=reportDirection(r)\n  const path=pathText(r).toUpperCase()",
    )
    text = text.replace("if(path.includes('ROUTE A'))return 'ENTRY · RSI↑EMA + RSI>50 + RSI>WMA'", "if(path.includes('ROUTE A'))return direction==='BEARISH'?'ENTRY · RSI↓EMA + RSI<50 + RSI<WMA':'ENTRY · RSI↑EMA + RSI>50 + RSI>WMA'")
    text = text.replace("if(path.includes('ROUTE B'))return 'ENTRY · ARMED + (RSI>WMA OR EMA>WMA) + RSI↑ + EMA↑'", "if(path.includes('ROUTE B'))return direction==='BEARISH'?'ENTRY · ARMED + (RSI<WMA OR EMA<WMA) + RSI↓ + EMA↓':'ENTRY · ARMED + (RSI>WMA OR EMA>WMA) + RSI↑ + EMA↑'")
    text = text.replace("if(kind==='ACTIVE')return 'CONTINUE · BULLISH_ACTIVE'", "if(kind==='ACTIVE')return `CONTINUE · ${direction}_ACTIVE`")
    text = text.replace("if(label.includes('RSI_CROSS_BELOW_WMA21'))return 'EXIT · RSI↓WMA21'", "if(label.includes('RSI_CROSS_BELOW_WMA21'))return 'EXIT · RSI↓WMA21'\n    if(label.includes('BEARISH_RSI_CROSS_ABOVE_WMA21'))return 'EXIT · RSI↑WMA21'")
    text = text.replace("return 'ARMED · RSI↑EMA'", "return direction==='BEARISH'?'ARMED · RSI↓EMA':'ARMED · RSI↑EMA'")
    return text


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--repo',required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--check',action='store_true')
    g.add_argument('--apply',action='store_true')
    a=ap.parse_args()
    repo=Path(a.repo).resolve()
    payload=Path(__file__).resolve().parent/'files'
    paths={
      'hist':repo/'frontend/src/hilegaHistoricalReplay.tsx',
      'live':repo/'frontend/src/hilegaMilegaShadow.tsx',
      'table':repo/'frontend/src/hilegaDecisionTable.tsx',
    }
    missing=[str(x) for x in paths.values() if not x.is_file()]
    if missing:
        raise SystemExit('BLOCKED: missing files:\n'+'\n'.join(missing))

    patch_historical(paths['hist'].read_text())
    patch_live(paths['live'].read_text())
    patch_decision_table(paths['table'].read_text())

    print('READY')
    print('  - restores original HilegaDecisionTable UI in historical and live')
    print('  - keeps same filters, columns, cards, audit expansion and CSS')
    print('  - overlays directional evidence onto existing reports')
    print('  - adds BEARISH_ENTRY / BEARISH_CONTINUATION / BEARISH_EXIT semantics')
    print('  - preserves bullish behavior when directional evidence is absent')
    print('  - no strategy/coordinator/CE/PE changes')
    print('  - frontend-only correction; no API/worker restart')
    if a.check:
        print('CHECK PASS')
        return

    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=repo/'.hilega-directional-ui-preserve-existing-v1-backup'/stamp
    for pth in paths.values():
        rel=pth.relative_to(repo)
        dst=backup/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(pth,dst)

    shutil.copy2(payload/'frontend/src/hilegaDirectionalAuditOverlay.ts', repo/'frontend/src/hilegaDirectionalAuditOverlay.ts')
    paths['hist'].write_text(patch_historical(paths['hist'].read_text()))
    paths['live'].write_text(patch_live(paths['live'].read_text()))
    paths['table'].write_text(patch_decision_table(paths['table'].read_text()))

    print('APPLY PASS')
    print('Backup:',backup)
    print('Next: cd frontend && npm run build')
    print('No API restart required.')
    print('Do not restart Hilega live-shadow worker.')

if __name__=='__main__':
    main()
