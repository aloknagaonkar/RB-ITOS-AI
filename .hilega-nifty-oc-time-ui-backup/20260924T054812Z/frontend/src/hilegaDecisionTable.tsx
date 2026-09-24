import { Fragment, useEffect, useMemo, useState } from 'react'
import './hilegaDecisionTable.css'

/* Pure presentation of canonical Hilega audit reports. No strategy decisions are
   recalculated, no market requests are made, and no execution APIs are called. */
export type HilegaAudit = {
  checkpoint: string
  linked_signal_bar?: string
  bar?: Record<string, any>
  indicators?: Record<string, any>
  conditions?: Record<string, any>
  strategy?: Record<string, any>
  route_a?: Record<string, any>
  route_b?: Record<string, any>
  transitions?: Array<Record<string, any>>
  option_candidate?: Record<string, any> | null
  option_market_snapshot?: Record<string, any> | null
  option_lifecycle?: Record<string, any> | null
  projection?: Record<string, any> | null
  audit_integrity?: Record<string, any>
  safety?: Record<string, any>
}
type Filter = 'ALL' | 'DETECTED' | 'ENTRY' | 'EXIT' | 'ACTIVE' | 'REJECTED' | 'REVIEW'
type Kind = 'DETECTED' | 'ENTRY' | 'EXIT' | 'ACTIVE' | 'REJECTED' | 'NONE'
export type DisplayKind = Kind | 'REVIEW'
const list = (x:unknown): any[] => Array.isArray(x) ? x : []
const val = (x:any) => x===undefined || x===null || x==='' ? '—' : String(x)
const money = (x:any) => x===undefined || x===null || !Number.isFinite(Number(x)) ? '—' : Number(x).toFixed(2)
const pct = (x:any) => x===undefined || x===null || !Number.isFinite(Number(x)) ? '—' : `${Number(x).toFixed(2)}%`
const clock = (x:any) => {
  if(!x)return '—'
  const d=new Date(String(x))
  return Number.isNaN(d.getTime())?String(x):d.toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false,hour:'2-digit',minute:'2-digit'})
}
export const shortDateTime = (x:any) => {
  if(!x)return '—'
  const d=new Date(String(x))
  if(Number.isNaN(d.getTime()))return String(x)
  const parts=new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).formatToParts(d)
  const get=(t:string)=>parts.find(x=>x.type===t)?.value??''
  return `${get('month')}/${get('day')} ${get('hour')}:${get('minute')}`
}

const candleTiming=(r:HilegaAudit)=>{
  const start=new Date(String(r.checkpoint))
  if(Number.isNaN(start.getTime()))return {window:shortDateTime(r.checkpoint),processed:null as string|null,label:null as string|null}
  const end=new Date(start.getTime()+5*60_000)
  const day=new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',month:'2-digit',day:'2-digit'}).format(start)
  const hm=(d:Date)=>d.toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false,hour:'2-digit',minute:'2-digit'})
  const hms=(x:any)=>{
    if(!x)return null
    const d=new Date(String(x))
    return Number.isNaN(d.getTime())?null:d.toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'})
  }
  const records=list(r.audit_integrity?.records)
  const processed=records.find((x:any)=>x.stage==='UNDERLYING_5M_BUILD')
  const recovered=records.find((x:any)=>x.stage==='BOOTSTRAP_RECOVERED_CHECKPOINT')
  return {
    window:`${day} ${hm(start)}–${hm(end)}`,
    processed:hms(processed?.event_time??recovered?.event_time),
    label:processed?'processed':recovered?'recovered':null,
  }
}
const json=(v:unknown)=>JSON.stringify(v??{},null,2)
const isEntry=(x:any)=>String(x?.event_type??'').startsWith('ENTRY_')
const isExit=(x:any)=>String(x?.event_type??'').includes('EXIT')
const transitions=(r:HilegaAudit)=>list(r.transitions)
const sameInstant=(a:any,b:any):boolean=>{
  if(!a||!b)return false
  const ams=new Date(String(a)).getTime(),bms=new Date(String(b)).getTime()
  if(Number.isFinite(ams)&&Number.isFinite(bms))return ams===bms
  return String(a)===String(b)
}
// Canonical audit reports deliberately include linked lifecycle evidence so an
// entry row can show the eventual CE exit. Those linked future transitions must
// never classify the *current candle*. Only transitions whose event_time is the
// current checkpoint are eligible for the row's decision label.
export const checkpointTransitions=(r:HilegaAudit)=>transitions(r).filter(t=>sameInstant(t?.event_time,r.checkpoint))
// Display classifications are derived from the current checkpoint's strategy
// transition/result only. Explicit ENTRY is checked before EXIT so a linked
// future exit attached to an entry audit can never overwrite BULLISH_ENTRY.
export function eventKind(r:HilegaAudit):Kind {
  const t=checkpointTransitions(r)
  const events=list(r.strategy?.events_emitted).map(String)
  if(t.some(isEntry)||events.some(x=>x.startsWith('ENTRY_')))return 'ENTRY'
  if(t.some(isExit)||events.some(x=>x.includes('EXIT')))return 'EXIT'
  if(String(r.strategy?.state_after??'').toUpperCase()==='BULLISH_ACTIVE')return 'ACTIVE'
  if(events.some(x=>x.includes('REJECTED')))return 'REJECTED'
  if(events.some(x=>/CANDIDATE|ARMED|DETECT|OPENING_HOLD/.test(x)) ||
     String(r.strategy?.state_after??'').toUpperCase()==='PATH1_ARMED')return 'DETECTED'
  return 'NONE'
}
export function decisionText(r:HilegaAudit):string {
  switch(eventKind(r)) {
    case 'ENTRY':return 'BULLISH_ENTRY'
    case 'ACTIVE':return 'BULLISH_CONTINUATION'
    case 'EXIT':return 'BULLISH_EXIT'
    case 'DETECTED':return 'ARMED / OPENING CANDIDATE'
    case 'REJECTED':return 'SETUP REJECTED'
    default:return 'NO_SIGNAL'
  }
}
export function displayDecisionText(kind:DisplayKind):string {
  switch(kind){
    case 'ENTRY':return 'BULLISH_ENTRY'
    case 'ACTIVE':return 'BULLISH_CONTINUATION'
    case 'EXIT':return 'BULLISH_EXIT'
    case 'DETECTED':return 'ARMED / OPENING CANDIDATE'
    case 'REJECTED':return 'SETUP REJECTED'
    case 'REVIEW':return 'REVIEW_REQUIRED'
    default:return 'NO_SIGNAL'
  }
}
// Preserve the original entry route on continuation and exit, when earlier
// records in the currently available timeline prove it. Never infer an origin
// from a later successful trade or a future candle.
export function pathText(r:HilegaAudit,carriedRoute?:string):string {
  const route=r.strategy?.selected_route
  if(route)return String(route).replaceAll('_',' ')
  const events=list(r.strategy?.events_emitted).map(String)
  const origin=checkpointTransitions(r).find(isEntry)
  const source=origin?.source
  if(source)return String(source).replaceAll('_',' ')
  if(events.some(x=>x.startsWith('OPENING_')) || [r.strategy?.state_before,r.strategy?.state_after].some(x=>String(x??'').startsWith('OPENING_')))return 'Opening path'
  if(carriedRoute)return carriedRoute
  if(r.route_a?.eligible===true && r.route_b?.eligible===true)return 'Route A / Route B'
  if(r.route_a?.eligible===true)return 'Route A'
  if(r.route_b?.eligible===true)return 'Route B'
  if(eventKind(r)==='ACTIVE'||eventKind(r)==='EXIT')return 'Entry route not in available records'
  if(r.strategy?.state_after)return val(r.strategy.state_after).replaceAll('_',' ')
  return 'Not evaluated'
}
export type DecisionRow = {
  report:HilegaAudit
  origin:string|null
  originRoute:string|null
  entryNifty:number|null
  niftyPoints:number|null
  rawKind:Kind
  displayKind:DisplayKind
  lifecycleIssue:string|null
}
const explicitOrigin=(r:HilegaAudit):string|null=>{
  const direct=r.linked_signal_bar
  if(direct)return String(direct)
  const exit=checkpointTransitions(r).find(isExit)
  const linked=exit?.details?.original_entry_time
  return linked?String(linked):null
}
const finiteNumber=(x:any):number|null=>x===null||x===undefined||x===''||!Number.isFinite(Number(x))?null:Number(x)
const currentNifty=(r:HilegaAudit):number|null=>finiteNumber(r.bar?.close)
const entryNiftyAt=(r:HilegaAudit):number|null=>{
  const entry=checkpointTransitions(r).find(isEntry)
  // Canonical entries use transition price. Restart-reconstructed entries also
  // expose the recorded signal_spot as the projected transition price. Never
  // infer an entry from a later continuation candle.
  return finiteNumber(entry?.price??entry?.entry_price??r.bar?.close)
}
export function niftyPointsFromEntry(current:any,entry:any):number|null {
  const c=finiteNumber(current),e=finiteNumber(entry)
  return c===null||e===null?null:c-e
}
export function shortRuleText(r:HilegaAudit,kind:DisplayKind,lifecycleIssue?:string|null):string {
  const path=pathText(r).toUpperCase()
  const at=clock(r.checkpoint)
  if(kind==='ENTRY'){
    if(String(r.projection?.kind??'')==='RECONSTRUCTED_ENTRY'){
      if(path.includes('ROUTE A'))return 'ENTRY · RECONSTRUCTED · ROUTE A'
      if(path.includes('ROUTE B'))return 'ENTRY · RECONSTRUCTED · ROUTE B'
      if(path.includes('OPENING'))return 'ENTRY · RECONSTRUCTED · OPENING PATH'
      return 'ENTRY · RECONSTRUCTED FROM RECORDED LIFECYCLE'
    }
    if(path.includes('OPENING'))return 'ENTRY · OPEN 09:15 ALIGN → 09:20 RSI>WMA → 09:25 RSI>WMA'
    if(path.includes('ROUTE A'))return 'ENTRY · RSI↑EMA + RSI>50 + RSI>WMA'
    if(path.includes('ROUTE B'))return 'ENTRY · ARMED + (RSI>WMA OR EMA>WMA) + RSI↑ + EMA↑'
    return 'ENTRY · RECORDED STRATEGY TRANSITION'
  }
  if(kind==='ACTIVE')return 'CONTINUE · BULLISH_ACTIVE'
  if(kind==='EXIT'){
    const ev=checkpointTransitions(r).find(isExit)
    const label=String(ev?.event_type??list(r.strategy?.events_emitted).find((x:any)=>String(x).includes('EXIT'))??'')
    if(label.includes('RSI_CROSS_BELOW_WMA21'))return 'EXIT · RSI↓WMA21'
    if(label.includes('CUTOFF')||at==='14:55')return 'EXIT · 14:55 CUTOFF'
    return 'EXIT · RECORDED EXIT RULE'
  }
  if(kind==='DETECTED'){
    if(path.includes('OPENING')){
      if(at==='09:15')return 'OPENING · RSI>50 + EMA>50 + WMA>50 + RSI>EMA>WMA'
      return 'OPENING · RSI>WMA21'
    }
    return 'ARMED · RSI↑EMA'
  }
  if(kind==='REJECTED')return 'REJECTED · ENTRY CONDITIONS FAILED'
  if(kind==='REVIEW')return `REVIEW · ${lifecycleIssue??'LIFECYCLE'}`
  return 'NO_SIGNAL'
}

// Build the visible lifecycle strictly in chronological order. A recorded exit
// cannot become BULLISH_EXIT unless a prior BULLISH_ENTRY is active (or the
// audit explicitly links the row to an earlier entry outside the loaded
// window). Likewise, continuation requires an active entry. This prevents raw
// exit/active fragments from creating impossible UI sequences.
export function deriveDecisionRows(reports:HilegaAudit[]):DecisionRow[] {
  let active=false,origin:string|null=null,originRoute:string|null=null,entryNifty:number|null=null,sessionDate:string|null=null
  return [...reports].sort((a,b)=>a.checkpoint.localeCompare(b.checkpoint)).map(report=>{
    const date=report.checkpoint.slice(0,10)
    if(sessionDate!==date){active=false;origin=null;originRoute=null;entryNifty=null;sessionDate=date}
    const rawKind=eventKind(report)
    const linked=explicitOrigin(report)
    let displayKind:DisplayKind=rawKind
    let lifecycleIssue:string|null=null

    if(rawKind==='ENTRY'){
      if(active){
        displayKind='REVIEW'
        lifecycleIssue='ENTRY_WHILE_BULLISH_ACTIVE'
      }else{
        displayKind='ENTRY'
        active=true
        origin=report.checkpoint
        originRoute=pathText(report)
        entryNifty=entryNiftyAt(report)
      }
    }else if(rawKind==='EXIT'){
      if(active){
        displayKind='EXIT'
        if(linked)origin=linked
      }else if(linked){
        // Valid when a live/replay API returns a window beginning after entry.
        displayKind='EXIT'
        origin=linked
        originRoute=pathText(report,originRoute??undefined)
        entryNifty=finiteNumber(checkpointTransitions(report).find(isExit)?.details?.original_entry_price)
      }else{
        displayKind='REVIEW'
        lifecycleIssue='EXIT_WITHOUT_BULLISH_ENTRY'
      }
    }else if(active){
      if(String(report.strategy?.state_after??'').toUpperCase()==='SESSION_LOCKED'){
        displayKind='REVIEW'
        lifecycleIssue='SESSION_LOCKED_WITHOUT_BULLISH_EXIT'
      }else{
        // Once entered, every completed candle is continuation until a genuine
        // recorded exit, regardless of unrelated candidate/rejection fragments.
        displayKind='ACTIVE'
      }
    }else if(rawKind==='ACTIVE'){
      if(linked){
        displayKind='ACTIVE'
        active=true
        origin=linked
        originRoute=pathText(report)
        entryNifty=finiteNumber(report.strategy?.original_entry_price)
      }else{
        displayKind='REVIEW'
        lifecycleIssue='CONTINUATION_WITHOUT_BULLISH_ENTRY'
      }
    }

    const niftyPoints=(displayKind==='ENTRY'||displayKind==='ACTIVE'||displayKind==='EXIT')?niftyPointsFromEntry(currentNifty(report),entryNifty):null
    const result:DecisionRow={report,origin,originRoute,entryNifty,niftyPoints,rawKind,displayKind,lifecycleIssue}
    if(displayKind==='EXIT'){
      active=false
      origin=null
      originRoute=null
      entryNifty=null
    }else if(displayKind==='REVIEW' && lifecycleIssue==='SESSION_LOCKED_WITHOUT_BULLISH_EXIT'){
      active=false
      origin=null
      originRoute=null
      entryNifty=null
    }
    return result
  })
}
function score(v:any):string {return v===true?'PASS':v===false?'FAIL':'NOT EVALUATED'}
function evidence(key:string,i:Record<string,any>):string {
  const f=(k:string)=>money(i[k]); const pair=(l:string,a:string,b:string)=>`${l}: ${f(a)} → ${f(b)}`
  switch(key){
    case 'rsi_cross_ema_up':return `${pair('RSI', 'previous_rsi9', 'rsi9')}; ${pair('EMA','previous_ema3_rsi','ema3_rsi')}`
    case 'rsi_cross_wma_down':return `${pair('RSI','previous_rsi9','rsi9')}; ${pair('WMA','previous_wma21_rsi','wma21_rsi')}`
    case 'rsi_gt_50':return `RSI ${f('rsi9')}; threshold 50`
    case 'rsi_gt_wma':return `RSI ${f('rsi9')}; WMA ${f('wma21_rsi')}`
    case 'ema_gt_wma':return `EMA ${f('ema3_rsi')}; WMA ${f('wma21_rsi')}`
    case 'rsi_rising':return pair('RSI','previous_rsi9','rsi9')
    case 'ema_rising':return pair('EMA','previous_ema3_rsi','ema3_rsi')
    case 'full_alignment':return `RSI ${f('rsi9')}; EMA ${f('ema3_rsi')}; WMA ${f('wma21_rsi')}`
    default:return '—'
  }
}
const conditionNames:Record<string,string>={
  rsi_cross_ema_up:'RSI crosses above EMA',rsi_cross_wma_down:'RSI crosses below WMA',
  rsi_gt_50:'RSI > 50',rsi_gt_wma:'RSI > WMA21',ema_gt_wma:'EMA > WMA21',
  rsi_rising:'RSI rising',ema_rising:'EMA rising',full_alignment:'Full opening alignment'
}
// Compare actual instants rather than lexicographically comparing ISO offsets.
function reached(timestamp:any,cutoff?:string):boolean {
  if(!timestamp)return false
  if(cutoff===undefined)return true
  const a=new Date(String(timestamp)).getTime(),b=new Date(cutoff).getTime()
  return Number.isFinite(a)&&Number.isFinite(b)&&a<=b
}
function candleBoundary(checkpoint?:string):string|undefined {
  if(!checkpoint)return undefined
  const ms=new Date(checkpoint).getTime()
  return Number.isFinite(ms)?new Date(ms+5*60*1000).toISOString():undefined
}
// Recorded legs are preferred to candidate data; chronological review uses
// only snapshots provably available by the selected candle's completion.
export function reportedLegs(r:HilegaAudit,asOf?:string,phase?:DisplayKind){
  const l=r.option_lifecycle??{}
  const start=list(l.start?.legs)
  const updates=list(l.updates)
  const final=list(l.exit?.legs)

  // Entry rows may expose the exact causal CE entry once it is recorded, but
  // never an eventual exit/P&L that happened later in the same trade.
  if(phase==='ENTRY'){
    if(start.length)return start
    const firstWithEntry=updates.find((u:any)=>list(u?.legs).some((x:any)=>x?.entry_timestamp || number(x?.entry_open)!==null))
    return list(firstWithEntry?.legs)
  }

  // Continuation rows are checkpoint-progressive. They can use only option
  // updates that were available by the end of this 5-minute row. A linked
  // terminal exit is intentionally ignored until the BULLISH_EXIT row.
  if(phase==='ACTIVE'){
    const visible=asOf===undefined?updates:updates.filter((u:any)=>reached(u.latest_completed_minute??u.event_time,asOf))
    const candidate=visible.at(-1)
    if(candidate&&list(candidate.legs).length)return list(candidate.legs)
    return start
  }

  // Exit rows may show the exact terminal option observation associated with
  // that strategy exit. If the exact exit is still pending, fall back to the
  // latest non-terminal lifecycle state and leave realized P&L unavailable.
  if(phase==='EXIT'){
    if(final.length)return final
    if(updates.length&&list(updates.at(-1)?.legs).length)return list(updates.at(-1).legs)
    return start
  }

  // Neutral/backward-compatible behavior for callers that do not supply a
  // lifecycle phase.
  if(asOf!==undefined){
    const visible=updates.filter((u:any)=>reached(u.latest_completed_minute??u.event_time,asOf))
    const candidate=visible.at(-1)
    if(candidate&&list(candidate.legs).length)return list(candidate.legs)
    if(start.length)return start
    return []
  }
  return final.length?final:updates.length&&list(updates.at(-1)?.legs).length
    ?list(updates.at(-1).legs):start
}
function number(x:any):number|null {return x===null||x===undefined||x===''||!Number.isFinite(Number(x))?null:Number(x)}
export function computedPremiumPoints(leg:any):number|null {
  const en=number(leg.entry_open),ex=number(leg.exit_open)
  if(!leg.exit_timestamp || en===null || ex===null)return null
  return ex-en
}
function legStatus(l:any){
  if(!l.entry_timestamp || number(l.entry_open)===null)return 'ENTRY UNAVAILABLE'
  if(!l.exit_timestamp || number(l.exit_open)===null)return 'ACTIVE / EXIT PENDING'
  return 'CLOSED'
}
const relative=(r:any)=>Number(r)===0?'ATM':`ATM${Number(r)>0?'+':''}${val(r)}`
const color=(n:number|null)=>n===null?'':n>0?'hd-positive':n<0?'hd-negative':''
const eventAt=(t:any,r:HilegaAudit)=>clock(t?.event_time??r.checkpoint)

function CeTable({r,allowedUntil,displayKind}:{r:HilegaAudit;allowedUntil?:string;displayKind:DisplayKind}){
  const raw=reportedLegs(r,allowedUntil,displayKind)
  // Realized option exit/P&L belongs only to the strategy's BULLISH_EXIT row.
  // Entry and continuation rows deliberately suppress linked future exits even
  // if the immutable audit report already contains the completed lifecycle.
  const canShowFinal=displayKind==='EXIT'
  const legs=raw.length?raw:list(r.option_candidate?.contracts??r.option_candidate?.candidates).map((x:any)=>({
    relation_to_atm:x.relation_to_atm,strike:x.strike,instrument_key:x.instrument_key,
    entry_open:null,exit_open:null,entry_timestamp:null,exit_timestamp:null
  }))
  if(!legs.length)return <p className="hd-muted">No five-strike CE lifecycle rows are recorded for this checkpoint. Open a linked entry or exit candle when available.</p>
  return <div className="hd-scroll"><table className="hd-table hd-ce"><thead><tr><th>CE</th><th>Instrument</th><th>Entry time</th><th>Entry premium</th><th>Exit time</th><th>Exit premium</th><th>P&amp;L pts</th><th>P&amp;L %</th><th>MFE</th><th>MAE</th><th>Status</th></tr></thead><tbody>
    {legs.map((x:any,i:number)=>{
      const isFinal=canShowFinal && Boolean(x.exit_timestamp) && (allowedUntil===undefined || reached(x.exit_timestamp,allowedUntil))
      const pts=isFinal?computedPremiumPoints(x):null
      const en=number(x.entry_open)
      const calculated=pts!==null && en!==null && en>0 ? pts/en*100:null
      const recorded=number(x.realized_points)
      const mismatch=isFinal && recorded!==null && pts!==null && Math.abs(pts-recorded)>0.011
      return <tr key={`${val(x.instrument_key)}-${i}`}>
        <td>{relative(x.relation_to_atm)} · {val(x.strike)} CE</td>
        <td title={val(x.instrument_key)}>{val(x.instrument_key)}</td>
        <td>{clock(x.entry_timestamp)}</td><td>{money(x.entry_open)}</td>
        <td>{isFinal?clock(x.exit_timestamp):'—'}</td><td>{isFinal?money(x.exit_open):'—'}</td>
        <td className={color(pts)}>{pts===null?'—':money(pts)}{mismatch&&<span className="hd-warning"> Recorded result differs</span>}</td>
        <td className={color(pts)}>{calculated===null?'—':pct(calculated)}</td>
        <td>{money(x.mfe_points)}</td><td>{money(x.mae_points)}</td>
        <td>{isFinal?'CLOSED':displayKind==='EXIT'?'PENDING EXACT EXIT':legStatus({...x,exit_timestamp:null,exit_open:null})}</td>
      </tr>
    })}
  </tbody></table><p className="hd-muted">Hypothetical premium points per independent CE contract; not executed account P&amp;L. No substitute premiums or assumed quantity/costs.</p></div>
}

function lifecycleHasData(l:any):boolean {
  return Boolean(
    list(l?.start?.legs).length ||
    list(l?.updates).some((u:any)=>list(u?.legs).length) ||
    list(l?.exit?.legs).length
  )
}

function mergeUpdates(values:any[]):any[] {
  const out:any[]=[]
  const seen=new Set<string>()
  for(const v of values){
    for(const u of list(v)){
      const key=JSON.stringify([
        u?.event_time??u?.latest_completed_minute??'',
        u?.status??'',
        list(u?.legs).map((x:any)=>[
          x?.instrument_key??'',x?.strike??'',x?.entry_timestamp??'',
          x?.entry_open??null,x?.latest_completed_minute??'',x?.latest_open??null,
          x?.exit_timestamp??'',x?.exit_open??null
        ])
      ])
      if(!seen.has(key)){seen.add(key);out.push(u)}
    }
  }
  return out.sort((a:any,b:any)=>String(a?.event_time??a?.latest_completed_minute??'').localeCompare(String(b?.event_time??b?.latest_completed_minute??'')))
}

export function mergeLifecycleEvidence(base:HilegaAudit, peers:HilegaAudit[]):HilegaAudit {
  const all=[base,...peers.filter(x=>x!==base)]
  const candidate=all.find(x=>x.option_candidate && (list(x.option_candidate?.contracts??x.option_candidate?.candidates).length || x.option_candidate?.status))
  const snapshot=all.find(x=>x.option_market_snapshot && x.option_market_snapshot?.status)
  const withStart=all.find(x=>list(x.option_lifecycle?.start?.legs).length)
  const withExit=[...all].reverse().find(x=>list(x.option_lifecycle?.exit?.legs).length)
  const updates=mergeUpdates(all.map(x=>x.option_lifecycle?.updates))
  const mergedLifecycle:any={
    ...(base.option_lifecycle??{}),
    ...(withStart?.option_lifecycle??{}),
    start: withStart?.option_lifecycle?.start ?? base.option_lifecycle?.start,
    updates,
    exit: withExit?.option_lifecycle?.exit ?? base.option_lifecycle?.exit,
  }
  return {
    ...base,
    option_candidate: candidate?.option_candidate ?? base.option_candidate,
    option_market_snapshot: snapshot?.option_market_snapshot ?? base.option_market_snapshot,
    option_lifecycle: lifecycleHasData(mergedLifecycle)?mergedLifecycle:base.option_lifecycle,
  }
}

function Detail({r,allowedUntil,origin,originRoute,displayKind,lifecycleIssue}:{r:HilegaAudit;allowedUntil?:string;origin?:string|null;originRoute?:string|null;displayKind:DisplayKind;lifecycleIssue?:string|null}){
  const cand=r.bar??{},ind=r.indicators??{},conditions=r.conditions??{}
  const entry=checkpointTransitions(r).find(isEntry),exit=checkpointTransitions(r).find(isExit)
  const reasons=[...list(r.route_a?.fail_reasons),...list(r.route_b?.fail_reasons)]
  const snapshotTime=r.option_market_snapshot?.signal_boundary
  const visibleSnapshot=allowedUntil===undefined || reached(snapshotTime,allowedUntil)
  return <div className="hd-audit">
    <div className="hd-cards">
      <article><b>Nifty candle</b><span>{clock(r.checkpoint)} IST</span><span>O {val(cand.open)} · H {val(cand.high)} · L {val(cand.low)} · C {val(cand.close)}</span><span>Volume {val(cand.volume)}</span></article>
      <article><b>Indicators</b><span>RSI9 {money(ind.rsi9)} (prev {money(ind.previous_rsi9)})</span><span>EMA3(RSI) {money(ind.ema3_rsi)} (prev {money(ind.previous_ema3_rsi)})</span><span>WMA21(RSI) {money(ind.wma21_rsi)} (prev {money(ind.previous_wma21_rsi)})</span></article>
      <article><b>Strategy state</b><span>{val(r.strategy?.state_before)} → {val(r.strategy?.state_after)}</span><span>Decision: {displayDecisionText(displayKind)}</span><span>Original entry route: {originRoute??pathText(r)}</span><span>Entry signal candle: {origin?clock(origin):'Not available in current timeline'}</span><span>Route A: {score(r.route_a?.pass)} · Route B: {score(r.route_b?.pass)}</span><span>Priority suppression: {score(r.strategy?.route_b_suppressed_by_route_a_priority)}</span></article>
      <article><b>Entry / exit</b><span>Entry: {entry?`${eventAt(entry,r)} · Nifty ${money(entry.price)}`:'Not detected'}</span><span>Exit: {exit?`${eventAt(exit,r)} · Nifty ${money(exit.price)}`:'Not detected'}</span><span>Reason: {val(exit?.exit_reason??exit?.event_type)}</span></article>
    </div>
    {displayKind==='ENTRY'&&<div className="hd-entry-reason"><b>BULLISH_ENTRY confirmed by {pathText(r)}</b><p>Recorded conditions and previous/current indicators are shown below. Only the strategy's recorded transition constitutes an entry; frontend condition checks do not generate new signals.</p></div>}
    {displayKind==='ACTIVE'&&<div className="hd-continuation-reason"><b>BULLISH_CONTINUATION</b><p>Recorded state remains BULLISH_ACTIVE and no exit event was emitted for this candle. No new entry is generated. Origin {origin?clock(origin):'not present in available records'}.</p></div>}
    {displayKind==='EXIT'&&<div className="hd-exit-reason"><b>BULLISH_EXIT</b><p>Recorded exit: {val(exit?.exit_reason??exit?.event_type??list(r.strategy?.events_emitted).find((x:any)=>String(x).includes('EXIT')))}. Original entry signal: {origin?clock(origin):'not available in current timeline'}. Option exit is independently pending until its exact source minute is recorded.</p></div>}
    {displayKind==='REVIEW'&&<div className="hd-review-reason"><b>REVIEW_REQUIRED</b><p>{val(lifecycleIssue)}. Raw audit evidence is preserved below, but the UI will not label this candle as a valid bullish entry/continuation/exit until lifecycle continuity is established.</p></div>}
    <h4>Opening / Route A / Route B conditions</h4>
    <div className="hd-scroll"><table className="hd-table"><thead><tr><th>Check</th><th>Result</th><th>Recorded value</th></tr></thead><tbody>{Object.entries(conditionNames).map(([k,label])=><tr key={k}><td>{label}</td><td><span className={`hd-badge ${conditions[k]===true?'hd-pass':conditions[k]===false?'hd-fail':'hd-neutral'}`}>{score(conditions[k])}</span></td><td>{evidence(k,ind)}</td></tr>)}</tbody></table></div>
    {reasons.length>0&&<p className="hd-muted">Recorded rejection reasons: {reasons.map(String).join(' · ')}</p>}
    <h4>Five independent CE contracts — exact historical/live observations</h4>
    <p>Expiry {val(r.option_candidate?.expiry)} · ATM {val(r.option_candidate?.atm)} · Candidate {val(r.option_candidate?.status)} · Market data {visibleSnapshot?val(r.option_market_snapshot?.status):'NOT YET AVAILABLE'}</p>
    <CeTable r={r} allowedUntil={allowedUntil} displayKind={displayKind}/>
    <details><summary>Recorded candidate selection and option-market snapshot</summary><pre>{json({candidate:r.option_candidate,snapshot:visibleSnapshot?r.option_market_snapshot:'Not yet available at selected candle'})}</pre></details>
    <details><summary>Strategy transitions and recorded decision evidence</summary><pre>{json({strategy:r.strategy,route_a:r.route_a,route_b:r.route_b,transitions:r.transitions})}</pre></details>
    <details><summary>Audit integrity and recorded source events</summary><p>Full-capture hash-chain check: {r.audit_integrity?.chain_ok===true?'PASS':r.audit_integrity?.chain_ok===false?'FAIL':'NOT VERIFIED'}</p><pre>{json(allowedUntil===undefined?r.audit_integrity:{...r.audit_integrity,records:list(r.audit_integrity?.records).filter((x:any)=>reached(x.event_time??x.checkpoint,allowedUntil))})}</pre></details>
  </div>
}

export default function HilegaDecisionTable({reports,mode,fetchDetail,visibleUntil,emptyMessage,onSelected}:{
  reports:HilegaAudit[];mode:'HISTORICAL'|'LIVE';fetchDetail?:(checkpoint:string)=>Promise<HilegaAudit>;
  visibleUntil?:string;emptyMessage?:string;onSelected?:(checkpoint:string)=>void
}){
  const [filter,setFilter]=useState<Filter>('ALL')
  const [open,setOpen]=useState<string|null>(null)
  const [details,setDetails]=useState<Record<string,HilegaAudit>>({})
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const ordered=useMemo(()=>[...reports].filter(r=>!visibleUntil || r.checkpoint<=visibleUntil)
    .sort((a,b)=>a.checkpoint.localeCompare(b.checkpoint)),[reports,visibleUntil])
  const contextual=useMemo(()=>deriveDecisionRows(ordered),[ordered])
  // Derive lifecycle state chronologically, but present newest completed candle first.
  // This keeps entry/continuation/exit state correct while making live monitoring easier.
  const filtered=[...contextual.filter(row=>filter==='ALL'||row.displayKind===filter)].reverse()
  const lifecycleGroup=(origin:string|null|undefined,checkpoint:string)=>{
    const key=origin??checkpoint
    return contextual.filter(row=>(row.origin??row.report.checkpoint)===key)
  }
  useEffect(()=>{
    if(mode!=='LIVE'||!open||!fetchDetail)return
    let active=true
    const refresh=async()=>{
      const current=contextual.find(x=>x.report.checkpoint===open)
      const group=current?lifecycleGroup(current.origin,open):[]
      const checkpoints=[...new Set((group.length?group.map(x=>x.report.checkpoint):[open]))]
      const values=await Promise.all(checkpoints.map(async cp=>[cp,await fetchDetail(cp)] as const))
      if(active)setDetails(prev=>({...prev,...Object.fromEntries(values)}))
    }
    const id=window.setInterval(()=>{refresh().catch(e=>{if(active)setError(`Live audit refresh failed: ${String(e)}`)})},5000)
    return()=>{active=false;window.clearInterval(id)}
  },[mode,open,fetchDetail,contextual])
  async function toggle(row:DecisionRow){
    const r=row.report
    onSelected?.(r.checkpoint)
    if(open===r.checkpoint){setOpen(null);return}
    setOpen(r.checkpoint);setError('')
    if(fetchDetail){
      setLoading(true)
      try{
        const group=lifecycleGroup(row.origin,r.checkpoint)
        const checkpoints=[...new Set((group.length?group.map(x=>x.report.checkpoint):[r.checkpoint]))]
        const values=await Promise.all(checkpoints.map(async cp=>[cp,await fetchDetail(cp)] as const))
        setDetails(prev=>({...prev,...Object.fromEntries(values)}))
      }
      catch(e){setError(String(e))}finally{setLoading(false)}
    }
  }
  return <div className="hd-shell">
    <div className="hd-toolbar"><strong>{mode==='LIVE'?'Live-shadow':'Historical'} candle decision audit</strong><span>{ordered.length} checkpoints available</span>
      <label>Filter <select aria-label={`${mode} candle filter`} value={filter} onChange={e=>setFilter(e.target.value as Filter)}>
        {(['ALL','DETECTED','ENTRY','EXIT','ACTIVE','REJECTED','REVIEW'] as Filter[]).map(k=><option key={k} value={k}>{({ALL:'All candles',DETECTED:'Armed / candidates',ENTRY:'Bullish entries',EXIT:'Bullish exits',ACTIVE:'Bullish continuations',REJECTED:'Rejected setups',REVIEW:'Review required'} as Record<Filter,string>)[k]}</option>)}
      </select></label>
    </div>
    {error&&<p role="alert" className="hd-warning">{error}</p>}
    <div className="hd-scroll"><table className="hd-table hd-main"><thead><tr><th>Date / Time (IST)</th><th>Strategy rule / decision</th><th>Nifty Δ from entry</th><th>Opening path / Route A / Route B</th><th>Signal detected</th><th>Audit</th></tr></thead><tbody>
      {filtered.map((row)=>{const {report:r,origin,originRoute,niftyPoints,displayKind:k,lifecycleIssue}=row
        const opened=open===r.checkpoint
        const peers=lifecycleGroup(origin,r.checkpoint).map(x=>details[x.report.checkpoint]??x.report)
        const report=mergeLifecycleEvidence(details[r.checkpoint]??r,peers)
        const badge=k==='ENTRY'?'BULLISH_ENTRY':k==='EXIT'?'BULLISH_EXIT':k==='ACTIVE'?'BULLISH_CONTINUATION':k==='DETECTED'?'ARMED':k==='NONE'?'NO SIGNAL':k==='REVIEW'?'REVIEW REQUIRED':'REJECTED'
        const timing=candleTiming(r)
        return <Fragment key={r.checkpoint}><tr className={`hd-row hd-${k.toLowerCase()}`}><td><span>{timing.window}</span>{timing.processed&&<small>{timing.label} {timing.processed}</small>}</td><td><strong>{shortRuleText(r,k,lifecycleIssue)}</strong>{lifecycleIssue&&<small className="hd-lifecycle-issue">{lifecycleIssue}</small>}</td><td className={color(niftyPoints)}>{niftyPoints===null?'—':`${niftyPoints>0?'+':''}${money(niftyPoints)} pts`}</td><td>{pathText(r,originRoute??undefined)}</td><td><span className={`hd-badge hd-${k.toLowerCase()}`}>{badge}</span></td><td><button aria-expanded={opened} aria-label={`Audit ${r.checkpoint}`} onClick={()=>void toggle(row)}>{opened?'Hide audit':'View audit ▾'}</button></td></tr>
        {opened&&<tr className="hd-expanded"><td colSpan={6}>{loading&&!details[r.checkpoint]&&<p>Loading linked CE lifecycle…</p>}<Detail r={report} origin={origin} originRoute={originRoute} displayKind={k} lifecycleIssue={lifecycleIssue} allowedUntil={candleBoundary(r.checkpoint)}/></td></tr>}
        </Fragment>
      })}
      {!filtered.length&&<tr><td colSpan={6}>{emptyMessage??'No recorded checkpoints for this selection.'}</td></tr>}
    </tbody></table></div>
  </div>
}
