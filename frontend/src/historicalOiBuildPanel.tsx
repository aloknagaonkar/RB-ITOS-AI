import {useEffect,useState} from 'react'
import './historicalOiBuildPanel.css'

type Job={job_id?:string;session_date:string;expiry:string;status:string;started_at?:string|null;completed_at?:string|null;result?:any;error?:string|null}

export default function HistoricalOiBuildPanel({onComplete}:{onComplete?:()=>void}){
  const [sessionDate,setSessionDate]=useState('')
  const [expiry,setExpiry]=useState('')
  const [job,setJob]=useState<Job|null>(null)
  const [error,setError]=useState('')
  const busy=job?.status==='QUEUED'||job?.status==='RUNNING'

  const start=async()=>{
    if(!sessionDate||!expiry){setError('Select both session date and exact expiry.');return}
    setError('')
    const r=await fetch('/api/live-shadow/replay-ops/historical-oi/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_date:sessionDate,expiry})})
    const v=await r.json().catch(()=>({}))
    if(!r.ok){setError(typeof v?.detail==='string'?v.detail:JSON.stringify(v));return}
    setJob(v)
  }

  useEffect(()=>{
    if(!job||!['QUEUED','RUNNING'].includes(job.status))return
    let active=true
    const poll=async()=>{
      try{
        const r=await fetch(`/api/live-shadow/replay-ops/historical-oi/build-status?session_date=${encodeURIComponent(job.session_date)}`)
        const v=await r.json().catch(()=>({}))
        if(!r.ok)throw new Error(v?.detail||'Build status unavailable')
        if(!active)return
        setJob(v)
        if(v.status==='COMPLETE')onComplete?.()
      }catch(e){if(active)setError(String(e))}
    }
    const id=setInterval(()=>void poll(),1500);void poll()
    return()=>{active=false;clearInterval(id)}
  },[job?.job_id,job?.status])

  return <section className="hoi-build">
    <div className="hoi-build-head"><div><h4>Download / build new historical date</h4><p>Builds a new per-strike historical positioning dataset. Exact expiry is required and is never guessed.</p></div></div>
    <div className="hoi-build-form">
      <label>Session date<input type="date" value={sessionDate} onChange={e=>setSessionDate(e.target.value)}/></label>
      <label>Exact expiry<input type="date" value={expiry} onChange={e=>setExpiry(e.target.value)}/></label>
      <button disabled={busy||!sessionDate||!expiry} onClick={()=>void start()}>{busy?'Building…':'Download / Build'}</button>
    </div>
    {error&&<div className="hoi-build-error">{error}</div>}
    {job&&<div className="hoi-build-status">
      <span>Status</span><b>{job.status}</b><span>Date</span><b>{job.session_date}</b><span>Expiry</span><b>{job.expiry}</b>
      {job.result?.row_count!=null&&<><span>Positioning rows</span><b>{job.result.row_count}</b></>}
      {job.error&&<><span>Error</span><b>{job.error}</b></>}
    </div>}
    <p className="hoi-build-note">This creates historical research data, not production Observation snapshots, so strict Historical Replay readiness is unchanged.</p>
  </section>
}
