from pathlib import Path

PATH = Path("frontend/src/historicalReplayOperations.tsx")
text = PATH.read_text(encoding="utf-8")

anchor = "  const [error,setError]=useState('')\n"
insert = """  const [pendingAction,setPendingAction]=useState<'readiness'|'download'|'run'|null>(null)
"""
if "const [pendingAction,setPendingAction]" not in text:
    if anchor not in text:
        raise SystemExit("Safe-stop: component state anchor not found.")
    text = text.replace(anchor, anchor + insert, 1)

old_readiness = """  const refreshReadiness=async()=>{
    if(!sessionDate){setReadiness(null);setSemanticRows([]);return}
    setError('')
    const value=await requestJson(`/api/live-shadow/replay-ops/readiness?session_date=${encodeURIComponent(sessionDate)}`)
    setReadiness(value.readiness)
    setSemanticRows(value.datasets||[])
    if(value.active_job){
      setJob(value.active_job)
      setBusy(['QUEUED','RUNNING'].includes(value.active_job.status))
    }
  }
"""
new_readiness = """  const refreshReadiness=async()=>{
    if(!sessionDate){setReadiness(null);setSemanticRows([]);return}
    setError('')
    setPendingAction('readiness')
    try{
      const value=await requestJson(`/api/live-shadow/replay-ops/readiness?session_date=${encodeURIComponent(sessionDate)}`)
      setReadiness(value.readiness)
      setSemanticRows(value.datasets||[])
      if(value.active_job){
        setJob(value.active_job)
        setBusy(['QUEUED','RUNNING'].includes(value.active_job.status))
      }
    }finally{
      setPendingAction(current=>current==='readiness'?null:current)
    }
  }
"""
if old_readiness in text:
    text = text.replace(old_readiness, new_readiness, 1)
elif new_readiness not in text:
    raise SystemExit("Safe-stop: refreshReadiness block not found.")

old_start = """  const start=async(action:'download'|'run')=>{
    if(!sessionDate)return
    setBusy(true);setError('')
    try{
      const url=action==='download'?'/api/live-shadow/replay-ops/download-missing':'/api/live-shadow/replay-ops/run'
      const body=action==='download'?{session_date:sessionDate}:{session_date:sessionDate,overwrite:true}
      const next=await requestJson(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
      setJob(next)
    }catch(e){setBusy(false);setError(String(e))}
  }
"""
new_start = """  const start=async(action:'download'|'run')=>{
    if(!sessionDate)return
    setBusy(true);setError('')
    setPendingAction(action)
    setJob(null)
    try{
      const url=action==='download'?'/api/live-shadow/replay-ops/download-missing':'/api/live-shadow/replay-ops/run'
      const body=action==='download'?{session_date:sessionDate}:{session_date:sessionDate,overwrite:true}
      const next=await requestJson(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
      setJob(next)
      setPendingAction(null)
    }catch(e){
      setBusy(false)
      setPendingAction(null)
      setError(String(e))
    }
  }
"""
if old_start in text:
    text = text.replace(old_start, new_start, 1)
elif new_start not in text:
    raise SystemExit("Safe-stop: start action block not found.")

old_button = """      <button disabled={busy||!sessionDate} onClick={()=>void refreshReadiness().catch(e=>setError(String(e)))}>Check readiness</button>"""
new_button = """      <button disabled={busy||!sessionDate||pendingAction==='readiness'} onClick={()=>void refreshReadiness().catch(e=>setError(String(e)))}>
        {pendingAction==='readiness'?'Checking readiness…':'Check readiness'}
      </button>"""
if old_button in text:
    text = text.replace(old_button, new_button, 1)
elif new_button not in text:
    raise SystemExit("Safe-stop: readiness button not found.")

job_anchor = """    {job&&<div className={`hr-ops-job hr-job-${job.status.toLowerCase()}`}>"""
transient = """    {pendingAction&&pendingAction!=='readiness'&&!job&&<div className="hr-ops-job hr-job-running">
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

"""
if "Validating strict readiness and starting replay worker" not in text:
    if job_anchor not in text:
        raise SystemExit("Safe-stop: job display anchor not found.")
    text = text.replace(job_anchor, transient + job_anchor, 1)

PATH.write_text(text, encoding="utf-8")
print("Applied Historical Replay immediate progress feedback V1.")
