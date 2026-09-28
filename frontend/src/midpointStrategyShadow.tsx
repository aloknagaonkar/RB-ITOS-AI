import { useEffect, useMemo, useState } from 'react'

type AuditEvent = {
  event_id:string
  session_date:string
  strategy:string
  version:string
  family:string
  event_timestamp:string
  event_type:string
  direction:string|null
  state_before:string|null
  state_after:string|null
  result:string|null
  reason:string|null
  underlying_price:number|null
  directional_points:number|null
  reference_type:string|null
  reference_high:number|null
  reference_low:number|null
  midpoint:number|null
  original_boundary:number|null
  futures_price:number|null
  futures_vwap:number|null
  directional_vwap_value:number|null
  evidence:Record<string,any>
  observation_only:boolean
  execution_enabled:boolean
  paper_order_enabled:boolean
  quantity:null
}

type WorkspaceStatus = {
  workspace:string
  display_name:string
  version:string
  mode:string
  families:Record<string,{enabled:boolean}>
  management:Record<string,any>
  safety:{
    observation_only:boolean
    execution_enabled:boolean
    paper_order_enabled:boolean
    quantity:null
  }
}

type Status = {
  model:string
  workspace:WorkspaceStatus
  audit_path:string
  audit_exists:boolean
  audit_record_count:number
  event_counts:Record<string,number>
  family_b_state:string
  latest_event:AuditEvent|null
  latest_entry:AuditEvent|null
  latest_plus20:AuditEvent|null
  latest_classifier:AuditEvent|null
  latest_degraded:AuditEvent|null
  latest_recovery:AuditEvent|null
  latest_rescue:AuditEvent|null
  latest_reentry:AuditEvent|null
  safety:WorkspaceStatus['safety']
}

type Timeline = {
  model:string
  count:number
  timeline:Array<{
    event_id:string
    timestamp:string
    event_type:string
    direction:string|null
    state_before:string|null
    state_after:string|null
    result:string|null
    reason:string|null
    underlying_price:number|null
    directional_points:number|null
  }>
}

const base='/api/live-shadow/midpoint-strategy'

const get=async<T,>(path:string):Promise<T>=>{
  const r=await fetch(base+path)
  if(!r.ok){
    const e=await r.json().catch(()=>null)
    throw new Error(e?.detail||'Midpoint Strategy request failed')
  }
  return r.json()
}

const words=(v:any)=>v==null?'—':String(v).replaceAll('_',' ')
const num=(v:any,d=2)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:d})
const dt=(v:string|null|undefined)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const yn=(v:any)=>v?'YES':'NO'

function Snapshot({label,event}:{label:string;event:AuditEvent|null}){
  return <article className="metric">
    <div className="metric-title"><span>{label}</span></div>
    <div className="metric-value">{event?words(event.result||event.event_type):'—'}</div>
    <div className="metric-note">
      {event?`${dt(event.event_timestamp)} · ${words(event.reason)}`:'No event yet'}
    </div>
  </article>
}

export default function MidpointStrategyShadow(){
  const [status,setStatus]=useState<Status|null>(null)
  const [timeline,setTimeline]=useState<Timeline['timeline']>([])
  const [selected,setSelected]=useState<AuditEvent|null>(null)
  const [error,setError]=useState('')
  const [loading,setLoading]=useState(true)

  const refresh=async()=>{
    try{
      const [s,t]=await Promise.all([
        get<Status>('/status'),
        get<Timeline>('/timeline?limit=250'),
      ])
      setStatus(s)
      setTimeline(t.timeline)
      setError('')
    }catch(e:any){
      setError(e?.message||'Midpoint Strategy refresh failed')
    }finally{
      setLoading(false)
    }
  }

  useEffect(()=>{
    void refresh()
    const id=window.setInterval(()=>void refresh(),5000)
    return()=>window.clearInterval(id)
  },[])

  const latestStructure=useMemo(
    ()=>status?.latest_entry??status?.latest_event??null,
    [status]
  )

  const openDetail=async(eventId:string)=>{
    try{
      const r=await get<{event:AuditEvent}>('/audit-detail?event_id='+encodeURIComponent(eventId))
      setSelected(r.event)
    }catch(e:any){
      setError(e?.message||'Audit detail failed')
    }
  }

  if(loading&&!status) return <section className="panel"><div className="empty">Loading Midpoint Strategy…</div></section>

  return <>
    {error&&<div role="alert" className="banner error">{error}</div>}

    <div className="instrument-bar">
      <div><b>MIDPOINT STRATEGY</b><span>FAMILY B · SHADOW ONLY</span></div>
      <div>
        State {words(status?.family_b_state)}
        <i/> Audit records {status?.audit_record_count??0}
        <i/> Execution OFF
      </div>
    </div>

    <div className="metrics">
      <Snapshot label="B entry" event={status?.latest_entry??null}/>
      <Snapshot label="+20 proof" event={status?.latest_plus20??null}/>
      <Snapshot label="Runner classification" event={status?.latest_classifier??null}/>
      <Snapshot label="CAP20 rescue" event={status?.latest_rescue??null}/>
      <Snapshot label="Post-rescue re-entry" event={status?.latest_reentry??null}/>
    </div>

    <section className="panel">
      <div className="panel-heading">
        <h2>Midpoint structure & lifecycle</h2>
        <button className="secondary" onClick={()=>void refresh()}>Refresh</button>
      </div>
      <div className="health-grid">
        <div className="health-body"><p><b>Family:</b> B</p><p><b>Direction:</b> {words(latestStructure?.direction)}</p></div>
        <div className="health-body"><p><b>Reference:</b> {words(latestStructure?.reference_type)}</p><p><b>Midpoint:</b> {num(latestStructure?.midpoint)}</p></div>
        <div className="health-body"><p><b>Boundary:</b> {num(latestStructure?.original_boundary)}</p><p><b>Underlying:</b> {num(status?.latest_event?.underlying_price)}</p></div>
        <div className="health-body"><p><b>Directional points:</b> {num(status?.latest_event?.directional_points)}</p><p><b>Directional VWAP:</b> {num(status?.latest_event?.directional_vwap_value)}</p></div>
      </div>
    </section>

    <section className="panel">
      <div className="panel-heading"><h2>Family rollout</h2></div>
      <div className="health-grid">
        {Object.entries(status?.workspace.families??{}).map(([family,v])=>
          <div className="health-body" key={family}><p><b>{family}</b></p><p>{v.enabled?'ENABLED':'DISABLED'}</p></div>
        )}
      </div>
    </section>

    <section className="panel">
      <div className="panel-heading"><h2>Safety</h2></div>
      <div className="health-grid">
        <div className="health-body"><p><b>Observation only:</b> {yn(status?.safety.observation_only)}</p></div>
        <div className="health-body"><p><b>Execution enabled:</b> {yn(status?.safety.execution_enabled)}</p></div>
        <div className="health-body"><p><b>Paper order enabled:</b> {yn(status?.safety.paper_order_enabled)}</p></div>
        <div className="health-body"><p><b>Quantity:</b> {status?.safety.quantity??'None'}</p></div>
      </div>
    </section>

    <section className="panel">
      <div className="panel-heading"><h2>Auditable timeline</h2></div>
      <div style={{overflowX:'auto'}}>
        <table>
          <thead><tr>
            <th>Time</th><th>Event</th><th>Direction</th><th>State</th>
            <th>Result</th><th>Reason</th><th>Points</th><th>Audit</th>
          </tr></thead>
          <tbody>
            {[...timeline].reverse().map(x=><tr key={x.event_id}>
              <td>{dt(x.timestamp)}</td>
              <td>{words(x.event_type)}</td>
              <td>{words(x.direction)}</td>
              <td>{words(x.state_after||x.state_before)}</td>
              <td>{words(x.result)}</td>
              <td>{words(x.reason)}</td>
              <td>{num(x.directional_points)}</td>
              <td><button className="secondary" onClick={()=>void openDetail(x.event_id)}>Inspect</button></td>
            </tr>)}
            {!timeline.length&&<tr><td colSpan={8} className="empty">No Midpoint audit evidence yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>

    {selected&&<section className="panel">
      <div className="panel-heading">
        <h2>Audit evidence</h2>
        <button className="secondary" onClick={()=>setSelected(null)}>Close</button>
      </div>
      <div className="health-body">
        <p><b>Event:</b> {words(selected.event_type)} · <b>ID:</b> {selected.event_id}</p>
        <p><b>Timestamp:</b> {dt(selected.event_timestamp)}</p>
        <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(selected,null,2)}</pre>
      </div>
    </section>}
  </>
}
