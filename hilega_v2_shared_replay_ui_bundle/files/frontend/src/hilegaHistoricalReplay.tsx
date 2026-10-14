import {useEffect,useMemo,useState} from 'react'
import HilegaDecisionTable,{type HilegaAudit} from './hilegaDecisionTable'
import {overlayDirectionalAuditReports} from './hilegaDirectionalAuditOverlay'
import HilegaDirectionalReplayTrades from './hilegaDirectionalReplayTrades'
import HilegaReplayTradeLedger from './hilegaReplayTradeLedger'
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
  strategy_version?:string
  reports:HilegaAudit[];report_count:number;audit_chain_ok:boolean|null;audit_chain_issue:string|null
  manifest:Record<string,any>;warning:string;available_sources:string[]
  performance_summary?:Array<Record<string,any>>
  comparison?:Record<string,any>
  parity?:Record<string,any>
  forward_confirmation_eligible?:boolean
  zero_trade_session?:boolean
}
const shortTime=(v:string)=>{
  const d=new Date(v)
  return Number.isNaN(d.getTime())?v:d.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Kolkata'})
}

export default function HilegaHistoricalReplay(){
  const [sessions,setSessions]=useState<Session[]>([])
  const [selectedDate,setSelectedDate]=useState('')
  const [strategyVersion,setStrategyVersion]=useState<'LIVE'|'V1'|'V2'|'V2_ALIGN'>('LIVE')
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
      const strategyTestUrl=`/api/live-shadow/hilega-historical/strategy-test?session_date=${encodeURIComponent(selectedDate)}`
      const sessionUrl=`/api/live-shadow/hilega-historical/session?session_date=${encodeURIComponent(selectedDate)}`
      const v1Url=`${strategyTestUrl}&strategy=V1`
      const [r,dr,mr]=await Promise.all([
        fetch(strategyVersion==='V2_ALIGN' ? `${strategyTestUrl}&strategy=V2_ALIGN` : strategyVersion==='V2' ? strategyTestUrl : strategyVersion==='V1' ? v1Url : sessionUrl),
        (strategyVersion==='V2'||strategyVersion==='V2_ALIGN')
          ? Promise.resolve({ok:false} as globalThis.Response)
          : fetch(`/api/live-shadow/hilega-directional-candles/historical?session_date=${encodeURIComponent(selectedDate)}`),
        (strategyVersion==='V2'||strategyVersion==='V2_ALIGN') ? Promise.resolve({ok:false} as globalThis.Response) : fetch(strategyTestUrl),
      ])
      if(!r.ok)throw new Error(`Session HTTP ${r.status}: ${await r.text()}`)
      const body=await r.json() as Response
      if(dr.ok && body.source!=='RECOVERED_HISTORICAL_REPLAY'){
        const directional=await dr.json()
        body.reports=overlayDirectionalAuditReports(body.reports??[],directional.rows??[])
        body.report_count=body.reports.length
      }
      if(mr.ok){
        const metrics=await mr.json() as Response
        body.performance_summary=metrics.performance_summary
        body.comparison=metrics.comparison
      }
      body.strategy_version=strategyVersion==='V2_ALIGN' ? body.strategy_version : strategyVersion==='LIVE'
        ? 'LIVE_RECORDED_V1'
        : strategyVersion==='V1' ? 'HILEGA_V1_REPLAY' : 'HILEGA_WMA_GAP_V2_REPLAY'
      setData(body)
    }catch(e){setError(String(e))}finally{setBusy(false)}
  }

  useEffect(()=>{
    if(selectedDate)void load()
  // A selected date is a complete replay request; no separate Load click is required.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[selectedDate,strategyVersion])

  useEffect(()=>{
    if(!selectedDate||strategyVersion!=='LIVE'||selected?.status==='COMPLETE')return
    const id=window.setInterval(()=>void load(),60000)
    return()=>window.clearInterval(id)
  // Active/partial recorded evidence refreshes automatically; completed days are immutable.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[selectedDate,selected?.status,strategyVersion])

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
    <p>Review recorded live decisions, canonical Hilega v1, WMA-gap v2 and the tested V2 alignment/dual-exit replay using the shared audit flow. Replay views never change live behavior or submit orders.</p>

    <div className="hime-controls">
      <label>Session date <select aria-label="Hilega historical session" value={selectedDate} onChange={e=>setSelectedDate(e.target.value)}>
        {!sessions.length&&<option value="">No Hilega sessions available</option>}
        {sessions.map(s=><option value={s.session_date} key={s.session_date}>
          {s.session_date} · {s.evidence_level} · {s.source}{s.ce_available?' · CE':''}
        </option>)}
      </select></label>
      <label>Strategy <select aria-label="Hilega historical strategy" value={strategyVersion} onChange={e=>setStrategyVersion(e.target.value as 'LIVE'|'V1'|'V2'|'V2_ALIGN')}>
        <option value="LIVE">Existing live strategy (recorded)</option>
        <option value="V1">Hilega v1 (canonical historical replay)</option>
        <option value="V2">WMA-gap V2 (historical observation)</option>
        <option value="V2_ALIGN">V2 — alignment setup + dual exit (research)</option>
      </select></label>
      <button onClick={()=>void load()} disabled={!selectedDate||busy}>{busy?'Loading…':'Reload session'}</button>
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
        <span>Strategy: {data.strategy_version??strategyVersion}</span>
        <span>Evidence: {data.evidence_level}</span>
        <span>CE: {data.ce_available?'AVAILABLE':'NOT RECORDED'}</span>
        <span>Checkpoints: {reports.length}</span>
        <span>Audit chain: {data.audit_chain_ok===null?'N/A':data.audit_chain_ok?'PASS':'FAIL'}</span>
      </div>
      <p className="hime-warning">{data.warning} {data.audit_chain_issue??''}</p>

      {data.parity?.status==='PARITY_MISMATCH'&&<section className="hime-performance" aria-label="Forward replay parity diagnostic">
        <h4>Forward replay parity · ACTION REQUIRED</h4>
        <p>Recorded live evidence contains {data.parity.recorded_live_signals} signals / {data.parity.recorded_live_completed} completed trades, while final-candle replay contains {data.parity.canonical_replay_signals} signals / {data.parity.canonical_replay_completed} completed trades. This session is diagnostic and is not counted as a valid zero-trade V1/V2 result.</p>
        <div className="hime-performance-scroll"><table><thead><tr><th>Recorded time</th><th>Direction</th><th>Recorded live event</th><th>Replay match</th></tr></thead><tbody>
          {(data.parity.recorded_live_entries??[]).map((row:any,index:number)=><tr key={`${row.timestamp}-${row.event_type}-${index}`}><td>{shortTime(row.timestamp)}</td><td>{row.direction}</td><td>{row.event_type}</td><td className="hime-loss">MISSING FROM FINAL-CANDLE REPLAY</td></tr>)}
        </tbody></table></div>
      </section>}

      {data.performance_summary&&<section className="hime-performance" aria-label="Daily Nifty points performance">
        <h4>Daily strategy performance · Nifty points (full session)</h4>
        <div className="hime-performance-scroll"><table><thead><tr><th>Strategy</th><th>Signals</th><th>Entries</th><th>Denied</th><th>Wins / Losses</th><th>Points gained</th><th>Points lost</th><th>Net points</th><th>Gain / Loss</th><th>Win rate</th></tr></thead><tbody>
          {data.performance_summary.map((m:any)=><tr key={m.strategy_id}><td><strong>{m.strategy_id}</strong>{m.available===false&&<small>Unavailable: {m.unavailable_reason}</small>}</td><td>{m.available===false?'—':m.signals}</td><td>{m.available===false?'—':m.entries}</td><td>{m.available===false?'—':m.denied}</td><td>{m.available===false?'—':`${m.winning_trades} / ${m.losing_trades}`}</td><td className="hime-gain">{m.available===false?'—':Number(m.gross_points_gained).toFixed(2)}</td><td className="hime-loss">{m.available===false?'—':Number(m.gross_points_lost).toFixed(2)}</td><td>{m.available===false?'—':`${Number(m.net_points)>0?'+':''}${Number(m.net_points).toFixed(2)}`}</td><td>{m.available===false?'—':m.gain_loss_ratio===null?'∞':Number(m.gain_loss_ratio).toFixed(3)}</td><td>{m.available===false?'—':`${Number(m.win_rate_pct).toFixed(2)}%`}</td></tr>)}
        </tbody></table></div>
        {data.comparison&&<p><strong>WMA-gap vs v1:</strong> {Number(data.comparison.candidate_net_delta_vs_v1)>=0?'+':''}{Number(data.comparison.candidate_net_delta_vs_v1).toFixed(2)} points · Losses avoided {data.comparison.losses_avoided} · Winners denied {data.comparison.winners_denied}</p>}
      </section>}

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

      {strategyVersion==='V2_ALIGN' ? <HilegaReplayTradeLedger data={data} visibleUntil={until}/> : <>
      {data?.source==='RECOVERED_HISTORICAL_REPLAY' ? <section className="panel"><h4>Recovered NIFTY trades · no option fills</h4><div style={{overflowX:'auto'}}><table><thead><tr><th>Direction</th><th>Signal candle</th><th>Decision</th><th>Entry time</th><th>Entry NIFTY</th><th>Exit candle</th><th>Exit NIFTY</th><th>Points</th><th>Canonical points</th></tr></thead><tbody>{((data as any).recovered_trades??[]).map((r:any)=><tr key={r.trade_id}><td>{r.direction}</td><td>{shortTime(r.entry_timestamp)}</td><td>{strategyVersion==='V1'?'ENTRY':r.candidate_decision}</td><td>{strategyVersion==='V1'?shortTime(r.entry_timestamp):r.candidate_entry_timestamp?shortTime(r.candidate_entry_timestamp):'—'}</td><td>{strategyVersion==='V1'?Number(r.entry_price).toFixed(2):r.candidate_entry_price==null?'—':Number(r.candidate_entry_price).toFixed(2)}</td><td>{shortTime(r.exit_timestamp)}</td><td>{Number(r.exit_price).toFixed(2)}</td><td>{strategyVersion==='V1'?Number(r.canonical_points).toFixed(2):r.candidate_points==null?'Not entered':Number(r.candidate_points).toFixed(2)}</td><td>{Number(r.canonical_points).toFixed(2)}</td></tr>)}</tbody></table></div><p>Denied V2 rows show the original canonical exit for comparison, not a V2 exit. Times are candle labels; no fees or slippage included.</p></section> : <HilegaDirectionalReplayTrades sessionDate={selectedDate} />}

      </>}
      <HilegaDecisionTable key={`${selectedDate}-${data.source}-${step?'step':'full'}`} reports={reports}
        mode="HISTORICAL" visibleUntil={until}
        emptyMessage={data.parity?.status==='PARITY_MISMATCH'
          ? 'WMA-gap decision audit is blocked: recorded live signals were not materialized into the forward V1 control. Rebuild this forward session from authoritative recorded-live lifecycles.'
          : 'No Hilega strategy rows were recorded for this session.'}
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
