import { useEffect, useMemo, useState } from 'react'
import './historicalReplayOperations.css'

type Props={ sessionDate:string; onReplayComplete?:()=>void }
type Job={ job_id:string; action:string; session_date:string; status:string;
  started_at?:string|null; completed_at?:string|null; result?:any; error?:string|null }

async function requestJson(url:string,init?:RequestInit){
  const r=await fetch(url,init)
  const value=await r.json().catch(()=>({}))
  if(!r.ok) throw new Error(typeof value?.detail==='string'?value.detail:JSON.stringify(value?.detail||value))
  return value
}
function statusOf(value:any){
  if(!value) return 'UNKNOWN'
  return String(value.status??value.state??value.availability??'UNKNOWN')
}
function datasetRows(readiness:any){
  const r=readiness||{}
  if(Array.isArray(r.datasets)) return r.datasets
  const keys=['snapshots','futures','exact_option','option_minutes','catalog']
  return keys.filter(k=>r[k]!=null).map(k=>({name:k,...(typeof r[k]==='object'?r[k]:{status:r[k]})}))
}

export default function HistoricalReplayOperations({sessionDate,onReplayComplete}:Props){
  const [readiness,setReadiness]=useState<any>(null)
  const [job,setJob]=useState<Job|null>(null)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')

  const refreshReadiness=async()=>{
    if(!sessionDate) return
    setError('')
    const value=await requestJson(`/api/live-shadow/replay-ops/readiness?session_date=${encodeURIComponent(sessionDate)}`)
    setReadiness(value.readiness)
  }

  useEffect(()=>{ if(sessionDate) void refreshReadiness().catch(e=>setError(String(e))) },[sessionDate])

  useEffect(()=>{
    if(!job || !['QUEUED','RUNNING'].includes(job.status)) return
    let active=true
    const poll=async()=>{
      try{
        const next=await requestJson(`/api/live-shadow/replay-ops/job/${job.job_id}`)
        if(!active) return
        setJob(next)
        if(next.status==='COMPLETE'){
          setBusy(false)
          await refreshReadiness()
          if(next.action==='RUN_REPLAY') onReplayComplete?.()
        }else if(next.status==='FAILED'){
          setBusy(false)
        }
      }catch(e){
        if(active){setBusy(false);setError(String(e))}
      }
    }
    const id=setInterval(()=>void poll(),1500)
    void poll()
    return()=>{active=false;clearInterval(id)}
  },[job?.job_id,job?.status])

  const rows=useMemo(()=>datasetRows(readiness),[readiness])
  const checkpointReady=Boolean(
    readiness?.checkpoint_replay_ready ??
    readiness?.checkpoint_ready ??
    readiness?.full_replay_prerequisites_ready ??
    readiness?.full_trade_replay_prerequisites_ready
  )

  const start=async(action:'download'|'run')=>{
    if(!sessionDate)return
    setBusy(true);setError('')
    try{
      const url=action==='download'?'/api/live-shadow/replay-ops/download-missing':'/api/live-shadow/replay-ops/run'
      const body=action==='download'?{session_date:sessionDate}:{session_date:sessionDate,overwrite:true}
      const next=await requestJson(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
      setJob(next)
    }catch(e){
      setBusy(false);setError(String(e))
    }
  }

  return <section className="hr-ops">
    <div className="hr-ops-head">
      <div><h3>Replay operations</h3><p>Readiness → download missing data → causal replay. Observation only.</p></div>
      <button disabled={busy||!sessionDate} onClick={()=>void refreshReadiness().catch(e=>setError(String(e)))}>Check readiness</button>
    </div>
    {error&&<div className="hr-ops-error">{error}</div>}
    <div className="hr-ops-state">
      <div><span>Date</span><b>{sessionDate||'—'}</b></div>
      <div><span>Checkpoint replay</span><b>{checkpointReady?'READY':'NOT READY'}</b></div>
      <div><span>Execution</span><b>DISABLED</b></div>
      <div><span>Paper orders</span><b>DISABLED</b></div>
    </div>
    {rows.length>0&&<div className="hr-ops-datasets">
      {rows.map((row:any,i:number)=><div key={`${row.name||row.dataset||i}`}>
        <b>{String(row.name||row.dataset||`dataset ${i+1}`).replaceAll('_',' ')}</b>
        <span>{statusOf(row)}</span>
        {row.records!=null&&<small>{row.records} records</small>}
        {row.detail&&<small>{String(row.detail)}</small>}
      </div>)}
    </div>}
    <div className="hr-ops-actions">
      <button disabled={busy||!sessionDate} onClick={()=>void start('download')}>Download missing</button>
      <button disabled={busy||!sessionDate||!checkpointReady} onClick={()=>void start('run')}>Run replay</button>
    </div>
    {job&&<div className={`hr-ops-job hr-job-${job.status.toLowerCase()}`}>
      <div><b>{job.action}</b><span>{job.status}</span></div>
      <small>Job {job.job_id}</small>
      {job.started_at&&<small>Started {job.started_at}</small>}
      {job.completed_at&&<small>Completed {job.completed_at}</small>}
      {job.error&&<div className="hr-ops-error">{job.error}</div>}
      {['QUEUED','RUNNING'].includes(job.status)&&<div className="hr-ops-progress"><span/></div>}
    </div>}
  </section>
}
