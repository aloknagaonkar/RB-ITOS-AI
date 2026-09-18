import { useEffect, useMemo, useState } from 'react'
import './historicalReplay.css'

type Session = {
  session_date:string
  status:string
  checkpoint_count?:number|null
  processed_checkpoint_count?:number|null
  missing_checkpoint_count?:number|null
  observation_count?:number|null
  state_counts?:Record<string,number>
  step_audit_chain_ok?:boolean|null
}

type AuditRow = {
  checkpoint:string|null
  event_time:string
  observation_id:string|null
  stage:string
  status:string
  payload:Record<string,any>
}

type TimelineRow = {
  checkpoint:string
  snapshot_selection:AuditRow|null
  normalized_features:AuditRow|null
  data_health:AuditRow|null
  all3_decision:AuditRow|null
  candidate_detection:AuditRow|null
  candidate_steps:AuditRow[]
  observation_ids:string[]
  observation_events:Record<string,any[]>
  summary:{
    spot:number|null
    moving_atm:number|null
    state_5m:string|null
    state_10m:string|null
    state_15m:string|null
    all3_state:string|null
    candidate:string|null
    health:string|null
  }
}

const shortTime=(value?:string|null)=>{
  if(!value) return '—'
  const d=new Date(value)
  return Number.isNaN(d.getTime()) ? value.slice(11,16) : d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',hour12:false})
}

const n=(value:any,digits=2)=>value==null?'—':Number(value).toFixed(digits)

function badge(value?:string|null){
  const text=value||'—'
  const key=text.toLowerCase().replaceAll('_','-')
  return <span className={`hr-badge hr-${key}`}>{text}</span>
}

function Horizon({name,data}:{name:string,data:any}){
  if(!data) return <div className="hr-horizon"><b>{name}</b><span>Unavailable</span></div>
  return <div className="hr-horizon">
    <b>{name} {badge(data.state)}</b>
    <span>CE Δ {n(data.ce_delta,0)}</span>
    <span>PE Δ {n(data.pe_delta,0)}</span>
    <span>Imbalance {n(data.imbalance,0)}</span>
    <span>PCR {n(data.prior_pcr,4)} → {n(data.current_pcr,4)}</span>
    <span>PCR Δ {n(data.pcr_change,4)}</span>
  </div>
}

function CheckpointDetail({row}:{row:TimelineRow}){
  const f=row.normalized_features?.payload||{}
  const horizons=f.horizons||{}
  const lifecycle=[...(row.candidate_steps||[])]
  const events=Object.entries(row.observation_events||{}).flatMap(([oid,items])=>
    (items||[]).map((event:any)=>({...event,_oid:oid}))
  )
  return <div className="hr-detail">
    <div className="hr-detail-grid">
      <div><b>Spot</b><span>{n(f.spot)}</span></div>
      <div><b>Moving ATM</b><span>{n(f.moving_atm,0)}</span></div>
      <div><b>Health</b><span>{badge(row.data_health?.status)}</span></div>
      <div><b>ALL3</b><span>{badge(row.all3_decision?.status)}</span></div>
      <div><b>Candidate</b><span>{badge(row.candidate_detection?.status)}</span></div>
      <div><b>Exact strikes</b><span>{(f.moving_strikes||[]).join(', ')||'—'}</span></div>
    </div>

    <div className="hr-horizons">
      <Horizon name="5m" data={horizons['5m']}/>
      <Horizon name="10m" data={horizons['10m']}/>
      <Horizon name="15m" data={horizons['15m']}/>
    </div>

    <h4>Strategy progression</h4>
    {!lifecycle.length && !events.length
      ? <div className="hr-empty">No candidate lifecycle at this checkpoint.</div>
      : <div className="hr-lifecycle">
          {lifecycle.map((step,i)=><div className="hr-life-row" key={`a-${i}`}>
            <span>{shortTime(step.event_time)}</span>
            <b>{step.stage}</b>
            {badge(step.status)}
            <code>{step.observation_id||''}</code>
          </div>)}
          {events.map((event:any,i)=><div className="hr-life-row" key={`e-${i}`}>
            <span>{shortTime(event.event_time)}</span>
            <b>{event.event_type}</b>
            <span>{event.payload?.exit_reason||event.payload?.futures_oi_state||event.payload?.option_side||''}</span>
            <code>{event._oid}</code>
          </div>)}
        </div>}
  </div>
}

export default function HistoricalReplay(){
  const [sessions,setSessions]=useState<Session[]>([])
  const [selected,setSelected]=useState('')
  const [timeline,setTimeline]=useState<TimelineRow[]>([])
  const [status,setStatus]=useState<any>(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const [expanded,setExpanded]=useState<string|null>(null)

  useEffect(()=>{
    fetch('/api/live-shadow/replay/sessions')
      .then(r=>{if(!r.ok) throw new Error('Replay sessions unavailable'); return r.json()})
      .then(data=>{
        const rows:Session[]=data.sessions||[]
        setSessions(rows)
        if(rows.length) setSelected(current=>current||rows[0].session_date)
      })
      .catch(e=>setError(String(e)))
  },[])

  useEffect(()=>{
    if(!selected) return
    let active=true
    setLoading(true); setError('')
    Promise.all([
      fetch(`/api/live-shadow/replay/status?date=${encodeURIComponent(selected)}`).then(r=>{if(!r.ok) throw new Error('Replay status unavailable');return r.json()}),
      fetch(`/api/live-shadow/replay/timeline?date=${encodeURIComponent(selected)}`).then(r=>{if(!r.ok) throw new Error('Replay timeline unavailable');return r.json()}),
    ]).then(([s,t])=>{
      if(!active)return
      setStatus(s.status||null)
      setTimeline(t.rows||[])
    }).catch(e=>{if(active)setError(String(e))})
      .finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[selected])

  const closed=useMemo(()=>status?.state_counts?.CLOSED||0,[status])
  const open=useMemo(()=>['OPEN','BE_ARMED','TRAIL_ARMED'].reduce((x,k)=>x+(status?.state_counts?.[k]||0),0),[status])

  return <section className="historical-replay">
    <div className="hr-head">
      <div>
        <h2>Historical Replay</h2>
        <p>Current Live Shadow strategy · chronological causal replay · observation only</p>
      </div>
      <label>Date
        <select value={selected} onChange={e=>setSelected(e.target.value)}>
          {!sessions.length&&<option value="">No replay sessions</option>}
          {sessions.map(s=><option key={s.session_date} value={s.session_date}>{s.session_date}</option>)}
        </select>
      </label>
    </div>

    {error&&<div className="hr-error">{error}</div>}

    <div className="hr-cards">
      <div><span>Analysis</span><b>{status?.status|| (loading?'LOADING':'—')}</b></div>
      <div><span>Checkpoints</span><b>{status?.processed_checkpoint_count??'—'} / {status?.checkpoint_count??'—'}</b></div>
      <div><span>Observations</span><b>{status?.observation_count??'—'}</b></div>
      <div><span>Open</span><b>{open}</b></div>
      <div><span>Closed</span><b>{closed}</b></div>
      <div><span>Audit chain</span><b>{status?.step_audit_chain_ok===true?'OK':status?.step_audit_chain_ok===false?'FAILED':'—'}</b></div>
    </div>

    <div className="hr-table-wrap">
      <table className="hr-table">
        <thead><tr>
          <th>Time</th><th>Spot</th><th>ATM</th>
          <th>5m</th><th>10m</th><th>15m</th><th>ALL3</th>
          <th>Candidate</th><th>Health</th><th>Details</th>
        </tr></thead>
        <tbody>
        {timeline.map(row=>{
          const isOpen=expanded===row.checkpoint
          return <>
            <tr key={row.checkpoint} className={row.observation_ids.length?'hr-candidate-row':''}>
              <td>{shortTime(row.checkpoint)}</td>
              <td>{n(row.summary.spot)}</td>
              <td>{n(row.summary.moving_atm,0)}</td>
              <td>{badge(row.summary.state_5m)}</td>
              <td>{badge(row.summary.state_10m)}</td>
              <td>{badge(row.summary.state_15m)}</td>
              <td>{badge(row.summary.all3_state)}</td>
              <td>{badge(row.summary.candidate)}</td>
              <td>{badge(row.summary.health)}</td>
              <td><button onClick={()=>setExpanded(isOpen?null:row.checkpoint)}>{isOpen?'Hide':'Audit'}</button></td>
            </tr>
            {isOpen&&<tr key={`${row.checkpoint}-detail`}><td colSpan={10}><CheckpointDetail row={row}/></td></tr>}
          </>
        })}
        {!loading&&!timeline.length&&<tr><td colSpan={10} className="hr-empty">No replay timeline found.</td></tr>}
        </tbody>
      </table>
    </div>
  </section>
}
