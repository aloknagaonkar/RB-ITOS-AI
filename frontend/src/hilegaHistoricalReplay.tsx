import {useEffect,useMemo,useState} from 'react'
import HilegaDecisionTable,{type HilegaAudit} from './hilegaDecisionTable'
import {overlayDirectionalAuditReports} from './hilegaDirectionalAuditOverlay'
import HilegaDirectionalReplayTrades from './hilegaDirectionalReplayTrades'
import './hilegaHistoricalReplay.css'

type Session={
  session_date:string
  source:'PHASE7D'|'LIVE_SHADOW'|'SESSION_REPLAY'|'RESEARCH_120'|string
  source_id:string
  status:string
  evidence_level:'FULL'|'STRATEGY'|'SUMMARY'|'PARTIAL'|string
  ce_available:boolean
  expiry:string|null
  available_sources:string[]
}
type Response={
  session_date:string;source:string;source_id:string;evidence_level:string;ce_available:boolean
  reports:HilegaAudit[];report_count:number;audit_chain_ok:boolean|null;audit_chain_issue:string|null
  manifest:Record<string,any>;warning:string;available_sources:string[]
}
const shortTime=(v:string)=>{
  const d=new Date(v)
  return Number.isNaN(d.getTime())?v:d.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Kolkata'})
}

export default function HilegaHistoricalReplay(){
  const [sessions,setSessions]=useState<Session[]>([])
  const [selectedDate,setSelectedDate]=useState('')
  const [data,setData]=useState<Response|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [refreshing,setRefreshing]=useState(false)
  const [step,setStep]=useState(false)
  const [cursor,setCursor]=useState(0)
  const [playing,setPlaying]=useState(false)
  const [reviewCheckpoint,setReviewCheckpoint]=useState('')
  const [notes,setNotes]=useState<Record<string,{label:string;note:string}>>({})
  const [note,setNote]=useState('')
  const [label,setLabel]=useState('Unreviewed')

  const reports=useMemo(()=>[...(data?.reports??[])].sort((a,b)=>a.checkpoint.localeCompare(b.checkpoint)),[data])
  const selected=useMemo(()=>sessions.find(x=>x.session_date===selectedDate)??null,[sessions,selectedDate])

  async function refreshSessions(silent=false){
    if(!silent)setRefreshing(true)
    try{
      const r=await fetch('/api/live-shadow/hilega-historical/sessions')
      if(!r.ok)throw new Error(`Sessions HTTP ${r.status}`)
      const body=await r.json()
      const rows:Session[]=body.sessions??[]
      setSessions(rows)
      setSelectedDate(prev=>rows.some(x=>x.session_date===prev)?prev:(rows[0]?.session_date??''))
    }catch(e){if(!silent)setError(String(e))}
    finally{if(!silent)setRefreshing(false)}
  }

  useEffect(()=>{
    let active=true
    const run=async()=>{
      try{
        const r=await fetch('/api/live-shadow/hilega-historical/sessions')
        if(!r.ok)throw new Error(`Sessions HTTP ${r.status}`)
        const body=await r.json()
        if(!active)return
        const rows:Session[]=body.sessions??[]
        setSessions(rows)
        setSelectedDate(prev=>rows.some(x=>x.session_date===prev)?prev:(rows[0]?.session_date??''))
      }catch(e){if(active)setError(String(e))}
    }
    void run()
    const id=window.setInterval(()=>void refreshSessions(true),60000)
    return()=>{active=false;window.clearInterval(id)}
  },[])

  useEffect(()=>{setData(null);setPlaying(false);setCursor(0);setError('')},[selectedDate])

  async function load(){
    if(!selectedDate)return
    setBusy(true);setError('');setPlaying(false);setData(null);setCursor(0)
    try{
      const [r,dr]=await Promise.all([
        fetch(`/api/live-shadow/hilega-historical/session?session_date=${encodeURIComponent(selectedDate)}`),
        fetch(`/api/live-shadow/hilega-directional-candles/historical?session_date=${encodeURIComponent(selectedDate)}`),
      ])
      if(!r.ok)throw new Error(`Session HTTP ${r.status}: ${await r.text()}`)
      const body=await r.json() as Response
      if(dr.ok){
        const directional=await dr.json()
        body.reports=overlayDirectionalAuditReports(body.reports??[],directional.rows??[])
        body.report_count=body.reports.length
      }
      setData(body)
    }catch(e){setError(String(e))}finally{setBusy(false)}
  }

  useEffect(()=>{
    if(!playing||!step||!reports.length)return
    const handle=window.setInterval(()=>setCursor(i=>Math.min(i+1,reports.length-1)),1200)
    return()=>clearInterval(handle)
  },[playing,step,reports.length])
  useEffect(()=>{if(cursor>=reports.length-1)setPlaying(false)},[cursor,reports.length])

  const until=step ? reports[cursor]?.checkpoint??'' : undefined
  const reviewKey=`hime-review:${selectedDate}`
  useEffect(()=>{
    try{setNotes(JSON.parse(localStorage.getItem(reviewKey)??'{}'))}catch{setNotes({})}
    setReviewCheckpoint('')
  },[reviewKey])
  useEffect(()=>{
    const saved=notes[reviewCheckpoint]
    setNote(saved?.note??'');setLabel(saved?.label??'Unreviewed')
  },[reviewCheckpoint,notes])
  function save(){
    if(!reviewCheckpoint)return
    const next={...notes,[reviewCheckpoint]:{label,note}}
    localStorage.setItem(reviewKey,JSON.stringify(next));setNotes(next)
  }
  function download(){
    const blob=new Blob([JSON.stringify({session_date:selectedDate,source:data?.source,reviews:notes},null,2)],{type:'application/json'})
    const href=URL.createObjectURL(blob)
    const a=document.createElement('a');a.href=href;a.download=`hilega-${selectedDate}-manual-review.json`;a.click();URL.revokeObjectURL(href)
  }

  return <section className="hime-replay" aria-label="Hilega historical replay">
    <h3>Hilega-Milega · Session Replay</h3>
    <p>Choose one trading day. The registry uses the richest evidence already available and never starts a broker/replay worker.</p>

    <div className="hime-controls">
      <label>Session date <select aria-label="Hilega historical session" value={selectedDate} onChange={e=>setSelectedDate(e.target.value)}>
        {!sessions.length&&<option value="">No Hilega sessions available</option>}
        {sessions.map(s=><option value={s.session_date} key={s.session_date}>
          {s.session_date} · {s.evidence_level} · {s.source}{s.ce_available?' · CE':''}
        </option>)}
      </select></label>
      <button onClick={()=>void load()} disabled={!selectedDate||busy}>{busy?'Loading…':'Load session'}</button>
      <button onClick={()=>void refreshSessions()} disabled={refreshing}>{refreshing?'Refreshing…':'Refresh sessions'}</button>
    </div>

    {selected&&<div className="hime-meta">
      <span>Available source: {selected.source}</span>
      <span>Evidence: {selected.evidence_level}</span>
      <span>CE: {selected.ce_available?'AVAILABLE':'NOT RECORDED'}</span>
      <span>Status: {selected.status}</span>
    </div>}

    {error&&<p role="alert" className="hime-error">{error}</p>}

    {data&&<>
      <div className="hime-meta">
        <span>Session: {data.session_date}</span>
        <span>Loaded from: {data.source}</span>
        <span>Evidence: {data.evidence_level}</span>
        <span>CE: {data.ce_available?'AVAILABLE':'NOT RECORDED'}</span>
        <span>Checkpoints: {reports.length}</span>
        <span>Audit chain: {data.audit_chain_ok===null?'N/A':data.audit_chain_ok?'PASS':'FAIL'}</span>
      </div>
      <p className="hime-warning">{data.warning} {data.audit_chain_issue??''}</p>

      {data.evidence_level==='SUMMARY'&&<p className="hime-warning">
        This 120-session research day contains entry/exit summary evidence only. It is selectable now, but full five-minute conditions and exact CE lifecycle require a richer recorded replay for that date.
      </p>}

      <div className="hime-controls">
        <button onClick={()=>{setStep(false);setPlaying(false)}} aria-pressed={!step}>Full-session table</button>
        <button onClick={()=>{setStep(true);setCursor(0);setPlaying(false)}} aria-pressed={step} disabled={!reports.length}>Candle-by-candle mode</button>
        {step&&reports.length>0&&<>
          <button onClick={()=>{setCursor(0);setPlaying(false)}}>Reset</button>
          <button disabled={cursor===0} onClick={()=>{setCursor(i=>i-1);setPlaying(false)}}>◀ Previous</button>
          <button disabled={cursor>=reports.length-1} onClick={()=>setPlaying(p=>!p)}>{playing?'Pause':'Play'}</button>
          <button disabled={cursor>=reports.length-1} onClick={()=>{setCursor(i=>i+1);setPlaying(false)}}>Next ▶</button>
          <label>Checkpoint <input aria-label="Replay checkpoint" type="range" min={0} max={Math.max(0,reports.length-1)} value={cursor} onChange={e=>{setCursor(Number(e.target.value));setPlaying(false)}} /></label>
          <strong>{cursor+1}/{reports.length} · {shortTime(reports[cursor].checkpoint)} IST</strong>
        </>}
      </div>

      <HilegaDirectionalReplayTrades sessionDate={selectedDate} />

      <HilegaDecisionTable key={`${selectedDate}-${data.source}-${step?'step':'full'}`} reports={reports}
        mode="HISTORICAL" visibleUntil={until}
        emptyMessage="No Hilega strategy rows were recorded for this session."
        onSelected={setReviewCheckpoint}/>

      <div className="hime-review"><h4>Manual review (separate from immutable audit)</h4>
        <p>Selected checkpoint: {reviewCheckpoint?shortTime(reviewCheckpoint):'Select View audit on a row'}</p>
        <label>Classification <select value={label} disabled={!reviewCheckpoint} onChange={e=>setLabel(e.target.value)}>
          {['Unreviewed','Correct','Needs investigation','Possible missed opportunity','Possible incorrect entry or exit','Data discrepancy'].map(v=><option key={v}>{v}</option>)}
        </select></label>
        <textarea value={note} disabled={!reviewCheckpoint} onChange={e=>setNote(e.target.value)} placeholder="Compare the selected checkpoint with your external chart"/>
        <button disabled={!reviewCheckpoint} onClick={save}>Save observation</button>
        <button onClick={download}>Export reviews JSON</button>
      </div>
    </>}
  </section>
}
