import {useEffect,useState} from 'react'
import './historicalOiBuildPanel.css'

type Attempt={
  attempt:number
  provider_status?:string|null
  returncode?:number
  available_session_count?:number|null
  unavailable_session_count?:number|null
  row_count?:number|null
  positioning_csv_exists?:boolean
}
type Job={
  job_id?:string;session_date:string;expiry:string;status:string;
  attempt?:number;max_attempts?:number;next_retry_seconds?:number|null;
  started_at?:string|null;completed_at?:string|null;
  result?:Attempt|null;attempt_history?:Attempt[];error?:string|null;
}

export default function HistoricalOiBuildPanel({onComplete}:{onComplete?:()=>void}){
  const [sessionDate,setSessionDate]=useState('')
  const [expiry,setExpiry]=useState('')
  const [job,setJob]=useState<Job|null>(null)
  const [error,setError]=useState('')
  const busy=!!job&&['QUEUED','RUNNING','RETRYING'].includes(job.status)

  const start=async()=>{
    if(!sessionDate||!expiry){setError('Select both session date and exact expiry.');return}
    setError('')
    const r=await fetch('/api/live-shadow/replay-ops/historical-oi/build',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({session_date:sessionDate,expiry})
    })
    const v=await r.json().catch(()=>({}))
    if(!r.ok){setError(typeof v?.detail==='string'?v.detail:JSON.stringify(v));return}
    setJob(v)
  }

  useEffect(()=>{
    if(!job||!['QUEUED','RUNNING','RETRYING'].includes(job.status))return
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
    const id=setInterval(()=>void poll(),1500)
    void poll()
    return()=>{active=false;clearInterval(id)}
  },[job?.job_id,job?.status])

  return <section className="hoi-build">
    <div className="hoi-build-head">
      <div>
        <h4>Download / build new historical date</h4>
        <p>Cache-aware automatic retry is enabled. Exact expiry is required and is never guessed.</p>
      </div>
    </div>

    <div className="hoi-build-form">
      <label>Session date<input type="date" value={sessionDate} onChange={e=>setSessionDate(e.target.value)}/></label>
      <label>Exact expiry<input type="date" value={expiry} onChange={e=>setExpiry(e.target.value)}/></label>
      <button disabled={busy||!sessionDate||!expiry} onClick={()=>void start()}>
        {busy?'Building…':'Download / Build'}
      </button>
    </div>

    {error&&<div className="hoi-build-error">{error}</div>}

    {job&&<div className="hoi-build-status">
      <span>Status</span><b>{job.status}</b>
      <span>Date</span><b>{job.session_date}</b>
      <span>Expiry</span><b>{job.expiry}</b>
      {job.max_attempts!=null&&<><span>Attempt</span><b>{job.attempt||0} / {job.max_attempts}</b></>}
      {job.result?.provider_status&&<><span>Provider result</span><b>{job.result.provider_status}</b></>}
      {job.result?.row_count!=null&&<><span>Positioning rows</span><b>{job.result.row_count}</b></>}
      {job.next_retry_seconds!=null&&<><span>Next retry</span><b>{job.next_retry_seconds}s</b></>}
      {job.error&&<><span>Error</span><b>{job.error}</b></>}
    </div>}

    {!!job?.attempt_history?.length&&<div className="hoi-attempts">
      <h5>Attempt history</h5>
      <table><thead><tr><th>Attempt</th><th>Status</th><th>Rows</th><th>Return code</th></tr></thead>
      <tbody>{job.attempt_history.map(a=><tr key={a.attempt}>
        <td>{a.attempt}</td><td>{a.provider_status||'—'}</td><td>{a.row_count??'—'}</td><td>{a.returncode??'—'}</td>
      </tr>)}</tbody></table>
    </div>}

    <p className="hoi-build-note">
      Retry delays: 15 seconds, then 60 seconds. Successful cached data is reused by the existing sidecar, so later attempts are intended to fill missing data rather than rebuild everything.
    </p>
  </section>
}
