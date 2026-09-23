import { useEffect, useMemo, useState } from 'react'

type AuditReport = {
  checkpoint:string
  mode:string
  strategy:{state_before:string|null;state_after:string|null;selected_route:string|null;route_b_suppressed_by_route_a_priority:boolean|null;events_emitted:string[]}
  bar:{open:number|null;high:number|null;low:number|null;close:number|null;volume:number|null}
  indicators:{rsi9:number|null;ema3_rsi:number|null;wma21_rsi:number|null;previous_rsi9:number|null;previous_ema3_rsi:number|null;previous_wma21_rsi:number|null}
  conditions:Record<string,boolean|null>
  route_a:{eligible:boolean|null;pass:boolean|null;fail_reasons:string[]}
  route_b:{eligible:boolean|null;pass:boolean|null;fail_reasons:string[]}
  transitions:Array<Record<string,any>>
  option_candidate:Record<string,any>|null
  option_market_snapshot:Record<string,any>|null
  option_lifecycle:{start:Record<string,any>|null;updates:Array<Record<string,any>>;exit:Record<string,any>|null}
  audit_integrity:{chain_ok:boolean|null;chain_issue:string|null;records:Array<Record<string,any>>}
  safety:{observation_only:boolean;execution_enabled:boolean;paper_order_enabled:boolean}
}

type Status = {
  observation_only:boolean
  execution_enabled:boolean
  paper_order_enabled:boolean
  step_audit_chain_ok:boolean
  step_audit_chain_issue:string|null
  latest_decision:Record<string,any>|null
  latest_option_shadow:Record<string,any>|null
}

const base='/api/live-shadow/hilega-milega'
const get=async<T,>(path:string):Promise<T>=>{
  const r=await fetch(base+path)
  if(!r.ok){const e=await r.json().catch(()=>null);throw new Error(e?.detail||'Hilega-Milega request failed')}
  return r.json()
}
const tm=(v:string|null|undefined)=>v?new Date(v).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const dt=(v:string|null|undefined)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const num=(v:any,d=2)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:d})
const words=(v:any)=>v==null?'—':String(v).replaceAll('_',' ')
const yn=(v:any)=>v==null?'NA':v?'YES':'NO'
const isEntry=(x:any)=>String(x?.event_type??'').startsWith('ENTRY_')
const isExit=(x:any)=>String(x?.event_type??'').includes('EXIT')
const firstEntry=(r:AuditReport)=>r.transitions.find(isEntry)??null
const firstExit=(r:AuditReport)=>r.transitions.find(isExit)??null
const lifecycleState=(r:AuditReport)=>r.option_lifecycle.exit?.status??r.option_lifecycle.updates.at(-1)?.status??r.option_lifecycle.start?.status??null

function AuditDetail({r}:{r:AuditReport}){
  const legs=(r.option_lifecycle.exit?.legs??r.option_lifecycle.updates.at(-1)?.legs??r.option_lifecycle.start?.legs??[]) as any[]
  const entry=firstEntry(r)
  const exit=firstExit(r)
  return <div className="hilega-audit-body">
    <div className="shadow-detail-grid" style={{gridTemplateColumns:'repeat(auto-fit,minmax(210px,1fr))'}}>
      <span>Checkpoint <b>{dt(r.checkpoint)}</b></span><span>Route <b>{words(r.strategy.selected_route)}</b></span>
      <span>State <b>{words(r.strategy.state_before)} → {words(r.strategy.state_after)}</b></span>
      <span>Entry <b>{entry?`${num(entry.price)} @ ${tm(entry.event_time??r.checkpoint)}`:'—'}</b><small>{entry?words(entry.source??entry.event_type):'No entry at this checkpoint'}</small></span>
      <span>Exit <b>{exit?`${num(exit.price)} @ ${tm(exit.event_time??r.checkpoint)}`:'—'}</b><small>{exit?words(exit.exit_reason??exit.source??exit.event_type):'No exit at this checkpoint'}</small></span>
      <span>Close <b>{num(r.bar.close)}</b></span>
      <span>RSI9 <b>{num(r.indicators.rsi9)}</b></span><span>EMA3 RSI <b>{num(r.indicators.ema3_rsi)}</b></span><span>WMA21 RSI <b>{num(r.indicators.wma21_rsi)}</b></span>
      <span>Previous RSI9 <b>{num(r.indicators.previous_rsi9)}</b></span><span>Previous EMA3 RSI <b>{num(r.indicators.previous_ema3_rsi)}</b></span><span>Previous WMA21 RSI <b>{num(r.indicators.previous_wma21_rsi)}</b></span>
      <span>RSI↑EMA <b>{yn(r.conditions.rsi_cross_ema_up)}</b></span><span>RSI↓WMA <b>{yn(r.conditions.rsi_cross_wma_down)}</b></span><span>RSI&gt;50 <b>{yn(r.conditions.rsi_gt_50)}</b></span>
      <span>RSI&gt;WMA <b>{yn(r.conditions.rsi_gt_wma)}</b></span><span>EMA&gt;WMA <b>{yn(r.conditions.ema_gt_wma)}</b></span><span>RSI rising <b>{yn(r.conditions.rsi_rising)}</b></span><span>EMA rising <b>{yn(r.conditions.ema_rising)}</b></span>
      <span>Route A <b>{yn(r.route_a.pass)}</b><small>{r.route_a.fail_reasons.join(', ')||'No failures'}</small></span>
      <span>Route B <b>{yn(r.route_b.pass)}</b><small>{r.route_b.fail_reasons.join(', ')||'No failures'}</small></span>
      <span>A priority <b>{yn(r.strategy.route_b_suppressed_by_route_a_priority)}</b></span>
      <span>Expiry <b>{String(r.option_candidate?.expiry??'—')}</b></span><span>ATM <b>{num(r.option_candidate?.atm,0)}</b></span>
      <span>Candidate status <b>{words(r.option_candidate?.status)}</b></span><span>Market snapshot <b>{words(r.option_market_snapshot?.status)}</b></span>
      <span>Lifecycle <b>{words(lifecycleState(r))}</b></span><span>Audit chain <b>{r.audit_integrity.chain_ok?'HEALTHY':'CHECK'}</b></span>
    </div>
    {legs.length>0&&<div className="hilega-audit-section"><b>ATM±2 CE shadow legs</b><div className="shadow-table-scroll"><table className="shadow-table"><thead><tr><th>Role</th><th>Strike</th><th>Entry</th><th>Latest / Exit</th><th>Move</th><th>MFE</th><th>MAE</th></tr></thead><tbody>{legs.map((x:any)=><tr key={x.instrument_key}><td>{x.relation_to_atm===0?'ATM':`ATM${x.relation_to_atm>0?'+':''}${x.relation_to_atm}`}</td><td>{num(x.strike,0)} CE</td><td>{num(x.entry_open)}</td><td>{num(x.exit_open??x.latest_close)}</td><td>{num(x.current_points??x.exit_points)}</td><td>{num(x.mfe_points)}</td><td>{num(x.mae_points)}</td></tr>)}</tbody></table></div></div>}
    <div className="hilega-audit-section"><b>Transitions</b><pre>{JSON.stringify(r.transitions,null,2)}</pre></div>
    <div className="hilega-audit-section"><b>Audit integrity</b><pre>{JSON.stringify(r.audit_integrity,null,2)}</pre></div>
  </div>
}

export default function HilegaMilegaShadow(){
  const [status,setStatus]=useState<Status|null>(null)
  const [rows,setRows]=useState<AuditReport[]>([])
  const [selected,setSelected]=useState<AuditReport|null>(null)
  const [auditLoading,setAuditLoading]=useState(false)
  const [error,setError]=useState('')
  const refresh=async()=>{const [s,a]=await Promise.all([get<Status>('/status'),get<AuditReport[]>('/audit-index?limit=100')]);setStatus(s);setRows(a);setError('')}
  useEffect(()=>{let active=true;const poll=()=>void refresh().catch(e=>active&&setError((e as Error).message));poll();const t=setInterval(poll,3000);return()=>{active=false;clearInterval(t)}},[])

  const activity=useMemo(()=>rows.filter(r=>r.transitions.length>0 || (r.strategy.events_emitted||[]).length>0),[rows])
  const entries=useMemo(()=>activity.flatMap(r=>r.transitions.filter(isEntry).map(t=>({r,t}))),[activity])
  const exits=useMemo(()=>activity.flatMap(r=>r.transitions.filter(isExit).map(t=>({r,t}))),[activity])
  const lastEntry=entries[0]??null
  const lastExit=exits[0]??null
  const activeState=String(status?.latest_decision?.payload?.state_after??rows[0]?.strategy.state_after??'NO DATA')

  const openAudit=async(r:AuditReport)=>{
    setSelected(r) // show the panel immediately, then hydrate with the endpoint response
    setAuditLoading(true)
    try{
      const detail=await get<AuditReport>('/audit-detail?checkpoint='+encodeURIComponent(r.checkpoint))
      setSelected(detail);setError('')
    }catch(e){setError(`Audit detail failed: ${(e as Error).message}`)}
    finally{setAuditLoading(false)}
  }

  return <div className="shadow-page">
    {error&&<div className="banner error">{error}</div>}
    <div className="shadow-safety"><b>HILEGA-MILEGA · OBSERVATION ONLY</b><span>Execution disabled</span><span>Paper orders disabled</span><span>ATM±2 CE shadow</span><span>Audit chain {status?.step_audit_chain_ok?'healthy':'check'}</span></div>

    <div className="shadow-metrics">
      <article><span>Strategy state</span><b>{words(activeState)}</b><small>Latest canonical live-shadow state</small></article>
      <article><span>Last entry detected</span><b>{lastEntry?tm(lastEntry.t.event_time??lastEntry.r.checkpoint):'—'}</b><small>{lastEntry?`${words(lastEntry.t.source??lastEntry.t.event_type)} · NIFTY ${num(lastEntry.t.price)}`:'No entry recorded'}</small></article>
      <article><span>Last exit</span><b>{lastExit?tm(lastExit.t.event_time??lastExit.r.checkpoint):'—'}</b><small>{lastExit?`${words(lastExit.t.exit_reason??lastExit.t.source??lastExit.t.event_type)} · NIFTY ${num(lastExit.t.price)}`:'No exit recorded'}</small></article>
    </div>

    <div className="shadow-columns hilega-main-columns">
      <section className="panel shadow-panel">
        <div className="panel-heading"><div><h2>Hilega-Milega entry / exit activity</h2><p>Operational view only. RSI, EMA3, WMA21 and condition details are kept inside Audit.</p></div><span className="pill teal">{activity.length} EVENTS</span></div>
        {!activity.length?<div className="empty">No Hilega-Milega entry/exit activity yet. Detailed decisions remain available through audit once recorded.</div>:
        <div className="shadow-table-scroll"><table className="shadow-table hilega-activity-table"><thead><tr><th>Time</th><th>Event</th><th>Route</th><th>State</th><th>Underlying</th><th>Option shadow</th><th>Exit details</th><th>Audit</th></tr></thead><tbody>{activity.map(r=>{
          const entry=firstEntry(r);const exit=firstExit(r);const event=entry??exit??r.transitions[0]??null
          const eventName=event?.event_type??r.strategy.events_emitted?.[0]??'STATE CHANGE'
          return <tr key={r.checkpoint} className={selected?.checkpoint===r.checkpoint?'selected':''}>
            <td>{tm(event?.event_time??r.checkpoint)}</td>
            <td className={entry?'positive':exit?'negative':''}>{entry?'ENTRY DETECTED':exit?'EXIT':'STATE CHANGE'}<small className="hilega-subline">{words(eventName)}</small></td>
            <td>{words(r.strategy.selected_route)}</td>
            <td>{words(r.strategy.state_after)}</td>
            <td>{num(event?.price??r.bar.close)}</td>
            <td>{words(lifecycleState(r))}</td>
            <td>{exit?<><b>{num(exit.price)}</b><small className="hilega-subline">{words(exit.exit_reason??exit.source??eventName)}</small></>: '—'}</td>
            <td><button onClick={()=>void openAudit(r)}>{selected?.checkpoint===r.checkpoint&&auditLoading?'Loading…':'Audit'}</button></td>
          </tr>
        })}</tbody></table></div>}
      </section>

      <section className="panel shadow-panel hilega-audit-panel">
        <div className="panel-heading"><div><h2>Detailed audit report</h2><p>{selected?selected.checkpoint:'Click Audit beside an entry, exit or state event.'}</p></div>{selected&&<button onClick={()=>setSelected(null)}>Close</button>}</div>
        {!selected?<div className="empty">Select <b>Audit</b> to see RSI/EMA/WMA values, route checks, exact option details, transitions and hash-chain integrity here.</div>:<AuditDetail r={selected}/>} 
      </section>
    </div>
  </div>
}
