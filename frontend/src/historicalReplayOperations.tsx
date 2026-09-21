import { useEffect, useMemo, useState } from 'react'
import './historicalReplayOperations.css'

type Props={ sessionDate:string; onReplayComplete?:()=>void }
type Job={ job_id:string; action:string; session_date:string; status:string;
  queued_at?:string|null; started_at?:string|null; completed_at?:string|null;
  result?:any; error?:string|null; stale_recovered?:boolean }

async function requestJson(url:string,init?:RequestInit,timeoutMs=20000){
  const controller=new AbortController()
  const timeout=setTimeout(()=>controller.abort(),timeoutMs)
  try{
    const r=await fetch(url,{...init,signal:controller.signal})
    const value=await r.json().catch(()=>({}))
    if(!r.ok) throw new Error(typeof value?.detail==='string'?value.detail:JSON.stringify(value?.detail||value))
    return value
  }catch(e:any){
    if(e?.name==='AbortError') throw new Error(`Request timed out after ${Math.round(timeoutMs/1000)}s: ${url}`)
    throw e
  }finally{
    clearTimeout(timeout)
  }
}
function statusOf(value:any){
  if(!value) return 'UNKNOWN'
  return String(value.operation_status??value.status??value.state??value.availability??'UNKNOWN')
}
function datasetRows(readiness:any, semanticRows:any[]){
  if(Array.isArray(semanticRows) && semanticRows.length) return semanticRows
  const r=readiness||{}
  if(Array.isArray(r.datasets)) return r.datasets
  const keys=['snapshots','futures','exact_option','option_minutes','catalog']
  return keys.filter(k=>r[k]!=null).map(k=>({name:k,...(typeof r[k]==='object'?r[k]:{status:r[k]})}))
}
function localTime(value?:string|null){
  if(!value) return null
  const d=new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString()
}

export default function HistoricalReplayOperations({sessionDate,onReplayComplete}:Props){
  const [readiness,setReadiness]=useState<any>(null)
  const [semanticRows,setSemanticRows]=useState<any[]>([])
  const [strictReplayReady,setStrictReplayReady]=useState<boolean|null>(null)
  const [job,setJob]=useState<Job|null>(null)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [lastCheckedAt,setLastCheckedAt]=useState<string|null>(null)
  const [pendingAction,setPendingAction]=useState<'readiness'|'download'|'run'|null>(null)

  const refreshReadiness=async()=>{
    if(!sessionDate){setReadiness(null);setSemanticRows([]);setStrictReplayReady(null);return}
    setError('')
    setPendingAction('readiness')
    try{
      const value=await requestJson(
      `/api/live-shadow/replay-ops/readiness?session_date=${encodeURIComponent(sessionDate)}`,
      undefined,
      60000,
    )
      setReadiness(value.readiness)
      setSemanticRows(value.datasets||[])
      setLastCheckedAt(new Date().toLocaleTimeString())
      setStrictReplayReady(
        typeof value.strict_replay_ready==='boolean' ? value.strict_replay_ready : null
      )
      if(value.active_job){
        setJob(value.active_job)
        setBusy(['QUEUED','RUNNING'].includes(value.active_job.status))
      }
    }finally{
      setPendingAction(current=>current==='readiness'?null:current)
    }
  }

  useEffect(()=>{
    if(!sessionDate){setJob(null);setBusy(false);setReadiness(null);setSemanticRows([]);return}
    let active=true
    const recover=async()=>{
      try{
        const value=await requestJson(`/api/live-shadow/replay-ops/jobs?limit=20&session_date=${encodeURIComponent(sessionDate)}`)
        if(!active)return
        const rows:Job[]=value.rows||[]
        const current=rows.find(row=>['QUEUED','RUNNING'].includes(row.status)) || rows[0] || null
        setJob(current)
        setBusy(Boolean(current&&['QUEUED','RUNNING'].includes(current.status)))
        await refreshReadiness()
      }catch(e){ if(active)setError(String(e)) }
    }
    void recover()
    return()=>{active=false}
  },[sessionDate])

  useEffect(()=>{
    if(!job || !['QUEUED','RUNNING'].includes(job.status)) return
    let active=true
    const poll=async()=>{
      try{
        const next=await requestJson(`/api/live-shadow/replay-ops/job/${job.job_id}`)
        if(!active)return
        setJob(next)
        if(next.status==='COMPLETE'){
          setBusy(false); await refreshReadiness()
          if(next.action==='RUN_REPLAY') onReplayComplete?.()
        }else if(next.status==='FAILED'){
          setBusy(false); await refreshReadiness()
        }
      }catch(e){ if(active){setBusy(false);setError(String(e))} }
    }
    const id=setInterval(()=>void poll(),1500)
    void poll()
    return()=>{active=false;clearInterval(id)}
  },[job?.job_id,job?.status])

  const rows=useMemo(()=>datasetRows(readiness,semanticRows),[readiness,semanticRows])
  const checkpointReady = strictReplayReady!==null
    ? strictReplayReady
    : Boolean(
        readiness?.checkpoint_replay_ready ??
        readiness?.checkpoint_ready ??
        readiness?.full_replay_prerequisites_ready ??
        readiness?.full_trade_replay_prerequisites_ready
      )
  const canDownload=rows.some((row:any)=>statusOf(row)==='DOWNLOADABLE')

  const start=async(action:'download'|'run')=>{
    if(!sessionDate)return
    setBusy(true);setError('')
    setPendingAction(action)
    setJob(null)
    try{
      const url=action==='download'?'/api/live-shadow/replay-ops/download-missing':'/api/live-shadow/replay-ops/run'
      const body=action==='download'?{session_date:sessionDate}:{session_date:sessionDate,overwrite:true}
      // Replay/download launch performs a synchronous readiness check before the
      // background worker is queued. Real readiness scans can take ~14s and
      // occasionally exceed the generic 20s UI timeout. Give launch requests
      // a wider client timeout while keeping ordinary readiness/job polling at
      // the existing 20s default.
      const next=await requestJson(
        url,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},
        60000,
      )
      setJob(next)
      setPendingAction(null)
    }catch(e){
      setBusy(false)
      setPendingAction(null)
      setError(String(e))
    }
  }

  return <section className="hr-ops">
    <div className="hr-ops-head">
      <div><h3>Replay operations</h3><p>Readiness → download supported missing data → causal replay. Observation only.</p></div>
      <button disabled={busy||!sessionDate||pendingAction==='readiness'} onClick={()=>void refreshReadiness().catch(e=>setError(String(e)))}>
        {pendingAction==='readiness'?'Checking readiness…':'Check readiness'}
      </button>
    </div>
    {error&&<div className="hr-ops-error">{error}</div>}
    {!error&&pendingAction==='readiness'&&
      <div className="hr-ops-info">Checking readiness for {sessionDate}…</div>}
    {!error&&pendingAction!=='readiness'&&lastCheckedAt&&
      <div className="hr-ops-info">
        Readiness checked for {sessionDate} at {lastCheckedAt}.
        {checkpointReady?' Replay prerequisites are ready.':' Replay prerequisites are not ready.'}
      </div>}
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
        {row.operation_detail&&<small>{String(row.operation_detail)}</small>}
      </div>)}
    </div>}
    <div className="hr-ops-actions">
      <button disabled={busy||!sessionDate||!canDownload} onClick={()=>void start('download')}>Download supported missing</button>
      <button disabled={busy||!sessionDate||!checkpointReady} onClick={()=>void start('run')}>Run / replace replay</button>
    </div>
    {!checkpointReady&&rows.some((row:any)=>statusOf(row)==='NOT_DOWNLOADABLE')&&
      <div className="hr-ops-error">This date cannot be made replay-ready by the current downloader because required historical option-chain OI snapshots are not stored locally.</div>}
    {pendingAction&&pendingAction!=='readiness'&&!job&&<div className="hr-ops-job hr-job-running">
      <div>
        <b>{pendingAction==='run'?'RUN_REPLAY':'DOWNLOAD_MISSING'}</b>
        <span>STARTING</span>
      </div>
      <small>
        {pendingAction==='run'
          ? 'Validating strict readiness and starting replay worker…'
          : 'Starting historical data download worker…'}
      </small>
      <div className="hr-ops-progress"><span/></div>
    </div>}

    {job&&<div className={`hr-ops-job hr-job-${job.status.toLowerCase()}`}>
      <div><b>{job.action}</b><span>{job.status}</span></div>
      <small>Job {job.job_id}</small>
      {job.queued_at&&<small>Queued {localTime(job.queued_at)}</small>}
      {job.started_at&&<small>Started {localTime(job.started_at)}</small>}
      {job.completed_at&&<small>Completed {localTime(job.completed_at)}</small>}
      {job.stale_recovered&&<small>Recovered stale job state</small>}
      {job.error&&<div className="hr-ops-error">{job.error}</div>}
      {['QUEUED','RUNNING'].includes(job.status)&&<div className="hr-ops-progress"><span/></div>}
    </div>}
  </section>
}
