import { useEffect, useState } from 'react'

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
const num=(v:any,d=2)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:d})
const words=(v:any)=>v==null?'—':String(v).replaceAll('_',' ')
const yn=(v:any)=>v==null?'NA':v?'YES':'NO'

function AuditDetail({r}:{r:AuditReport}){
  const legs=(r.option_lifecycle.exit?.legs??r.option_lifecycle.updates.at(-1)?.legs??r.option_lifecycle.start?.legs??[]) as any[]
  return <div className="shadow-detail-grid" style={{gridTemplateColumns:'repeat(auto-fit,minmax(220px,1fr))'}}>
    <span>Checkpoint <b>{tm(r.checkpoint)}</b></span><span>Route <b>{words(r.strategy.selected_route)}</b></span>
    <span>State <b>{words(r.strategy.state_before)} → {words(r.strategy.state_after)}</b></span><span>Close <b>{num(r.bar.close)}</b></span>
    <span>RSI9 <b>{num(r.indicators.rsi9)}</b></span><span>EMA3 RSI <b>{num(r.indicators.ema3_rsi)}</b></span><span>WMA21 RSI <b>{num(r.indicators.wma21_rsi)}</b></span>
    <span>RSI↑EMA <b>{yn(r.conditions.rsi_cross_ema_up)}</b></span><span>RSI&gt;50 <b>{yn(r.conditions.rsi_gt_50)}</b></span><span>RSI&gt;WMA <b>{yn(r.conditions.rsi_gt_wma)}</b></span>
    <span>Route A <b>{yn(r.route_a.pass)}</b><small>{r.route_a.fail_reasons.join(', ')||'No failures'}</small></span>
    <span>Route B <b>{yn(r.route_b.pass)}</b><small>{r.route_b.fail_reasons.join(', ')||'No failures'}</small></span>
    <span>A priority <b>{yn(r.strategy.route_b_suppressed_by_route_a_priority)}</b></span>
    <span>Expiry <b>{String(r.option_candidate?.expiry??'—')}</b></span><span>ATM <b>{num(r.option_candidate?.atm,0)}</b></span>
    <span>Candidate status <b>{words(r.option_candidate?.status)}</b></span><span>Market snapshot <b>{words(r.option_market_snapshot?.status)}</b></span>
    <span>Lifecycle <b>{words(r.option_lifecycle.exit?.status??r.option_lifecycle.start?.status)}</b></span><span>Audit chain <b>{r.audit_integrity.chain_ok?'HEALTHY':'CHECK'}</b></span>
    {legs.length>0&&<div style={{gridColumn:'1/-1'}}><b>ATM±2 CE shadow legs</b><div className="shadow-table-scroll"><table className="shadow-table"><thead><tr><th>Role</th><th>Strike</th><th>Entry</th><th>Latest</th><th>Move</th><th>MFE</th><th>MAE</th></tr></thead><tbody>{legs.map((x:any)=><tr key={x.instrument_key}><td>{x.relation_to_atm===0?'ATM':`ATM${x.relation_to_atm>0?'+':''}${x.relation_to_atm}`}</td><td>{num(x.strike,0)} CE</td><td>{num(x.entry_open)}</td><td>{num(x.latest_close)}</td><td>{num(x.current_points)}</td><td>{num(x.mfe_points)}</td><td>{num(x.mae_points)}</td></tr>)}</tbody></table></div></div>}
    <div style={{gridColumn:'1/-1'}}><b>Transitions</b><pre>{JSON.stringify(r.transitions,null,2)}</pre></div>
    <div style={{gridColumn:'1/-1'}}><b>Audit integrity</b><pre>{JSON.stringify(r.audit_integrity,null,2)}</pre></div>
  </div>
}

export default function HilegaMilegaShadow(){
  const [status,setStatus]=useState<Status|null>(null)
  const [rows,setRows]=useState<AuditReport[]>([])
  const [selected,setSelected]=useState<AuditReport|null>(null)
  const [error,setError]=useState('')
  const refresh=async()=>{const [s,a]=await Promise.all([get<Status>('/status'),get<AuditReport[]>('/audit-index?limit=100')]);setStatus(s);setRows(a);setError('')}
  useEffect(()=>{let active=true;const poll=()=>void refresh().catch(e=>active&&setError((e as Error).message));poll();const t=setInterval(poll,3000);return()=>{active=false;clearInterval(t)}},[])
  const openAudit=async(cp:string)=>{try{setSelected(await get<AuditReport>('/audit-detail?checkpoint='+encodeURIComponent(cp)))}catch(e){setError((e as Error).message)}}
  return <div className="shadow-page">
    {error&&<div className="banner error">{error}</div>}
    <div className="shadow-safety"><b>HILEGA-MILEGA · OBSERVATION ONLY</b><span>Execution disabled</span><span>Paper orders disabled</span><span>ATM±2 CE shadow</span><span>Audit chain {status?.step_audit_chain_ok?'healthy':'check'}</span></div>
    <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Canonical decision audit</h2><p>Historical and live use the same detailed audit schema. Click Audit for the complete report.</p></div></div>
      {!rows.length?<div className="empty">No Hilega-Milega decisions yet.</div>:<div className="shadow-table-scroll"><table className="shadow-table"><thead><tr><th>Time</th><th>State</th><th>Route</th><th>Close</th><th>RSI</th><th>EMA3</th><th>WMA21</th><th>Events</th><th>Audit</th></tr></thead><tbody>{rows.map(r=><tr key={r.checkpoint}><td>{tm(r.checkpoint)}</td><td>{words(r.strategy.state_after)}</td><td>{words(r.strategy.selected_route)}</td><td>{num(r.bar.close)}</td><td>{num(r.indicators.rsi9)}</td><td>{num(r.indicators.ema3_rsi)}</td><td>{num(r.indicators.wma21_rsi)}</td><td>{(r.strategy.events_emitted||[]).map(words).join(', ')||'—'}</td><td><button onClick={()=>void openAudit(r.checkpoint)}>Audit</button></td></tr>)}</tbody></table></div>}
    </section>
    {selected&&<section className="panel shadow-panel"><div className="panel-heading"><div><h2>Detailed audit report</h2><p>{selected.checkpoint}</p></div><button onClick={()=>setSelected(null)}>Close</button></div><AuditDetail r={selected}/></section>}
  </div>
}
