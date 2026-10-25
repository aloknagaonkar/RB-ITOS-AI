import {useEffect,useState} from 'react'
import {startLivePolling} from './hilegaLivePolling'
import './hilegaProductionWorkspace.css'

type Snapshot={durable_execution?:any;allocation?:any;bridge_health?:any;broker_observation?:any;model:string;workspace_mode:string;source:string;label:string;generated_at:string;control:any;
 production_execution_enabled:boolean;strategy_worker_controlled:boolean;configuration:any;policy_id:string;strategy_version:string;
 readiness_checks:any[];positions:any[];orders:any[];closed_trades:any[];events:any[];last_reconciled_at?:string}
const money=(v:any)=>v===null||v===undefined?'Unavailable':Number(v).toLocaleString('en-IN',{style:'currency',currency:'INR'})
const fmt=(v:any)=>v===null||v===undefined?'—':String(v)
function requestId(){
 const a=crypto.getRandomValues(new Uint8Array(16));a[6]=(a[6]&15)|64;a[8]=(a[8]&63)|128
 const s=Array.from(a,x=>x.toString(16).padStart(2,'0')).join('')
 return `${s.slice(0,8)}-${s.slice(8,12)}-${s.slice(12,16)}-${s.slice(16,20)}-${s.slice(20)}`
}
async function call(token:string,body?:any,signal?:AbortSignal){
 const c=new AbortController();const abort=()=>c.abort();signal?.addEventListener('abort',abort,{once:true})
 const timer=window.setTimeout(abort,8000)
 try{
  const r=await fetch('/api/hilega-production/'+(body?'commands':'status'),{method:body?'POST':'GET',
   headers:{Authorization:'Bearer '+token,...(body?{'Content-Type':'application/json'}:{})},
   body:body?JSON.stringify(body):undefined,signal:c.signal,cache:'no-store'})
  const value=await r.json()
  if(!r.ok)throw new Error(typeof value.detail==='string'?value.detail:`Request failed (${r.status})`)
  return value
 }catch(e){if(c.signal.aborted)throw new Error(body?'Command acknowledgement unavailable. Check server state; do not assume it succeeded.':'Display connection timed out. Server controls are unaffected.');throw e}
 finally{window.clearTimeout(timer);signal?.removeEventListener('abort',abort)}
}
export default function HilegaProductionWorkspace({onOpenStrategy}:{onOpenStrategy:()=>void}){
 const [draft,setDraft]=useState(''),[token,setToken]=useState(''),[data,setData]=useState<Snapshot|null>(null)
 const [error,setError]=useState(''),[busy,setBusy]=useState(false),[received,setReceived]=useState(0),[clock,setClock]=useState(Date.now())
 const [tab,setTab]=useState('Overview'),[message,setMessage]=useState('')
 useEffect(()=>{const t=window.setInterval(()=>setClock(Date.now()),1000);return()=>window.clearInterval(t)},[])
 useEffect(()=>{
  if(!token)return
  let active=true;const controller=new AbortController()
  const stop=startLivePolling(async()=>{
   try{const value=await call(token,undefined,controller.signal)
    if(value.model!=='HILEGA_PRODUCTION_WORKSPACE_V1')throw new Error('Unexpected workspace response')
    if(active){setData(previous=>previous?.control&&value.control&&previous.control.version>value.control.version?previous:value);setReceived(Date.now());setError('')}
   }catch(e){if(active)setError((e as Error).message)}
  },2000)
  return()=>{active=false;controller.abort();stop()}
 },[token])
 const stale=!!error||!received||clock-received>10000
 const broker=data?.broker_observation
 const brokerFresh=!!broker&&!stale&&broker.status==='LIVE_READ_ONLY'&&Number.isFinite(Date.parse(broker.generated_at))&&clock-Date.parse(broker.generated_at)>=0&&clock-Date.parse(broker.generated_at)<=90000
 const bridgeHealth=data?.bridge_health
 const allocation=data?.allocation
 const allocationReady=!allocation?.required||allocation?.ready===true
 const bridgeReady=!bridgeHealth?.required||bridgeHealth?.healthy===true
 const sim=data?.workspace_mode==='SIMULATION_ONLY'
 const durable=data?.durable_execution
 const stopPending=durable?.stop_requested===true
 const canCommand=sim&&!stale&&!busy
 const action=async(name:string,positionId?:string)=>{
  if(!data||busy||!sim||(!['pause','flatten'].includes(name)&&stale))return
  if(['exit','flatten'].includes(name)&&!window.confirm('SIMULATION ONLY: '+(name==='exit'?'exit selected simulated position?':'flatten simulated positions and pause?')))return
  setBusy(true);setMessage('Awaiting backend acknowledgement…')
  try{
   const value=await call(token,{action:name,request_id:requestId(),expected_version:data.control?.version,
    session_date:data.control?.session_date,position_id:positionId??null,confirmation:'SIMULATION_ONLY'})
   setData(previous=>previous?.control&&value.snapshot.control&&previous.control.version>value.snapshot.control.version?previous:value.snapshot);setReceived(Date.now());setError('');setMessage('Backend acknowledged: '+value.snapshot.label)
  }catch(e){setMessage('Command not confirmed: '+(e as Error).message)}finally{setBusy(false)}
 }
 return <div className="up-production">
  <div className="up-warning"><strong>PRODUCTION SUBMISSION DISABLED</strong><p>This preparation workspace does not control the current Hilega/Sandbox worker. Controls below apply only to a separate simulator. No real Upstox orders are sent.</p></div>
  <div className="up-auth">
   <label>Workspace control key<input type="password" autoComplete="off" value={draft} onChange={e=>setDraft(e.target.value)} placeholder="Enter locally configured control key"/></label>
   <button disabled={!draft||busy} onClick={()=>{setToken(draft);setDraft('');setData(null);setReceived(0);setError('')}}>Connect</button>
   {token&&<button onClick={()=>{setToken('');setData(null);setReceived(0);setMessage('')}}>Disconnect display</button>}
   <small>Key stays in page memory; never in URL or browser storage. Use HTTPS or an SSH tunnel.</small>
  </div>
  {error&&<div role="alert" className="up-warning">{error}</div>}
  {token&&<div className={'up-status '+(stale?'up-stale':'')} role="status">
   <strong>{stale?'DISPLAY DISCONNECTED / STALE':data?.label}</strong>
   <span>Mode: {data?.source??'Awaiting server'}</span><span>Last received: {received?new Date(received).toLocaleTimeString():'—'}</span>
   <span>Reconciled: {data?.last_reconciled_at?new Date(data.last_reconciled_at).toLocaleTimeString():'Not verified'}</span>
  </div>}
  {data&&<>
   <div className="up-controls">
    <button disabled={!sim||busy} onClick={()=>void action('pause')}>Do not trade today — SIM</button>
    <button disabled={!canCommand||stopPending||!bridgeReady||!allocationReady||data.control?.mode==='ARMED'} onClick={()=>void action('resume')}>Start — next fresh signal — SIM</button>
    <button disabled={!sim||busy} onClick={()=>void action('flatten')}>Exit all &amp; stop today — SIM</button>
    <button disabled={!canCommand} onClick={()=>void action('reconcile')}>Reconcile simulator</button>
    <button onClick={onOpenStrategy}>Open Hilega decision audit</button>
   </div>
   <p role="status">{message}</p>
   <section className="up-panel" aria-label="Durable simulator controls"><strong>Durable simulator controls: {stale?'DISPLAY STALE':stopPending?'STOP REQUESTED — cleanup acknowledgement pending':durable?'ACTIVE':'Awaiting server'}</strong>
    <p>Reservation and entry intent commit together. Stop request: {fmt(durable?.stop_generation)} · Handled: {fmt(durable?.handled_generation)}. Established positions remain open on Pause; use Exit all to close them. Simulation only.</p>
   </section>
   <section className="up-panel" aria-label="Simulator bridge health"><strong>Simulator bridge: {stale?'DISPLAY STALE':bridgeHealth?.status??'NOT_ENABLED'}</strong>
    <p>Heartbeat age: {fmt(bridgeHealth?.heartbeat_age_seconds)}s · Source age: {fmt(bridgeHealth?.source_age_seconds)}s · PID: {fmt(bridgeHealth?.pid)} · Instance: {fmt(bridgeHealth?.instance)}</p>
    <p>Entry health required: {bridgeHealth?.required?'Yes':'No — optional reader not enabled'}. A healthy process does not arm trading. Recovery requires explicit Resume; exits remain available.</p>
   </section>
   <section className="up-panel" aria-label="Simulator allocation"><strong>Simulator allocation: {stale?'DISPLAY STALE':allocation?.status??'Awaiting server'}</strong>
    <p>SYNTHETIC CASH ONLY · Cash: {money(allocation?.synthetic_available_cash)} · 50% cap: {money(allocation?.half_cash_cap)} · Held: {money(allocation?.held_total)} · Remaining: {money(allocation?.remaining_capacity)}</p>
    <p>Funds age: {fmt(allocation?.funds_age_seconds)}s · Buffer per entry: {money(allocation?.buffer_per_entry)}. Single instrument only. Real broker funds and allocation approval remain pending.</p>
   </section>
   <nav className="up-tabs">{['Overview','Active positions','Orders & fills','Closed trades','Execution settings','Readiness & audit'].map(t=><button key={t} aria-pressed={tab===t} onClick={()=>setTab(t)}>{t}</button>)}</nav>
   {tab==='Overview'&&<section className="up-panel"><h2>Account overview</h2>
    <p>Simulator controls and broker observations are separate. Broker observations cannot submit orders or update the simulator ledger.</p>
    <h3>Upstox account — read-only evidence</h3>
    <p role="status"><strong>{stale?'DISPLAY STALE':brokerFresh?'LIVE_READ_ONLY':broker?.status==='LIVE_READ_ONLY'?'STALE':broker?.status??'NOT_ENABLED'}</strong> · Snapshot: {fmt(broker?.generated_at)} · Server age: {fmt(broker?.age_seconds)} seconds</p>
    <p>Net cash available to trade: <strong>{brokerFresh?money(broker?.funds?.cash_available_to_trade):'Unknown'}</strong> · 50% preview: {brokerFresh?money(broker?.funds?.half_cash_preview):'Unknown'} · Cash mapping pending account comparison; allocation is not approved.</p>
    <p>Pledged margin (excluded from preview): {brokerFresh?money(broker?.funds?.pledge_available_to_trade):'Unknown'}. Broker P&amp;L and strategy ownership: not validated.</p>
    <table><thead><tr><th>Read-only check</th><th>Status</th><th>Error</th></tr></thead><tbody>{(broker?.checks??[]).map((c:any)=><tr key={c.check}><td>{c.check}</td><td>{c.status}</td><td>{c.error??'—'} {c.provider_code??''}</td></tr>)}</tbody></table>
    <p>Account snapshot diagnostics: {brokerFresh?fmt(broker?.diagnostics?.status):'Unknown'}. {(broker?.diagnostics?.issues??[]).join(', ')}</p>
    <h3>Broker positions — account-wide, read-only</h3>
    {!brokerFresh||broker?.positions===null?<p>Exposure unknown or stale. No flat-account claim is made.</p>:<><div className="up-scroll"><table><thead><tr><th>Instrument</th><th>Product</th><th>Quantity</th></tr></thead><tbody>{broker.positions.map((p:any,i:number)=><tr key={i}><td>{p.instrument_token}</td><td>{p.product}</td><td>{p.quantity}</td></tr>)}</tbody></table></div><p>{broker.positions.length===0?'No position rows returned at this snapshot.':'Positions are not attributed to this strategy.'}</p></>}
    <p>Broker orders / trade fills: {brokerFresh?`${broker?.orders?.length??'Unknown'} / ${broker?.trades?.length??'Unknown'}`:'Unknown'}. These are account-wide observations, not production execution approval.</p>
    <dl><dt>Policy</dt><dd>{data.policy_id}</dd><dt>Version</dt><dd>{data.strategy_version}</dd><dt>Entry control</dt><dd>{data.control?.mode??'DISABLED'}</dd></dl>
    <h3>Blocked trades — hypothetical outcome</h3><p>Not implemented in this milestone. No hypothetical results are included in real P&amp;L.</p>
   </section>}
   {tab==='Active positions'&&<section className="up-panel"><h2>Simulator positions — no live prices</h2><div className="up-scroll"><table><thead><tr><th>Instrument</th><th>Filled / remaining</th><th>Average entry</th><th>Broker discrepancy</th><th>Live P&amp;L</th><th>Action</th></tr></thead><tbody>{data.positions.map(p=><tr key={p.position_id}><td>{p.instrument}</td><td>{p.filled_quantity} / {p.remaining_quantity}</td><td>{money(p.average_entry)}</td><td>{p.reconciliation_required?'Review required; observed '+p.external_observed_quantity:'—'}</td><td>Unavailable</td><td><button disabled={!canCommand||p.reconciliation_required} onClick={()=>void action('exit',p.position_id)}>Exit — SIM</button></td></tr>)}</tbody></table></div>{!data.positions.length&&<p>No simulated positions. Real broker exposure has not been checked.</p>}</section>}
   {tab==='Orders & fills'&&<section className="up-panel"><h2>Simulator order ledger</h2><div className="up-scroll"><table><thead><tr><th>Intent / broker ID</th><th>Instrument</th><th>Side</th><th>Quantity / filled</th><th>Status</th><th>Average</th></tr></thead><tbody>{data.orders.map(o=><tr key={o.id}><td><code>{o.id}</code><br/><code>{fmt(o.order_id)}</code></td><td>{o.instrument}</td><td>{o.side}</td><td>{o.quantity} / {o.filled}</td><td>{o.status}</td><td>{money(o.average_price)}</td></tr>)}</tbody></table></div>{!data.orders.length&&<p>No simulator orders.</p>}</section>}
   {tab==='Closed trades'&&<section className="up-panel"><h2>Closed simulator positions</h2>{data.closed_trades.map(p=><p key={p.position_id}>{p.instrument} · {p.filled_quantity} filled · remaining {p.remaining_quantity} · simulated fills only</p>)}{!data.closed_trades.length&&<p>No reconciled closed simulator trades. Realised production P&amp;L is unavailable.</p>}</section>}
   {tab==='Execution settings'&&<section className="up-panel"><h2>Agreed initial settings — preview only</h2><dl><dt>Strike offsets</dt><dd>{data.configuration.strike_offsets.join(', ')}</dd><dt>Lots per strike</dt><dd>{data.configuration.lots_per_strike}</dd><dt>Cash cap</dt><dd>50% of available trading cash, excluding noncash collateral</dd><dt>Daily loss limit</dt><dd>UNSET</dd></dl><p>Editing and production activation are not available. Live instrument mapping and cash validation remain pending. Central simulator reservations support one instrument; multi-leg execution is unavailable.</p></section>}
   {tab==='Readiness & audit'&&<section className="up-panel"><h2>Production readiness — NOT CLEARED</h2><table><thead><tr><th>Check</th><th>Status</th></tr></thead><tbody>{data.readiness_checks.map(r=><tr key={r.check}><td>{r.check}</td><td>{r.status}</td></tr>)}</tbody></table><h3>Lifecycle events — latest 200</h3>{data.events.slice().reverse().map(e=><details key={e.sequence}><summary>#{e.sequence} · {e.type} · {e.at}</summary><pre>{JSON.stringify(e,null,2)}</pre></details>)}</section>}
  </>}
 </div>
}
