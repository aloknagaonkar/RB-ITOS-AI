import { useEffect, useMemo, useState } from 'react'

type Direction='BULLISH'|'BEARISH'|'NONE'|string
type Status={
  strategy_id:string
  selected_live_shadow_strategy:string|null
  directional_mode_active:boolean
  observation_only:boolean
  execution_enabled:boolean
  paper_order_enabled:boolean
  option_selection_enabled:boolean
  step_audit_chain_ok:boolean
  step_audit_chain_issue:string|null
  current:{
    trade_owner:Direction
    bullish_state:string|null
    bearish_state:string|null
    bullish_armed:boolean|null
    bearish_armed:boolean|null
    last_completed_bar:string|null
  }
  latest_accepted_record:Record<string,any>|null
  latest_suppressed_record:Record<string,any>|null
}
type EventRow={
  event_time:string|null
  checkpoint:string|null
  stage:string
  status:string
  bar_timestamp:string|null
  trade_owner_before:string|null
  trade_owner_after:string|null
  bullish_state:string|null
  bearish_state:string|null
  bullish_armed:boolean|null
  bearish_armed:boolean|null
  accepted_events:string[]
  suppressed_events:string[]
  note:string|null
}
type TradeLeg={
  relation_to_atm:number
  strike:number
  side:string
  instrument_key:string
  entry_timestamp:string|null
  entry_open:number|null
  latest_completed_minute:string|null
  latest_close:number|null
  current_points:number|null
  current_return_pct:number|null
  mfe_points:number|null
  mae_points:number|null
  exit_timestamp:string|null
  exit_open:number|null
  realized_points:number|null
  realized_return_pct:number|null
}
type Trade={
  direction:Direction
  option_side:'CE'|'PE'|string
  signal_bar:string
  signal_boundary:string|null
  signal_spot:number|null
  source:string|null
  expiry:string|null
  atm:number|null
  status:string
  complete:boolean
  issue:string|null
  exit_reason:string|null
  pending_exit_boundary:string|null
  legs:TradeLeg[]
}
type Dashboard={
  warning:string
  coverage_note:string
  trade_count:number
  active_count:number
  complete_closed_count:number
  pending_exit_count:number
  incomplete_count:number
  by_direction:Record<string,{trade_count:number;active_count:number;closed_count:number;incomplete_count:number}>
  trades:Trade[]
}

const base='/api/live-shadow/hilega-directional'
const get=async<T,>(path:string):Promise<T>=>{
  const r=await fetch(base+path)
  if(!r.ok){const e=await r.json().catch(()=>null);throw new Error(e?.detail||'Directional Hilega request failed')}
  return r.json()
}
const tm=(v:string|null|undefined)=>v?new Date(v).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const num=(v:any,d=2)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:d})
const words=(v:any)=>v==null?'—':String(v).replaceAll('_',' ')
const signed=(v:number|null|undefined)=>v==null?'—':`${v>0?'+':''}${num(v)}`
const role=(r:number)=>r===0?'ATM':`ATM${r>0?'+':''}${r}`
const plusMinutes=(v:string|null|undefined,m:number)=>{
  if(!v)return null
  const ms=new Date(v).getTime()
  return Number.isFinite(ms)?new Date(ms+m*60_000).toISOString():null
}
const candleWindow=(v:string|null|undefined)=>!v?'—':`${tm(v).slice(0,5)}–${tm(plusMinutes(v,5)).slice(0,5)}`
const lastEvents=(r:Record<string,any>|null,key:'accepted_events'|'suppressed_events')=>{
  const a=(r?.payload?.[key]??[]) as string[]
  return a.length?a.map(words).join(', '):'—'
}

function TradeCard({t}:{t:Trade}){
  const side=t.option_side
  const active=String(t.status).toUpperCase()==='ACTIVE'
  return <article className="hilega-trade-card">
    <div className="hilega-trade-head"><div>
      <b>{words(t.direction)} · {side} · Signal candle {candleWindow(t.signal_bar)}</b> <span className="shadow-stage">{words(t.status)}</span>
      <small>Route/source {words(t.source)} · Decision boundary {tm(t.signal_boundary??plusMinutes(t.signal_bar,5))} · Expiry {t.expiry??'—'} · ATM {num(t.atm,0)} · Signal NIFTY {num(t.signal_spot)}</small>
    </div></div>
    {t.issue&&<div className="hilega-dashboard-warning">Data limitation: {t.issue}</div>}
    {String(t.status).toUpperCase()==='PENDING_EXACT_EXIT'&&<div className="hilega-dashboard-warning">Underlying strategy has exited. Awaiting the exact causal {side} exit-minute OPEN at {tm(t.pending_exit_boundary)}.</div>}
    {t.legs.length>0&&<div className="shadow-table-scroll"><table className="shadow-table hilega-economics-table"><thead><tr>
      <th>{side}</th><th>Entry time</th><th>Entry premium</th>
      {active?<><th>Latest premium</th><th>Current pts</th><th>Current %</th></>:<><th>Exit time</th><th>Exit premium</th><th>Realized pts</th><th>Realized %</th></>}
      <th>MFE</th><th>MAE</th>
    </tr></thead><tbody>{t.legs.map(l=><tr key={l.instrument_key}>
      <td>{role(l.relation_to_atm)} · {num(l.strike,0)} {side}</td>
      <td>{tm(l.entry_timestamp)}</td><td>{num(l.entry_open)}</td>
      {active?<><td>{num(l.latest_close)}</td><td className={l.current_points==null?'':l.current_points>=0?'positive':'negative'}>{signed(l.current_points)}</td><td>{l.current_return_pct==null?'—':`${signed(l.current_return_pct)}%`}</td></>
      :<><td>{tm(l.exit_timestamp)}</td><td>{num(l.exit_open)}</td><td className={l.realized_points==null?'':l.realized_points>=0?'positive':'negative'}>{signed(l.realized_points)}</td><td>{l.realized_return_pct==null?'—':`${signed(l.realized_return_pct)}%`}</td></>}
      <td>{num(l.mfe_points)}</td><td>{num(l.mae_points)}</td>
    </tr>)}</tbody></table></div>}
    {!active&&<small>Exit reason: {words(t.exit_reason)}</small>}
  </article>
}

export default function HilegaMilegaShadow(){
  const [status,setStatus]=useState<Status|null>(null)
  const [events,setEvents]=useState<EventRow[]>([])
  const [dashboard,setDashboard]=useState<Dashboard|null>(null)
  const [error,setError]=useState('')
  const refresh=async()=>{
    const [s,e,d]=await Promise.all([
      get<Status>('/status'),
      get<EventRow[]>('/events?limit=200'),
      get<Dashboard>('/trade-dashboard'),
    ])
    setStatus(s);setEvents(e);setDashboard(d);setError('')
  }
  useEffect(()=>{let active=true;const poll=()=>void refresh().catch(e=>active&&setError((e as Error).message));poll();const t=setInterval(poll,5000);return()=>{active=false;clearInterval(t)}},[])
  const activeTrades=useMemo(()=>dashboard?.trades.filter(t=>String(t.status).toUpperCase()==='ACTIVE')??[],[dashboard])
  const exitedTrades=useMemo(()=>dashboard?.trades.filter(t=>String(t.status).toUpperCase()!=='ACTIVE')??[],[dashboard])
  const owner=status?.current.trade_owner??'NONE'
  return <div className="shadow-page hilega-page">
    {error&&<div className="banner error">{error}</div>}
    {!status?.directional_mode_active&&status&&<div className="banner error">Directional UI is available, but LIVE_SHADOW_STRATEGY is currently {status.selected_live_shadow_strategy??'not configured'}.</div>}
    <div className="shadow-safety"><b>HILEGA DIRECTIONAL · OBSERVATION ONLY</b><span>Execution disabled</span><span>Paper orders disabled</span><span>No CE/PE selector</span><span>Five independent ATM±2 option observations</span><span>Audit chain {status?.step_audit_chain_ok?'healthy':'check'}</span></div>

    <div className="shadow-metrics hilega-dashboard-summary">
      <article><span>Trade owner</span><b>{words(owner)}</b><small>Exclusive ACTIVE owner from coordinator</small></article>
      <article><span>Bullish state</span><b>{words(status?.current.bullish_state)}</b><small>Armed {status?.current.bullish_armed?'YES':'NO'}</small></article>
      <article><span>Bearish state</span><b>{words(status?.current.bearish_state)}</b><small>Armed {status?.current.bearish_armed?'YES':'NO'}</small></article>
      <article><span>Last completed bar</span><b>{tm(status?.current.last_completed_bar)}</b><small>Latest coordinator state checkpoint</small></article>
      <article><span>Last accepted event</span><b>{lastEvents(status?.latest_accepted_record,'accepted_events')}</b><small>{tm(status?.latest_accepted_record?.event_time)}</small></article>
      <article><span>Last suppressed event</span><b>{lastEvents(status?.latest_suppressed_record,'suppressed_events')}</b><small>{tm(status?.latest_suppressed_record?.event_time)}</small></article>
    </div>

    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>Active directional option shadow</h2><p>BULLISH owner tracks CE ATM±2; BEARISH owner tracks PE ATM±2. Direction is read from the coordinator audit, never inferred by the UI.</p></div><span className="pill teal">{activeTrades.length?`${activeTrades.length} ACTIVE`:'NO ACTIVE TRADE'}</span></div>
      {!dashboard?<div className="empty">Loading active trade…</div>:!activeTrades.length?<div className="empty">No active directional option shadow trade.</div>:<div className="hilega-ledger">{activeTrades.map(t=><TradeCard key={`${t.direction}-${t.signal_bar}`} t={t}/>)}</div>}
    </section>

    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>Directional coordinator activity</h2><p>Accepted and suppressed events, owner hand-offs, and independent bullish/bearish state.</p></div><span className="pill teal">LIVE · OBSERVATION ONLY</span></div>
      {!events.length?<div className="empty">No directional coordinator records yet.</div>:<div className="shadow-table-scroll"><table className="shadow-table"><thead><tr><th>Time</th><th>Owner</th><th>Bullish state</th><th>Bearish state</th><th>Accepted</th><th>Suppressed</th></tr></thead><tbody>
        {events.map((e,i)=><tr key={`${e.event_time}-${i}`}><td>{tm(e.bar_timestamp??e.event_time)}</td><td>{words(e.trade_owner_before)} → {words(e.trade_owner_after)}</td><td>{words(e.bullish_state)}</td><td>{words(e.bearish_state)}</td><td>{e.accepted_events.length?e.accepted_events.map(words).join(', '):'—'}</td><td>{e.suppressed_events.length?e.suppressed_events.map(words).join(', '):'—'}</td></tr>)}
      </tbody></table></div>}
    </section>

    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>Exited directional shadow trades</h2><p>Combined CE and PE observations recorded by the directional live audit. Five ATM±2 legs remain independent observations.</p></div><span className="pill teal">{exitedTrades.length} EXITED / NON-ACTIVE</span></div>
      {dashboard&&<div className="hilega-dashboard-warning">{dashboard.coverage_note}</div>}
      {!dashboard?<div className="empty">Loading exited trades…</div>:!exitedTrades.length?<div className="empty">No exited directional option lifecycle has been recorded since directional activation.</div>:<div className="hilega-ledger">{exitedTrades.map(t=><TradeCard key={`${t.direction}-${t.signal_bar}`} t={t}/>)}</div>}
    </section>
  </div>
}
