#!/usr/bin/env python3
from pathlib import Path

root = Path.cwd()
overlay = root / 'frontend/src/hilegaDirectionalAuditOverlay.ts'
decision = root / 'frontend/src/hilegaDecisionTable.tsx'

for p in (overlay, decision):
    if not p.is_file():
        raise SystemExit(f'STOP: missing {p}')
    b = p.with_suffix(p.suffix + '.bak-directional-audit-20260925')
    if not b.exists():
        b.write_text(p.read_text(encoding='utf-8'), encoding='utf-8')

# 1) Previous indicators for synthetic directional rows.
s = overlay.read_text(encoding='utf-8')
if 'const previousByMinute=' not in s:
    marker = "  const used=new Set<string>()\n\n  const applyOverlay=("
    insert = """  const used=new Set<string>()

  const previousByMinute=new Map<string,DirectionalCandleOverlayRow>()
  const chronological=[...rows].sort(
    (a,b)=>String(a.bar_timestamp).localeCompare(String(b.bar_timestamp))
  )
  let previous:DirectionalCandleOverlayRow|null=null
  for(const current of chronological){
    const key=minuteKey(current.bar_timestamp)
    if(!key)continue
    if(previous && String(previous.bar_timestamp).slice(0,10)===String(current.bar_timestamp).slice(0,10)){
      previousByMinute.set(key,previous)
    }
    previous=current
  }

  const applyOverlay=("""
    if marker not in s:
        raise SystemExit('STOP: overlay insertion marker not found')
    s = s.replace(marker, insert, 1)

old = """        previous_rsi9:
          null,

        previous_ema3_rsi:
          null,

        previous_wma21_rsi:
          null,"""
new = """        previous_rsi9:
          previousByMinute.get(key)?.rsi9 ?? null,

        previous_ema3_rsi:
          previousByMinute.get(key)?.ema3_rsi ?? null,

        previous_wma21_rsi:
          previousByMinute.get(key)?.wma21_rsi ?? null,"""
if old in s:
    s = s.replace(old, new, 1)
overlay.write_text(s, encoding='utf-8')

# 2) Direction-aware audit presentation.
s = decision.read_text(encoding='utf-8')

start = s.index('export function shortRuleText(')
end = s.index('\n// Build the visible lifecycle', start)
short_rule = r'''export function shortRuleText(
  r:HilegaAudit,
  kind:DisplayKind,
  lifecycleIssue?:string|null,
):string {
  const path=pathText(r).toUpperCase()
  const at=clock(r.checkpoint)
  const direction=reportDirection(r)

  if(kind==='ENTRY'){
    if(path.includes('OPENING')){
      return direction==='BEARISH'
        ? 'BEARISH ENTRY · 09:15 ALIGN <50 → 09:20 RSI<WMA → 09:25 RSI<WMA'
        : 'BULLISH ENTRY · 09:15 ALIGN >50 → 09:20 RSI>WMA → 09:25 RSI>WMA'
    }
    if(path.includes('ROUTE A')){
      return direction==='BEARISH'
        ? 'BEARISH ENTRY · RSI↓EMA + RSI<50 + RSI<WMA'
        : 'BULLISH ENTRY · RSI↑EMA + RSI>50 + RSI>WMA'
    }
    if(path.includes('ROUTE B')){
      return direction==='BEARISH'
        ? 'BEARISH ENTRY · ARMED + (RSI<WMA OR EMA<WMA) + RSI↓ + EMA↓'
        : 'BULLISH ENTRY · ARMED + (RSI>WMA OR EMA>WMA) + RSI↑ + EMA↑'
    }
    return `${direction} ENTRY · RECORDED STRATEGY TRANSITION`
  }
  if(kind==='ACTIVE')return `CONTINUE · ${direction}_ACTIVE`
  if(kind==='EXIT'){
    const ev=checkpointTransitions(r).find(isExit)
    const label=String(ev?.event_type??list(r.strategy?.events_emitted).find((x:any)=>String(x).includes('EXIT'))??'')
    if(label.includes('STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21'))return 'BEARISH EXIT · RSI↑WMA21'
    if(label.includes('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'))return 'BULLISH EXIT · RSI↓WMA21'
    if(label.includes('CUTOFF')||at==='14:55')return `${direction} EXIT · 14:55 CUTOFF`
    return `${direction} EXIT · RECORDED EXIT RULE`
  }
  if(kind==='DETECTED')return `${direction} · ARMED / CANDIDATE`
  if(kind==='REJECTED')return 'REJECTED · ENTRY CONDITIONS FAILED'
  if(kind==='REVIEW')return `REVIEW · ${lifecycleIssue??'LIFECYCLE'}`
  return 'NO_SIGNAL'
}
'''
s = s[:start] + short_rule + s[end:]

# Rename the CE table and make side label dynamic while preserving lifecycle math.
s = s.replace('function CeTable(', 'function OptionTable(', 1)
s = s.replace(
    '  const raw=reportedLegs(r,allowedUntil,displayKind)',
    "  const direction=reportDirection(r)\n  const side=direction==='BEARISH'?'PE':'CE'\n  const raw=reportedLegs(r,allowedUntil,displayKind)",
    1,
)
s = s.replace(
    'No five-strike CE lifecycle rows are recorded for this checkpoint. Open a linked entry or exit candle when available.',
    'No five-strike {side} lifecycle rows are recorded for this checkpoint. Signal evidence remains valid; missing option evidence is not zero P&L.',
    1,
)
s = s.replace('<th>CE</th><th>Instrument</th>', '<th>{side}</th><th>Instrument</th>', 1)
s = s.replace('<CeTable r={r} allowedUntil={allowedUntil} displayKind={displayKind}/>', '<OptionTable r={r} allowedUntil={allowedUntil} displayKind={displayKind}/>', 1)
s = s.replace('Five independent CE contracts — exact historical/live observations', 'Five independent {side} contracts — exact historical/live observations', 1)
s = s.replace('Loading linked CE lifecycle…', 'Loading linked directional option lifecycle…')

# Add directional validation helpers before Detail.
start = s.index('function Detail(')
end = s.index('\nexport default function HilegaDecisionTable', start)

detail = r'''type DirectionalAuditCheck={label:string;result:boolean|null;evidence:string}
const indicatorValue=(r:HilegaAudit|undefined,key:string):number|null=>!r?null:finiteNumber(r.indicators?.[key])
const fmtIndicator=(v:number|null):string=>v===null?'—':Number(v).toFixed(2)
const checkpointTime=(r:HilegaAudit):string=>clock(r.checkpoint).slice(0,5)
const sessionReports=(reports:HilegaAudit[],r:HilegaAudit):HilegaAudit[]=>{
  const day=String(r.checkpoint).slice(0,10)
  return reports.filter(x=>String(x.checkpoint).slice(0,10)===day)
}
const reportAt=(reports:HilegaAudit[],r:HilegaAudit,hhmm:string):HilegaAudit|undefined=>sessionReports(reports,r).find(x=>checkpointTime(x)===hhmm)
const previousReport=(reports:HilegaAudit[],r:HilegaAudit):HilegaAudit|undefined=>sessionReports(reports,r).filter(x=>x.checkpoint<r.checkpoint).sort((a,b)=>a.checkpoint.localeCompare(b.checkpoint)).at(-1)
const priorArm=(reports:HilegaAudit[],r:HilegaAudit,direction:'BULLISH'|'BEARISH'):HilegaAudit|undefined=>{
  const target=direction==='BEARISH'?'BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN':'PATH1_ARMED_RSI_CROSS_EMA3_UP'
  return sessionReports(reports,r).filter(x=>x.checkpoint<=r.checkpoint&&list(x.strategy?.events_emitted).some((e:any)=>String(e)===target)).sort((a,b)=>a.checkpoint.localeCompare(b.checkpoint)).at(-1)
}

function directionalAuditChecks(r:HilegaAudit,reports:HilegaAudit[]):DirectionalAuditCheck[]{
  const direction=reportDirection(r),path=pathText(r).toUpperCase(),kind=eventKind(r)
  const cr=indicatorValue(r,'rsi9'),ce=indicatorValue(r,'ema3_rsi'),cw=indicatorValue(r,'wma21_rsi')
  const prev=previousReport(reports,r)
  const pr=indicatorValue(prev,'rsi9')??indicatorValue(r,'previous_rsi9')
  const pe=indicatorValue(prev,'ema3_rsi')??indicatorValue(r,'previous_ema3_rsi')
  const pw=indicatorValue(prev,'wma21_rsi')??indicatorValue(r,'previous_wma21_rsi')
  const known=(...v:Array<number|null>)=>v.every(x=>x!==null)
  const out:DirectionalAuditCheck[]=[]

  if(kind==='ENTRY'&&path.includes('OPENING')){
    const a=reportAt(reports,r,'09:15'),b=reportAt(reports,r,'09:20'),c=reportAt(reports,r,'09:25')
    const aR=indicatorValue(a,'rsi9'),aE=indicatorValue(a,'ema3_rsi'),aW=indicatorValue(a,'wma21_rsi')
    const bR=indicatorValue(b,'rsi9'),bW=indicatorValue(b,'wma21_rsi')
    const cR=indicatorValue(c,'rsi9'),cW=indicatorValue(c,'wma21_rsi')
    if(direction==='BEARISH'){
      out.push({label:'09:15 RSI, EMA and WMA below 50',result:known(aR,aE,aW)?[aR,aE,aW].every(x=>Number(x)<50):null,evidence:`RSI ${fmtIndicator(aR)} · EMA ${fmtIndicator(aE)} · WMA ${fmtIndicator(aW)}`})
      out.push({label:'09:15 RSI < EMA < WMA',result:known(aR,aE,aW)?Number(aR)<Number(aE)&&Number(aE)<Number(aW):null,evidence:`${fmtIndicator(aR)} < ${fmtIndicator(aE)} < ${fmtIndicator(aW)}`})
      out.push({label:'09:20 RSI < WMA21',result:known(bR,bW)?Number(bR)<Number(bW):null,evidence:`RSI ${fmtIndicator(bR)} · WMA ${fmtIndicator(bW)}`})
      out.push({label:'09:25 RSI < WMA21',result:known(cR,cW)?Number(cR)<Number(cW):null,evidence:`RSI ${fmtIndicator(cR)} · WMA ${fmtIndicator(cW)}`})
    }else{
      out.push({label:'09:15 RSI, EMA and WMA above 50',result:known(aR,aE,aW)?[aR,aE,aW].every(x=>Number(x)>50):null,evidence:`RSI ${fmtIndicator(aR)} · EMA ${fmtIndicator(aE)} · WMA ${fmtIndicator(aW)}`})
      out.push({label:'09:15 RSI > EMA > WMA',result:known(aR,aE,aW)?Number(aR)>Number(aE)&&Number(aE)>Number(aW):null,evidence:`${fmtIndicator(aR)} > ${fmtIndicator(aE)} > ${fmtIndicator(aW)}`})
      out.push({label:'09:20 RSI > WMA21',result:known(bR,bW)?Number(bR)>Number(bW):null,evidence:`RSI ${fmtIndicator(bR)} · WMA ${fmtIndicator(bW)}`})
      out.push({label:'09:25 RSI > WMA21',result:known(cR,cW)?Number(cR)>Number(cW):null,evidence:`RSI ${fmtIndicator(cR)} · WMA ${fmtIndicator(cW)}`})
    }
    return out
  }

  if(kind==='ENTRY'&&path.includes('ROUTE A')){
    if(direction==='BEARISH'){
      out.push({label:'Fresh RSI cross below EMA',result:known(pr,pe,cr,ce)?Number(pr)>=Number(pe)&&Number(cr)<Number(ce):null,evidence:`RSI ${fmtIndicator(pr)} → ${fmtIndicator(cr)} · EMA ${fmtIndicator(pe)} → ${fmtIndicator(ce)}`})
      out.push({label:'RSI < 50',result:cr===null?null:cr<50,evidence:`RSI ${fmtIndicator(cr)}`})
      out.push({label:'RSI < WMA21',result:known(cr,cw)?Number(cr)<Number(cw):null,evidence:`RSI ${fmtIndicator(cr)} · WMA ${fmtIndicator(cw)}`})
    }else{
      out.push({label:'Fresh RSI cross above EMA',result:known(pr,pe,cr,ce)?Number(pr)<=Number(pe)&&Number(cr)>Number(ce):null,evidence:`RSI ${fmtIndicator(pr)} → ${fmtIndicator(cr)} · EMA ${fmtIndicator(pe)} → ${fmtIndicator(ce)}`})
      out.push({label:'RSI > 50',result:cr===null?null:cr>50,evidence:`RSI ${fmtIndicator(cr)}`})
      out.push({label:'RSI > WMA21',result:known(cr,cw)?Number(cr)>Number(cw):null,evidence:`RSI ${fmtIndicator(cr)} · WMA ${fmtIndicator(cw)}`})
    }
    return out
  }

  if(kind==='ENTRY'&&path.includes('ROUTE B')){
    const arm=priorArm(reports,r,direction)
    out.push({label:`${direction} Route B armed previously`,result:Boolean(arm),evidence:arm?`Arm recorded at ${clock(arm.checkpoint)} IST`:'No prior arm event found'})
    if(direction==='BEARISH'){
      out.push({label:'RSI < WMA21 OR EMA < WMA21',result:known(cr,ce,cw)?Number(cr)<Number(cw)||Number(ce)<Number(cw):null,evidence:`RSI ${fmtIndicator(cr)} · EMA ${fmtIndicator(ce)} · WMA ${fmtIndicator(cw)}`})
      out.push({label:'RSI falling',result:known(pr,cr)?Number(cr)<Number(pr):null,evidence:`RSI ${fmtIndicator(pr)} → ${fmtIndicator(cr)}`})
      out.push({label:'EMA falling',result:known(pe,ce)?Number(ce)<Number(pe):null,evidence:`EMA ${fmtIndicator(pe)} → ${fmtIndicator(ce)}`})
    }else{
      out.push({label:'RSI > WMA21 OR EMA > WMA21',result:known(cr,ce,cw)?Number(cr)>Number(cw)||Number(ce)>Number(cw):null,evidence:`RSI ${fmtIndicator(cr)} · EMA ${fmtIndicator(ce)} · WMA ${fmtIndicator(cw)}`})
      out.push({label:'RSI rising',result:known(pr,cr)?Number(cr)>Number(pr):null,evidence:`RSI ${fmtIndicator(pr)} → ${fmtIndicator(cr)}`})
      out.push({label:'EMA rising',result:known(pe,ce)?Number(ce)>Number(pe):null,evidence:`EMA ${fmtIndicator(pe)} → ${fmtIndicator(ce)}`})
    }
    return out
  }

  if(kind==='EXIT'){
    if(direction==='BEARISH')out.push({label:'Fresh RSI cross above WMA21',result:known(pr,pw,cr,cw)?Number(pr)<=Number(pw)&&Number(cr)>Number(cw):null,evidence:`RSI ${fmtIndicator(pr)} → ${fmtIndicator(cr)} · WMA ${fmtIndicator(pw)} → ${fmtIndicator(cw)}`})
    else out.push({label:'Fresh RSI cross below WMA21',result:known(pr,pw,cr,cw)?Number(pr)>=Number(pw)&&Number(cr)<Number(cw):null,evidence:`RSI ${fmtIndicator(pr)} → ${fmtIndicator(cr)} · WMA ${fmtIndicator(pw)} → ${fmtIndicator(cw)}`})
  }
  return out
}

function Detail({r,reports,allowedUntil,origin,originRoute,displayKind,lifecycleIssue}:{r:HilegaAudit;reports:HilegaAudit[];allowedUntil?:string;origin?:string|null;originRoute?:string|null;displayKind:DisplayKind;lifecycleIssue?:string|null}){
  const cand=r.bar??{},ind=r.indicators??{},direction=reportDirection(r),side=direction==='BEARISH'?'PE':'CE'
  const entry=checkpointTransitions(r).find(isEntry),exit=checkpointTransitions(r).find(isExit)
  const checks=directionalAuditChecks(r,reports)
  const reasons=[...list(r.route_a?.fail_reasons),...list(r.route_b?.fail_reasons)]
  const snapshotTime=r.option_market_snapshot?.signal_boundary
  const visibleSnapshot=allowedUntil===undefined||reached(snapshotTime,allowedUntil)
  return <div className="hd-audit">
    <div className="hd-cards">
      <article><b>Nifty candle</b><span>{clock(r.checkpoint)} IST</span><span>O {val(cand.open)} · H {val(cand.high)} · L {val(cand.low)} · C {val(cand.close)}</span><span>Volume {val(cand.volume)}</span></article>
      <article><b>Indicators</b><span>RSI9 {money(ind.rsi9)} (prev {money(ind.previous_rsi9)})</span><span>EMA3(RSI) {money(ind.ema3_rsi)} (prev {money(ind.previous_ema3_rsi)})</span><span>WMA21(RSI) {money(ind.wma21_rsi)} (prev {money(ind.previous_wma21_rsi)})</span></article>
      <article><b>Strategy state</b><span>Direction: {direction}</span><span>{val(r.strategy?.state_before)} → {val(r.strategy?.state_after)}</span><span>Decision: {displayDecisionText(displayKind,direction)}</span><span>Original entry route: {originRoute??pathText(r)}</span><span>Entry signal candle: {origin?clock(origin):displayKind==='ENTRY'?clock(r.checkpoint):'Not available in current timeline'}</span></article>
      <article><b>Entry / exit</b><span>Entry: {entry?`${eventAt(entry,r)} · Nifty ${money(entry.price)}`:'Not detected'}</span><span>Exit: {exit?`${eventAt(exit,r)} · Nifty ${money(exit.price)}`:'Not detected'}</span><span>Reason: {val(exit?.exit_reason??exit?.event_type)}</span></article>
    </div>
    {displayKind==='ENTRY'&&<div className="hd-entry-reason"><b>{displayDecisionText('ENTRY',direction)} confirmed by {pathText(r)}</b><p>Recorded directional event is authoritative. Checks below are read-only validation and do not create signals.</p></div>}
    {displayKind==='ACTIVE'&&<div className="hd-continuation-reason"><b>{displayDecisionText('ACTIVE',direction)}</b><p>Recorded owner/state remains active and no directional exit was emitted for this candle.</p></div>}
    {displayKind==='EXIT'&&<div className="hd-exit-reason"><b>{displayDecisionText('EXIT',direction)}</b><p>Recorded exit: {val(exit?.exit_reason??exit?.event_type??list(r.strategy?.events_emitted).find((x:any)=>String(x).includes('EXIT')))}. Original entry signal: {origin?clock(origin):'not available in current timeline'}.</p></div>}
    {displayKind==='REVIEW'&&<div className="hd-review-reason"><b>REVIEW_REQUIRED</b><p>{val(lifecycleIssue)}. Raw evidence is preserved; UI does not promote unsupported lifecycle state.</p></div>}
    <h4>{direction} {pathText(r)} validation</h4>
    {checks.length?<div className="hd-scroll"><table className="hd-table"><thead><tr><th>Check</th><th>Result</th><th>Canonical evidence</th></tr></thead><tbody>{checks.map((x,i)=><tr key={`${x.label}-${i}`}><td>{x.label}</td><td><span className={`hd-badge ${x.result===true?'hd-pass':x.result===false?'hd-fail':'hd-neutral'}`}>{score(x.result)}</span></td><td>{x.evidence}</td></tr>)}</tbody></table></div>:<p className="hd-muted">No additional route-specific validation is required for this checkpoint.</p>}
    {reasons.length>0&&<p className="hd-muted">Recorded rejection reasons: {reasons.map(String).join(' · ')}</p>}
    <h4>Five independent {side} contracts — exact historical/live observations</h4>
    <p>Expiry {val(r.option_candidate?.expiry)} · ATM {val(r.option_candidate?.atm)} · Candidate {val(r.option_candidate?.status)} · Market data {visibleSnapshot?val(r.option_market_snapshot?.status):'NOT YET AVAILABLE'}</p>
    <OptionTable r={r} allowedUntil={allowedUntil} displayKind={displayKind}/>
    <details><summary>Recorded candidate selection and option-market snapshot</summary><pre>{json({candidate:r.option_candidate,snapshot:visibleSnapshot?r.option_market_snapshot:'Not yet available at selected candle'})}</pre></details>
    <details><summary>Strategy transitions and recorded decision evidence</summary><pre>{json({strategy:r.strategy,route_a:r.route_a,route_b:r.route_b,transitions:r.transitions})}</pre></details>
    <details><summary>Audit integrity and recorded source events</summary><p>Full-capture hash-chain check: {r.audit_integrity?.chain_ok===true?'PASS':r.audit_integrity?.chain_ok===false?'FAIL':'NOT VERIFIED'}</p><pre>{json(allowedUntil===undefined?r.audit_integrity:{...r.audit_integrity,records:list(r.audit_integrity?.records).filter((x:any)=>reached(x.event_time??x.checkpoint,allowedUntil))})}</pre></details>
  </div>
}
'''
s = s[:start] + detail + s[end:]

old = '<Detail r={report} origin={origin} originRoute={originRoute} displayKind={k} lifecycleIssue={lifecycleIssue} allowedUntil={candleBoundary(r.checkpoint)}/>'
new = '<Detail r={report} reports={ordered} origin={origin} originRoute={originRoute} displayKind={k} lifecycleIssue={lifecycleIssue} allowedUntil={candleBoundary(r.checkpoint)}/>'
if old in s:
    s = s.replace(old, new, 1)
elif 'reports={ordered}' not in s:
    raise SystemExit('STOP: Detail invocation not found')

s = s.replace('ENTRY_WHILE_BULLISH_ACTIVE','ENTRY_WHILE_DIRECTIONAL_ACTIVE')
decision.write_text(s, encoding='utf-8')
print('PATCHED:', overlay)
print('PATCHED:', decision)
print('DONE')
