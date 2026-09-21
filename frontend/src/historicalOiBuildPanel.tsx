import {useEffect,useState} from 'react'
import './historicalOiBuildPanel.css'

type Quality={
  total_rows?:number;instrument_pair_rows?:number;oi_pair_rows?:number;premium_pair_rows?:number;
  instrument_pair_pct?:number;oi_pair_pct?:number;premium_pair_pct?:number
}
type Attempt={attempt:number;provider_status?:string|null;returncode?:number;row_count?:number|null;quality?:Quality}
type Job={job_id?:string;session_date:string;expiry:string;status:string;attempt?:number;max_attempts?:number;next_retry_seconds?:number|null;result?:Attempt|null;attempt_history?:Attempt[];error?:string|null}

const p=(v:any)=>v==null?'—':`${Number(v).toFixed(1)}%`

export default function HistoricalOiBuildPanel(){
  const [sessionDate,setSessionDate]=useState('')
  const [expiry,setExpiry]=useState('')
  const [job,setJob]=useState<Job|null>(null)
  const [error,setError]=useState('')
  const busy=!!job&&['QUEUED','RUNNING','RETRYING'].includes(job.status)

  const start=async()=>{
    if(!sessionDate||!expiry){setError('Select both session date and exact expiry.');return}
    setError('')
    const r=await fetch('/api/live-shadow/replay-ops/historical-oi/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_date:sessionDate,expiry})})
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
        if(active)setJob(v)
      }catch(e){if(active)setError(String(e))}
    }
    const id=setInterval(()=>void poll(),1500);void poll()
    return()=>{active=false;clearInterval(id)}
  },[job?.job_id,job?.status])

  const q=job?.result?.quality

  return <section className="hoi-build">
    <div className="hoi-build-head"><div>
      <h4>Download / build new historical date</h4>
      <p>Completion requires actual CE/PE contracts, premiums and OI — not merely 4,125 generated rows.</p>
    </div></div>

    <div className="hoi-build-form">
      <label>Session date<input type="date" value={sessionDate} onChange={e=>setSessionDate(e.target.value)}/></label>
      <label>Exact expiry<input type="date" value={expiry} onChange={e=>setExpiry(e.target.value)}/></label>
      <button disabled={busy||!sessionDate||!expiry} onClick={()=>void start()}>{busy?'Building…':'Download / Build'}</button>
    </div>

    {error&&<div className="hoi-build-error">{error}</div>}
    {job&&<div className="hoi-build-status">
      <span>Status</span><b>{job.status}</b>
      <span>Date</span><b>{job.session_date}</b>
      <span>Expiry</span><b>{job.expiry}</b>
      {job.max_attempts!=null&&<><span>Attempt</span><b>{job.attempt||0} / {job.max_attempts}</b></>}
      {job.result?.row_count!=null&&<><span>Generated rows</span><b>{job.result.row_count}</b></>}
      {q&&<><span>CE/PE instruments</span><b>{q.instrument_pair_rows??0} / {q.total_rows??0} ({p(q.instrument_pair_pct)})</b></>}
      {q&&<><span>CE/PE OI</span><b>{q.oi_pair_rows??0} / {q.total_rows??0} ({p(q.oi_pair_pct)})</b></>}
      {q&&<><span>CE/PE premiums</span><b>{q.premium_pair_rows??0} / {q.total_rows??0} ({p(q.premium_pair_pct)})</b></>}
      {job.next_retry_seconds!=null&&<><span>Next retry</span><b>{job.next_retry_seconds}s</b></>}
      {job.error&&<><span>Reason</span><b>{job.error}</b></>}
    </div>}

    {job?.status==='INVALID_CONTRACT_DATA'&&
      <div className="hoi-contract-warning">
        The selected expiry produced no usable option contracts. Correct the expiry and run again. Automatic retry is intentionally stopped because repeating the same contract selection cannot repair this condition.
      </div>}

    <p className="hoi-build-note">Transient partial provider downloads still retry automatically (15s, then 60s). Invalid contract/expiry data fails immediately instead of wasting retries.</p>
  </section>
}
