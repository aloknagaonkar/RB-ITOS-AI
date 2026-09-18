import { useEffect, useMemo, useState } from 'react'

type ShadowStatus = {
  observation_only:boolean
  execution_enabled:boolean
  paper_order_enabled:boolean
  event_chain_ok:boolean
  event_chain_issue:string|null
  observation_count:number
  open_trade_count:number
  closed_trade_count:number
  rejected_count:number
  incomplete_count:number
  latest_health:Record<string,unknown>|null
}

type ShadowObservation = {
  observation_id:string
  session_date:string
  direction:'BULLISH'|'BEARISH'
  status:string
  all3_candle1_timestamp:string|null
  confirmation_timestamp:string|null
  all3_state:string|null
  futures_oi_state:string|null
  futures_aligned:boolean|null
  spot_c1:number|null
  spot_c2:number|null
  price_lag_class:string|null
  atm_strike:number|null
  option_side:string|null
  option_instrument_key:string|null
  entry_timestamp:string|null
  entry_price:number|null
  active_stop_price:number|null
  best_price_seen:number|null
  breakeven_armed:boolean
  trail_armed:boolean
  exit_timestamp:string|null
  exit_price:number|null
  exit_reason:string|null
  gross_return_pct:number|null
  net_return_pct:number|null
  mfe_pct:number|null
  mae_pct:number|null
  last_bar_timestamp:string|null
  rejection_reason:string|null
}

type AuditEvent = {
  global_sequence:number
  event_type:string
  event_time:string
  payload:Record<string,unknown>
}

type ObservationDetail = {
  observation:ShadowObservation
  events:AuditEvent[]
}

const api = async <T,>(path:string):Promise<T> => {
  const response = await fetch('/api/live-shadow' + path)
  if (!response.ok) {
    const value = await response.json().catch(()=>null)
    throw new Error(value?.detail || 'Live shadow request failed')
  }
  return response.json()
}
const words=(v:string|null|undefined)=>v ? v.replaceAll('_',' ') : '—'
const fmt=(v:number|null|undefined,d=2)=>v==null?'—':v.toLocaleString('en-IN',{maximumFractionDigits:d})
const pct=(v:number|null|undefined)=>v==null?'—':`${v>0?'+':''}${v.toFixed(2)}%`
const dt=(v:string|null|undefined)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const tm=(v:string|null|undefined)=>v?new Date(v).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'

function Stage({value}:{value:string}) {
  return <span className={`shadow-stage ${value.toLowerCase()}`}>{words(value)}</span>
}
function HealthBadge({value}:{value:string}) {
  return <span className={`shadow-health ${value.toLowerCase()}`}>{words(value)}</span>
}

export default function LiveShadowMonitor() {
  const [status,setStatus]=useState<ShadowStatus|null>(null)
  const [observations,setObservations]=useState<ShadowObservation[]>([])
  const [health,setHealth]=useState<Record<string,unknown>[]>([])
  const [selected,setSelected]=useState<string|null>(null)
  const [detail,setDetail]=useState<ObservationDetail|null>(null)
  const [error,setError]=useState('')
  const refresh=async()=>{
    const [s,o,h]=await Promise.all([
      api<ShadowStatus>('/status'),
      api<ShadowObservation[]>('/observations?limit=100'),
      api<Record<string,unknown>[]>('/health?limit=30'),
    ])
    setStatus(s);setObservations(o);setHealth(h);setError('')
    if (!selected && o.length) setSelected(o[0].observation_id)
  }
  useEffect(()=>{
    let active=true
    const poll=()=>void refresh().catch(e=>{if(active)setError((e as Error).message)})
    poll(); const timer=setInterval(poll,3000)
    return()=>{active=false;clearInterval(timer)}
  },[])
  useEffect(()=>{
    let active=true
    if (!selected){setDetail(null);return}
    void api<ObservationDetail>('/observation/'+encodeURIComponent(selected))
      .then(v=>{if(active)setDetail(v)})
      .catch(e=>{if(active)setError((e as Error).message)})
    return()=>{active=false}
  },[selected,observations])

  const latestHealth=(health[0]??status?.latest_health??{}) as Record<string,unknown>
  const healthState=String(latestHealth.health_state ?? latestHealth.state ?? 'NO DATA')
  const live=useMemo(()=>observations.filter(o=>['OPEN','BE_ARMED','TRAIL_ARMED'].includes(o.status)),[observations])
  const closed=useMemo(()=>observations.filter(o=>o.status==='CLOSED'),[observations])
  const net=closed.reduce((sum,o)=>sum+(o.net_return_pct??0),0)

  return <div className="shadow-page">
    {error&&<div className="banner error">{error}</div>}
    <div className="shadow-safety">
      <b>OBSERVATION ONLY</b>
      <span>Execution disabled</span><span>Paper orders disabled</span>
      <span>Broker order path unavailable</span>
      <span>Refresh 3s</span>
    </div>

    <div className="shadow-metrics">
      <article><span>Observations</span><b>{status?.observation_count??0}</b><small>{status?.rejected_count??0} rejected · {status?.incomplete_count??0} incomplete</small></article>
      <article><span>Open shadow trades</span><b>{status?.open_trade_count??0}</b><small>Hypothetical only</small></article>
      <article><span>Closed today/session</span><b>{status?.closed_trade_count??0}</b><small>Recorded shadow exits</small></article>
      <article><span>Net shadow return</span><b className={net>=0?'positive':'negative'}>{pct(net)}</b><small>Sum of recorded net-return %-points</small></article>
      <article><span>Data health</span><b><HealthBadge value={healthState}/></b><small>{String(latestHealth.health_reason??latestHealth.reason??'Latest checkpoint')}</small></article>
      <article><span>Audit chain</span><b><HealthBadge value={status?.event_chain_ok?'HEALTHY':'UNHEALTHY'}/></b><small>{status?.event_chain_issue??'Hash chain verifies'}</small></article>
    </div>

    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>Live observations</h2><p>Every candidate, rejection, open shadow trade and close is retained.</p></div><span className="pill teal">{live.length} OPEN</span></div>
      {!observations.length?<div className="empty">No shadow observations yet. Checkpoints and health can still be monitored below.</div>:
      <div className="shadow-table-scroll"><table className="shadow-table"><thead><tr>
        <th>Detected</th><th>Dir</th><th>Stage</th><th>ALL3</th><th>Futures</th><th>Spot</th><th>Option</th><th>Entry</th><th>Stop</th><th>Net P&amp;L</th>
      </tr></thead><tbody>{observations.map(o=><tr key={o.observation_id} className={selected===o.observation_id?'selected':''} onClick={()=>setSelected(o.observation_id)}>
        <td>{tm(o.all3_candle1_timestamp)}</td><td className={o.direction==='BULLISH'?'positive':'negative'}>{o.direction}</td><td><Stage value={o.status}/></td>
        <td>{words(o.all3_state)}</td><td>{words(o.futures_oi_state)}</td><td>{words(o.price_lag_class)}</td>
        <td>{o.atm_strike==null?'—':`${fmt(o.atm_strike,0)} ${o.option_side??''}`}</td><td>{fmt(o.entry_price)}</td><td>{fmt(o.active_stop_price)}</td>
        <td className={(o.net_return_pct??0)>=0?'positive':'negative'}>{pct(o.net_return_pct)}</td>
      </tr>)}</tbody></table></div>}
    </section>

    <div className="shadow-columns">
      <section className="panel shadow-panel">
        <div className="panel-heading"><div><h2>Observation audit trail</h2><p>{detail?.observation.observation_id??'Select an observation'}</p></div></div>
        {!detail?<div className="empty">Select an observation to inspect every processing step.</div>:
        <>
          <div className="shadow-detail-grid">
            <span>Direction <b>{detail.observation.direction}</b></span>
            <span>Detected <b>{dt(detail.observation.all3_candle1_timestamp)}</b></span>
            <span>C2 <b>{dt(detail.observation.confirmation_timestamp)}</b></span>
            <span>Spot class <b>{words(detail.observation.price_lag_class)}</b></span>
            <span>Instrument <b>{detail.observation.option_instrument_key??'—'}</b></span>
            <span>Entry <b>{fmt(detail.observation.entry_price)} @ {tm(detail.observation.entry_timestamp)}</b></span>
            <span>Best premium <b>{fmt(detail.observation.best_price_seen)}</b></span>
            <span>Active stop <b>{fmt(detail.observation.active_stop_price)}</b></span>
            <span>BE / Trail <b>{detail.observation.breakeven_armed?'YES':'NO'} / {detail.observation.trail_armed?'YES':'NO'}</b></span>
            <span>Exit <b>{fmt(detail.observation.exit_price)} · {words(detail.observation.exit_reason)}</b></span>
            <span>MFE / MAE <b>{pct(detail.observation.mfe_pct)} / {pct(detail.observation.mae_pct)}</b></span>
            <span>Net return <b>{pct(detail.observation.net_return_pct)}</b></span>
          </div>
          <div className="shadow-timeline">{detail.events.map(e=><div key={e.global_sequence} className="shadow-event">
            <time>{tm(e.event_time)}</time><i/><div><b>{words(e.event_type)}</b><small>#{e.global_sequence}</small>
            {Object.keys(e.payload??{}).length>0&&<pre>{JSON.stringify(e.payload,null,2)}</pre>}</div>
          </div>)}</div>
        </>}
      </section>

      <section className="panel shadow-panel">
        <div className="panel-heading"><div><h2>Data health</h2><p>Latest production checkpoint health records.</p></div></div>
        {!health.length?<div className="empty">No shadow health records yet.</div>:
        <div className="shadow-health-list">{health.map((h,i)=>{
          const state=String(h.health_state??h.state??'UNKNOWN')
          return <article key={i}><div><HealthBadge value={state}/><b>{String(h.checkpoint??'')}</b></div>
            <p>{String(h.health_reason??h.reason??'No issue reported')}</p>
            <small>Delay {h.source_delay_ms==null?'—':`${fmt(Number(h.source_delay_ms),0)} ms`} · ALL3 {String(h.all3_state??'—')}</small>
          </article>
        })}</div>}
      </section>
    </div>
  </div>
}
