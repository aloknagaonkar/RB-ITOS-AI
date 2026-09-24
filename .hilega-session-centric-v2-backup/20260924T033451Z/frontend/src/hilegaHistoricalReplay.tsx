import {useEffect,useMemo,useState} from 'react'
import HilegaDecisionTable,{type HilegaAudit} from './hilegaDecisionTable'
import './hilegaHistoricalReplay.css'

type Capture={session_date:string;capture_id:string;expiry:string|null;has_manifest:boolean;has_report?:boolean}
type Response={session_date:string;capture_id:string;reports:HilegaAudit[];report_count:number;
  audit_chain_ok:boolean;audit_chain_issue:string|null;manifest:Record<string,any>;warning:string}
const shortTime=(v:string)=>{
  const d=new Date(v)
  return Number.isNaN(d.getTime())?v:d.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Kolkata'})
}
// Deliberately independent of the existing ALL3 date and readiness checks.
// The Hilega API reads completed, immutable captures; this component never
// acquires broker data or calls the running live worker.
export default function HilegaHistoricalReplay(){
  const [captures,setCaptures]=useState<Capture[]>([])
  const [selectedDate,setSelectedDate]=useState('')
  const [captureId,setCaptureId]=useState('')
  const [data,setData]=useState<Response|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [step,setStep]=useState(false)
  const [cursor,setCursor]=useState(0)
  const [playing,setPlaying]=useState(false)
  const [reviewCheckpoint,setReviewCheckpoint]=useState('')
  const [notes,setNotes]=useState<Record<string,{label:string;note:string}>>({})
  const [note,setNote]=useState('')
  const [label,setLabel]=useState('Unreviewed')
  const dates=useMemo(()=>[...new Set(captures.map(x=>x.session_date))].sort().reverse(),[captures])
  const available=useMemo(()=>captures.filter(c=>c.session_date===selectedDate),[captures,selectedDate])
  const reports=useMemo(()=>[...(data?.reports??[])].sort((a,b)=>a.checkpoint.localeCompare(b.checkpoint)),[data])
  useEffect(()=>{
    let active=true
    fetch('/api/live-shadow/hilega-historical/sessions')
      .then(async r=>{if(!r.ok)throw new Error(`Sessions HTTP ${r.status}`);return r.json()})
      .then(body=>{if(active){const rows:Capture[]=body.sessions??[];setCaptures(rows)
        const sorted=[...new Set(rows.map(r=>r.session_date))].sort().reverse()
        setSelectedDate(prev=>sorted.includes(prev)?prev:(sorted[0]??''))}})
      .catch(e=>{if(active)setError(String(e))})
    return()=>{active=false}
  },[])
  useEffect(()=>{
    const best=available.find(x=>x.has_report&&x.has_manifest)??available.find(x=>x.has_manifest)??available[0]
    setCaptureId(best?.capture_id??'');setData(null);setPlaying(false);setCursor(0)
  },[available])
  useEffect(()=>{setData(null);setCursor(0);setPlaying(false)},[captureId])
  async function load(){
    if(!captureId)return
    setBusy(true);setError('');setPlaying(false);setData(null);setCursor(0)
    try{
      const r=await fetch(`/api/live-shadow/hilega-historical/capture?capture_id=${encodeURIComponent(captureId)}`)
      if(!r.ok)throw new Error(`Capture HTTP ${r.status}: ${await r.text()}`)
      const value=await r.json() as Response
      // Checkpoint count is shown without claiming verification of provider parity.
      setData(value)
    }catch(e){setError(String(e))}finally{setBusy(false)}
  }
  useEffect(()=>{
    if(!playing||!step||!reports.length)return
    const handle=window.setInterval(()=>setCursor(i=>Math.min(i+1,reports.length-1)),1200)
    return()=>clearInterval(handle)
  },[playing,step,reports.length])
  useEffect(()=>{if(cursor>=reports.length-1)setPlaying(false)},[cursor,reports.length])
  const until=step ? reports[cursor]?.checkpoint??'' : undefined
  const key=`hime-review:${captureId}`
  useEffect(()=>{
    try{setNotes(JSON.parse(localStorage.getItem(key)??'{}'))}catch{setNotes({})}
    setReviewCheckpoint('')
  },[key])
  useEffect(()=>{
    const saved=notes[reviewCheckpoint]
    setNote(saved?.note??'');setLabel(saved?.label??'Unreviewed')
  },[reviewCheckpoint,notes])
  function save(){
    if(!reviewCheckpoint)return
    const next={...notes,[reviewCheckpoint]:{label,note}}
    localStorage.setItem(key,JSON.stringify(next));setNotes(next)
  }
  function download(){
    const blob=new Blob([JSON.stringify({session_date:selectedDate,capture_id:captureId,reviews:notes},null,2)],{type:'application/json'})
    const href=URL.createObjectURL(blob)
    const a=document.createElement('a');a.href=href;a.download=`${captureId}-manual-review.json`;a.click();URL.revokeObjectURL(href)
  }
  return <section className="hime-replay" aria-label="Hilega historical replay">
    <h3>Hilega-Milega · Historical Replay</h3>
    <p>Read-only Hilega capture review. Existing ALL3 replay remains separate; no broker requests or live-worker changes.</p>
    <div className="hime-controls">
      <label>Hilega session <select aria-label="Hilega historical session" value={selectedDate} onChange={e=>setSelectedDate(e.target.value)}>
        {!dates.length&&<option value="">No Hilega historical sessions available</option>}
        {dates.map(d=><option value={d} key={d}>{d}</option>)}
      </select></label>
      <label>Capture <select aria-label="Hilega historical capture" value={captureId} onChange={e=>setCaptureId(e.target.value)}>
        {!available.length&&<option value="">No capture available</option>}
        {available.map(c=><option key={c.capture_id} value={c.capture_id}>{c.capture_id} · Expiry {c.expiry??'—'}</option>)}
      </select></label>
      <button onClick={()=>void load()} disabled={!captureId||busy}>{busy?'Loading…':'Load existing replay'}</button>
    </div>
    {error&&<p role="alert" className="hime-error">{error}</p>}
    {data&&<>
      <div className="hime-meta"><span>Session: {data.session_date}</span><span>Capture: {data.capture_id}</span>
        <span>Checkpoints: {reports.length}</span><span>Audit chain: {data.audit_chain_ok?'PASS':'FAIL'}</span></div>
      <p className="hime-warning">{data.warning} {data.audit_chain_issue??''}</p>
      <div className="hime-controls">
        <button onClick={()=>{setStep(false);setPlaying(false)}} aria-pressed={!step}>Full-session table</button>
        <button onClick={()=>{setStep(true);setCursor(0);setPlaying(false)}} aria-pressed={step}>Candle-by-candle mode</button>
        {step&&reports.length>0&&<>
          <button onClick={()=>{setCursor(0);setPlaying(false)}}>Reset</button>
          <button disabled={cursor===0} onClick={()=>{setCursor(i=>i-1);setPlaying(false)}}>◀ Previous</button>
          <button disabled={cursor>=reports.length-1} onClick={()=>setPlaying(p=>!p)}>{playing?'Pause':'Play'}</button>
          <button disabled={cursor>=reports.length-1} onClick={()=>{setCursor(i=>i+1);setPlaying(false)}}>Next ▶</button>
          <label>Checkpoint <input aria-label="Replay checkpoint" type="range" min={0} max={Math.max(0,reports.length-1)} value={cursor} onChange={e=>{setCursor(Number(e.target.value));setPlaying(false)}} /></label>
          <strong>{cursor+1}/{reports.length} · {shortTime(reports[cursor].checkpoint)} IST</strong>
        </>}
      </div>
      <HilegaDecisionTable key={captureId+(step?'-step':'-full')} reports={reports} mode="HISTORICAL" visibleUntil={until}
        emptyMessage="No Hilega checkpoints recorded in this historical capture." onSelected={setReviewCheckpoint}/>
      <div className="hime-review"><h4>Manual review (separate from immutable audit)</h4>
        <p>Selected checkpoint: {reviewCheckpoint?shortTime(reviewCheckpoint):'Select View audit on a row'}</p>
        <label>Classification <select value={label} disabled={!reviewCheckpoint} onChange={e=>setLabel(e.target.value)}>
          {['Unreviewed','Correct','Needs investigation','Possible missed opportunity','Possible incorrect entry or exit','Data discrepancy'].map(v=><option key={v}>{v}</option>)}
        </select></label>
        <textarea value={note} disabled={!reviewCheckpoint} onChange={e=>setNote(e.target.value)} placeholder="Compare the selected checkpoint with your external chart"/>
        <button disabled={!reviewCheckpoint} onClick={save}>Save observation</button><button onClick={download}>Export reviews JSON</button>
      </div>
    </>}
  </section>
}
