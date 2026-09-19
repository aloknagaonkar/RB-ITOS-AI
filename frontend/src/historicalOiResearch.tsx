import {useEffect,useMemo,useState} from 'react'
import './historicalOiResearch.css'

type Session={session_date:string;rows:number}
type Row={session_date:string;time:string;timestamp:string;spot:number|null;moving_atm:number|null;fixed_atm:number|null;m_ce_oi:number|null;m_pe_oi:number|null;m_ce_delta:number|null;m_pe_delta:number|null;m_pcr_previous:number|null;m_pcr:number|null;m_pcr_change:number|null;ce_state:string;pe_state:string;f_pcr:number|null;pattern_family:string}

const n=(v:any,d=2)=>v==null?'—':Number(v).toFixed(d)
const i=(v:any)=>v==null?'—':Number(v).toLocaleString()

export default function HistoricalOiResearch(){
  const [sessions,setSessions]=useState<Session[]>([])
  const [selected,setSelected]=useState('')
  const [rows,setRows]=useState<Row[]>([])
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')

  useEffect(()=>{
    fetch('/api/live-shadow/replay-ops/historical-oi/sessions')
      .then(async r=>{const v=await r.json();if(!r.ok)throw new Error(v?.detail||'Historical OI sessions unavailable');return v})
      .then(v=>{const s=v.sessions||[];setSessions(s);if(s.length)setSelected(s[0].session_date)})
      .catch(e=>setError(String(e)))
  },[])

  useEffect(()=>{
    if(!selected)return
    setLoading(true);setError('')
    fetch(`/api/live-shadow/replay-ops/historical-oi/session?session_date=${encodeURIComponent(selected)}`)
      .then(async r=>{const v=await r.json();if(!r.ok)throw new Error(v?.detail||'Historical OI session unavailable');return v})
      .then(v=>setRows(v.rows||[]))
      .catch(e=>setError(String(e)))
      .finally(()=>setLoading(false))
  },[selected])

  const summary=useMemo(()=>{if(!rows.length)return null;const last=rows[rows.length-1];return {count:rows.length,lastTime:last.time,lastPcr:last.m_pcr}},[rows])

  return <section className="hoi">
    <div className="hoi-head">
      <div><h3>Historical OI research</h3><p>90-session historical evidence source · separate from strict live-shadow replay.</p></div>
      <label>Date<select value={selected} onChange={e=>setSelected(e.target.value)}>{sessions.map(s=><option key={s.session_date} value={s.session_date}>{s.session_date} ({s.rows})</option>)}</select></label>
    </div>
    {error&&<div className="hoi-error">{error}</div>}
    <div className="hoi-cards">
      <div><span>Sessions</span><b>{sessions.length||'—'}</b></div>
      <div><span>Rows this day</span><b>{summary?.count??'—'}</b></div>
      <div><span>Last checkpoint</span><b>{summary?.lastTime??'—'}</b></div>
      <div><span>Last moving PCR</span><b>{n(summary?.lastPcr,3)}</b></div>
    </div>
    <div className="hoi-table-wrap"><table className="hoi-table">
      <thead><tr><th>Time</th><th>Spot</th><th>ATM</th><th>CE OI</th><th>PE OI</th><th>CE ΔOI</th><th>PE ΔOI</th><th>PCR prev</th><th>PCR</th><th>PCR Δ</th><th>CE state</th><th>PE state</th><th>Fixed PCR</th><th>Pattern</th></tr></thead>
      <tbody>{rows.map((r,idx)=><tr key={`${r.timestamp}-${idx}`}><td>{r.time}</td><td>{n(r.spot)}</td><td>{n(r.moving_atm,0)}</td><td>{i(r.m_ce_oi)}</td><td>{i(r.m_pe_oi)}</td><td>{i(r.m_ce_delta)}</td><td>{i(r.m_pe_delta)}</td><td>{n(r.m_pcr_previous,3)}</td><td>{n(r.m_pcr,3)}</td><td>{n(r.m_pcr_change,3)}</td><td>{r.ce_state||'—'}</td><td>{r.pe_state||'—'}</td><td>{n(r.f_pcr,3)}</td><td>{r.pattern_family||'—'}</td></tr>)}{!loading&&!rows.length&&<tr><td colSpan={14}>No historical OI rows for this date.</td></tr>}</tbody>
    </table></div>
    <p className="hoi-note">This is historical OI/PCR research evidence. It does not replace the exact production snapshots required by strict live-shadow replay.</p>
  </section>
}
