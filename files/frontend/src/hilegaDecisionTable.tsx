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
  audit_integrity?: Record<string, any>
  safety?: Record<string, any>
}
type Filter = 'ALL' | 'DETECTED' | 'ENTRY' | 'EXIT' | 'ACTIVE' | 'REJECTED'
type Kind = 'DETECTED' | 'ENTRY' | 'EXIT' | 'ACTIVE' | 'REJECTED' | 'NONE'
const list = (x:unknown): any[] => Array.isArray(x) ? x : []
const val = (x:any) => x===undefined || x===null || x==='' ? '—' : String(x)
const money = (x:any) => x===undefined || x===null || !Number.isFinite(Number(x)) ? '—' : Number(x).toFixed(2)
const pct = (x:any) => x===undefined || x===null || !Number.isFinite(Number(x)) ? '—' : `${Number(x).toFixed(2)}%`
const clock = (x:any) => {
  if(!x)return '—'
  const d=new Date(String(x))
  return Number.isNaN(d.getTime())?String(x):d.toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false,hour:'2-digit',minute:'2-digit'})
}
const json=(v:unknown)=>JSON.stringify(v??{},null,2)
const isEntry=(x:any)=>String(x?.event_type??'').startsWith('ENTRY_')
const isExit=(x:any)=>String(x?.event_type??'').includes('EXIT')
const transitions=(r:HilegaAudit)=>list(r.transitions)
// Display classifications are derived from recorded transitions and state, not
// independent entry/exit calculations. EXIT always has precedence over ENTRY.
export function eventKind(r:HilegaAudit):Kind {
  const t=transitions(r)
  const events=list(r.strategy?.events_emitted).map(String)
  if(t.some(isExit)||events.some(x=>x.includes('EXIT')))return 'EXIT'
  if(t.some(isEntry)||events.some(x=>x.startsWith('ENTRY_')))return 'ENTRY'
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
// Preserve the original entry route on continuation and exit, when earlier
// records in the currently available timeline prove it. Never infer an origin
// from a later successful trade or a future candle.
export function pathText(r:HilegaAudit,carriedRoute?:string):string {
  const route=r.strategy?.selected_route
  if(route)return String(route).replaceAll('_',' ')
  const events=list(r.strategy?.events_emitted).map(String)
  const origin=transitions(r).find(isEntry)
  const source=origin?.source
  if(source)return String(source).replaceAll('_',' ')
  if(events.some(x=>x.startsWith('OPENING_')) || [r.strategy?.state_before,r.strategy?.state_after].some(x=>String(x??'').startsWith('OPENING_')))return 'Opening path'
  if(carriedRoute && (eventKind(r)==='ACTIVE' || eventKind(r)==='EXIT'))return carriedRoute
  if(r.route_a?.eligible===true && r.route_b?.eligible===true)return 'Route A / Route B'
  if(r.route_a?.eligible===true)return 'Route A'
  if(r.route_b?.eligible===true)return 'Route B'
  if(eventKind(r)==='ACTIVE'||eventKind(r)==='EXIT')return 'Entry route not in available records'
  if(r.strategy?.state_after)return val(r.strategy.state_after).replaceAll('_',' ')
  return 'Not evaluated'
}
export type DecisionRow = {report:HilegaAudit;origin:string|null;originRoute:string|null}
export function deriveDecisionRows(reports:HilegaAudit[]):DecisionRow[] {
  let origin:string|null=null,originRoute:string|null=null,sessionDate:string|null=null
  return [...reports].sort((a,b)=>a.checkpoint.localeCompare(b.checkpoint)).map(report=>{
    const date=report.checkpoint.slice(0,10)
    if(sessionDate!==date){origin=null;originRoute=null;sessionDate=date}
    const kind=eventKind(report)
    if(kind==='ENTRY'){
      origin=report.checkpoint
      originRoute=pathText(report)
    }
    const result={report,origin,originRoute}
    if(kind==='EXIT'){
      // Exit transitions carry immutable original entry identity when recorded.
      const linked=transitions(report).find(isExit)?.details?.original_entry_time
      if(linked)result.origin=String(linked)
      origin=null;originRoute=null
    } else if(kind==='NONE' && String(report.strategy?.state_after??'')==='SESSION_LOCKED'){
      origin=null;originRoute=null
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
function reportedLegs(r:HilegaAudit,asOf?:string){
  const l=r.option_lifecycle??{}
  if(asOf!==undefined){
    const exit=transitions(r).find(isExit)
    const final=list(l.exit?.legs)
    if(exit&&reached(exit.event_time??r.checkpoint,asOf)&&final.length&&final.every((x:any)=>reached(x.exit_timestamp,asOf)))return final
    const updates=list(l.updates).filter((x:any)=>reached(x.latest_completed_minute,asOf))
    const candidate=updates.at(-1)
    if(candidate&&list(candidate.legs).length&&list(candidate.legs).every((x:any)=>reached(x.entry_timestamp,asOf)))return list(candidate.legs)
    if(list(l.start?.legs).length&&list(l.start.legs).every((x:any)=>reached(x.entry_timestamp,asOf)))return list(l.start.legs)
    return []
  }
  return list(l.exit?.legs).length?list(l.exit.legs):list(l.updates).length&&list(l.updates.at(-1)?.legs).length
    ?list(l.updates.at(-1).legs):list(l.start?.legs)
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

function CeTable({r,allowedUntil}:{r:HilegaAudit;allowedUntil?:string}){
  const raw=reportedLegs(r,allowedUntil)
  // Progressive replay: never expose a future lifecycle result, even when the
  // immutable entry audit contains linked future updates or exits.
  const transitionExit=transitions(r).find(isExit)
  const canShowFinal=allowedUntil===undefined || Boolean(transitionExit && reached(transitionExit.event_time??r.checkpoint,allowedUntil) && list(r.option_lifecycle?.exit?.legs).length && list(r.option_lifecycle?.exit?.legs).every((x:any)=>reached(x.exit_timestamp,allowedUntil)))
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
        <td>{isFinal?'CLOSED':legStatus({...x,exit_timestamp:null,exit_open:null})}</td>
      </tr>
    })}
  </tbody></table><p className="hd-muted">Hypothetical premium points per independent CE contract; not executed account P&amp;L. No substitute premiums or assumed quantity/costs.</p></div>
}
function Detail({r,allowedUntil,origin,originRoute}:{r:HilegaAudit;allowedUntil?:string;origin?:string|null;originRoute?:string|null}){
  const cand=r.bar??{},ind=r.indicators??{},conditions=r.conditions??{}
  const entry=transitions(r).find(isEntry),exit=transitions(r).find(isExit)
  const reasons=[...list(r.route_a?.fail_reasons),...list(r.route_b?.fail_reasons)]
  const snapshotTime=r.option_market_snapshot?.signal_boundary
  const visibleSnapshot=allowedUntil===undefined || reached(snapshotTime,allowedUntil)
  return <div className="hd-audit">
    <div className="hd-cards">
      <article><b>Nifty candle</b><span>{clock(r.checkpoint)} IST</span><span>O {val(cand.open)} · H {val(cand.high)} · L {val(cand.low)} · C {val(cand.close)}</span><span>Volume {val(cand.volume)}</span></article>
      <article><b>Indicators</b><span>RSI9 {money(ind.rsi9)} (prev {money(ind.previous_rsi9)})</span><span>EMA3(RSI) {money(ind.ema3_rsi)} (prev {money(ind.previous_ema3_rsi)})</span><span>WMA21(RSI) {money(ind.wma21_rsi)} (prev {money(ind.previous_wma21_rsi)})</span></article>
      <article><b>Strategy state</b><span>{val(r.strategy?.state_before)} → {val(r.strategy?.state_after)}</span><span>Decision: {decisionText(r)}</span><span>Original entry route: {originRoute??pathText(r)}</span><span>Entry signal candle: {origin?clock(origin):'Not available in current timeline'}</span><span>Route A: {score(r.route_a?.pass)} · Route B: {score(r.route_b?.pass)}</span><span>Priority suppression: {score(r.strategy?.route_b_suppressed_by_route_a_priority)}</span></article>
      <article><b>Entry / exit</b><span>Entry: {entry?`${eventAt(entry,r)} · Nifty ${money(entry.price)}`:'Not detected'}</span><span>Exit: {exit?`${eventAt(exit,r)} · Nifty ${money(exit.price)}`:'Not detected'}</span><span>Reason: {val(exit?.exit_reason??exit?.event_type)}</span></article>
    </div>
    {eventKind(r)==='ENTRY'&&<div className="hd-entry-reason"><b>BULLISH_ENTRY confirmed by {pathText(r)}</b><p>Recorded conditions and previous/current indicators are shown below. Only the strategy's recorded transition constitutes an entry; frontend condition checks do not generate new signals.</p></div>}
    {eventKind(r)==='ACTIVE'&&<div className="hd-continuation-reason"><b>BULLISH_CONTINUATION</b><p>Recorded state remains BULLISH_ACTIVE and no exit event was emitted for this candle. No new entry is generated. Origin {origin?clock(origin):'not present in available records'}.</p></div>}
    {eventKind(r)==='EXIT'&&<div className="hd-exit-reason"><b>BULLISH_EXIT</b><p>Recorded exit: {val(exit?.exit_reason??exit?.event_type??list(r.strategy?.events_emitted).find((x:any)=>String(x).includes('EXIT')))}. Original entry signal: {origin?clock(origin):'not available in current timeline'}. Option exit is independently pending until its exact source minute is recorded.</p></div>}
    <h4>Opening / Route A / Route B conditions</h4>
    <div className="hd-scroll"><table className="hd-table"><thead><tr><th>Check</th><th>Result</th><th>Recorded value</th></tr></thead><tbody>{Object.entries(conditionNames).map(([k,label])=><tr key={k}><td>{label}</td><td><span className={`hd-badge ${conditions[k]===true?'hd-pass':conditions[k]===false?'hd-fail':'hd-neutral'}`}>{score(conditions[k])}</span></td><td>{evidence(k,ind)}</td></tr>)}</tbody></table></div>
    {reasons.length>0&&<p className="hd-muted">Recorded rejection reasons: {reasons.map(String).join(' · ')}</p>}
    <h4>Five independent CE contracts — exact historical/live observations</h4>
    <p>Expiry {val(r.option_candidate?.expiry)} · ATM {val(r.option_candidate?.atm)} · Candidate {val(r.option_candidate?.status)} · Market data {visibleSnapshot?val(r.option_market_snapshot?.status):'NOT YET AVAILABLE'}</p>
    <CeTable r={r} allowedUntil={allowedUntil}/>
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
  const filtered=contextual.filter(({report:r})=>filter==='ALL'||eventKind(r)===filter)
  useEffect(()=>{
    if(mode!=='LIVE'||!open||!fetchDetail)return
    let active=true
    const id=window.setInterval(()=>{
      fetchDetail(open).then(value=>{if(active)setDetails(prev=>({...prev,[open]:value}))})
        .catch(e=>{if(active)setError(`Live audit refresh failed: ${String(e)}`)})
    },5000)
    return()=>{active=false;window.clearInterval(id)}
  },[mode,open,fetchDetail])
  async function toggle(r:HilegaAudit){
    onSelected?.(r.checkpoint)
    if(open===r.checkpoint){setOpen(null);return}
    setOpen(r.checkpoint);setError('')
    if(fetchDetail){
      setLoading(true)
      try{const item=await fetchDetail(r.checkpoint);setDetails(prev=>({...prev,[r.checkpoint]:item}))}
      catch(e){setError(String(e))}finally{setLoading(false)}
    }
  }
  return <div className="hd-shell">
    <div className="hd-toolbar"><strong>{mode==='LIVE'?'Live-shadow':'Historical'} candle decision audit</strong><span>{ordered.length} checkpoints available</span>
      <label>Filter <select aria-label={`${mode} candle filter`} value={filter} onChange={e=>setFilter(e.target.value as Filter)}>
        {(['ALL','DETECTED','ENTRY','EXIT','ACTIVE','REJECTED'] as Filter[]).map(k=><option key={k} value={k}>{({ALL:'All candles',DETECTED:'Armed / candidates',ENTRY:'Bullish entries',EXIT:'Bullish exits',ACTIVE:'Bullish continuations',REJECTED:'Rejected setups'} as Record<Filter,string>)[k]}</option>)}
      </select></label>
    </div>
    {error&&<p role="alert" className="hd-warning">{error}</p>}
    <div className="hd-scroll"><table className="hd-table hd-main"><thead><tr><th>Time (IST)</th><th>Strategy decision</th><th>Opening path / Route A / Route B</th><th>Signal detected</th><th>Audit</th></tr></thead><tbody>
      {filtered.map(({report:r,origin,originRoute})=>{const k=eventKind(r),opened=open===r.checkpoint,report=details[r.checkpoint]??r
        return <Fragment key={r.checkpoint}><tr className={`hd-row hd-${k.toLowerCase()}`}><td>{clock(r.checkpoint)}</td><td><strong>{decisionText(r)}</strong></td><td>{pathText(r,originRoute??undefined)}</td><td><span className={`hd-badge hd-${k.toLowerCase()}`}>{k==='ENTRY'?'BULLISH_ENTRY':k==='EXIT'?'BULLISH_EXIT':k==='ACTIVE'?'BULLISH_CONTINUATION':k==='DETECTED'?'ARMED':k==='NONE'?'NO SIGNAL':'REJECTED'}</span></td><td><button aria-expanded={opened} aria-label={`Audit ${r.checkpoint}`} onClick={()=>void toggle(r)}>{opened?'Hide audit':'View audit ▾'}</button></td></tr>
        {opened&&<tr className="hd-expanded"><td colSpan={5}>{loading&&!details[r.checkpoint]&&<p>Loading complete audit…</p>}<Detail r={report} origin={origin} originRoute={originRoute} allowedUntil={candleBoundary(visibleUntil)}/></td></tr>}
        </Fragment>
      })}
      {!filtered.length&&<tr><td colSpan={5}>{emptyMessage??'No recorded checkpoints for this selection.'}</td></tr>}
    </tbody></table></div>
  </div>
}
