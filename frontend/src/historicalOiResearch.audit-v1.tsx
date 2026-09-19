import {useEffect,useMemo,useState} from 'react'
import './historicalOiResearch.css'

type Session={session_date:string;rows:number}
type Row={
  block?:string;session_date:string;time:string;timestamp:string;spot:number|null;
  moving_atm:number|null;fixed_atm:number|null;
  m_ce_oi:number|null;m_pe_oi:number|null;m_ce_delta:number|null;m_pe_delta:number|null;
  m_ce_pct:number|null;m_pe_pct:number|null;m_activity:number|null;
  m_pcr_previous:number|null;m_pcr:number|null;m_pcr_change:number|null;
  m_common_strikes?:string;
  atm_ce_price_pct?:number|null;atm_pe_price_pct?:number|null;
  ce_state:string;pe_state:string;
  f_ce_delta?:number|null;f_pe_delta?:number|null;f_activity?:number|null;f_pcr:number|null;
  forward_5m_points?:number|null;forward_10m_points?:number|null;forward_15m_points?:number|null;
  pattern_family:string;
}

const n=(v:any,d=2)=>v==null?'—':Number(v).toFixed(d)
const i=(v:any)=>v==null?'—':Number(v).toLocaleString()
const pct=(v:any)=>v==null?'—':`${Number(v)>=0?'+':''}${Number(v).toFixed(2)}%`
const signed=(v:any,d=0)=>v==null?'—':`${Number(v)>=0?'+':''}${Number(v).toFixed(d)}`
const pcrDir=(v:any)=>v==null?'—':Number(v)>0?'RISING':Number(v)<0?'FALLING':'FLAT'

function Audit({row}:{row:Row}){
  const imbalance=(row.m_pe_delta==null||row.m_ce_delta==null)?null:row.m_pe_delta-row.m_ce_delta
  return <div className="hoi-audit">
    <div className="hoi-audit-title">{row.time} checkpoint audit</div>

    <div className="hoi-audit-grid">
      <section>
        <h4>Checkpoint context</h4>
        <div><span>Timestamp</span><b>{row.timestamp||'—'}</b></div>
        <div><span>Block</span><b>{row.block||'—'}</b></div>
        <div><span>Spot</span><b>{n(row.spot)}</b></div>
        <div><span>Moving ATM</span><b>{n(row.moving_atm,0)}</b></div>
        <div><span>Fixed ATM</span><b>{n(row.fixed_atm,0)}</b></div>
      </section>

      <section>
        <h4>Moving ATM OI</h4>
        <div><span>CE OI</span><b>{i(row.m_ce_oi)}</b></div>
        <div><span>PE OI</span><b>{i(row.m_pe_oi)}</b></div>
        <div><span>CE ΔOI</span><b>{signed(row.m_ce_delta)}</b></div>
        <div><span>PE ΔOI</span><b>{signed(row.m_pe_delta)}</b></div>
        <div><span>CE OI % change</span><b>{pct(row.m_ce_pct)}</b></div>
        <div><span>PE OI % change</span><b>{pct(row.m_pe_pct)}</b></div>
        <div><span>PE ΔOI − CE ΔOI</span><b>{signed(imbalance)}</b></div>
        <div><span>Total activity</span><b>{i(row.m_activity)}</b></div>
        <div><span>Common strikes</span><b>{row.m_common_strikes||'—'}</b></div>
      </section>

      <section>
        <h4>PCR</h4>
        <div><span>Previous PCR</span><b>{n(row.m_pcr_previous,3)}</b></div>
        <div><span>Current PCR</span><b>{n(row.m_pcr,3)}</b></div>
        <div><span>PCR change</span><b>{signed(row.m_pcr_change,3)}</b></div>
        <div><span>PCR direction</span><b>{pcrDir(row.m_pcr_change)}</b></div>
      </section>

      <section>
        <h4>Positioning</h4>
        <div><span>CE state</span><b>{row.ce_state||'—'}</b></div>
        <div><span>PE state</span><b>{row.pe_state||'—'}</b></div>
        <div><span>ATM CE price %</span><b>{pct(row.atm_ce_price_pct)}</b></div>
        <div><span>ATM PE price %</span><b>{pct(row.atm_pe_price_pct)}</b></div>
        <div><span>Pattern</span><b>{row.pattern_family||'—'}</b></div>
      </section>

      <section>
        <h4>Fixed basket</h4>
        <div><span>Fixed CE ΔOI</span><b>{signed(row.f_ce_delta)}</b></div>
        <div><span>Fixed PE ΔOI</span><b>{signed(row.f_pe_delta)}</b></div>
        <div><span>Fixed activity</span><b>{i(row.f_activity)}</b></div>
        <div><span>Fixed PCR</span><b>{n(row.f_pcr,3)}</b></div>
      </section>

      <section>
        <h4>Forward research context</h4>
        <div><span>NIFTY +5m</span><b>{signed(row.forward_5m_points,2)} pts</b></div>
        <div><span>NIFTY +10m</span><b>{signed(row.forward_10m_points,2)} pts</b></div>
        <div><span>NIFTY +15m</span><b>{signed(row.forward_15m_points,2)} pts</b></div>
      </section>
    </div>

    <p className="hoi-audit-note">
      Forward returns are retrospective research labels and are not inputs to the checkpoint classification.
    </p>
  </div>
}

export default function HistoricalOiResearch(){
  const [sessions,setSessions]=useState<Session[]>([])
  const [selected,setSelected]=useState('')
  const [rows,setRows]=useState<Row[]>([])
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const [expanded,setExpanded]=useState<string|null>(null)

  useEffect(()=>{
    fetch('/api/live-shadow/replay-ops/historical-oi/sessions')
      .then(async r=>{const v=await r.json();if(!r.ok)throw new Error(v?.detail||'Historical OI sessions unavailable');return v})
      .then(v=>{const s=v.sessions||[];setSessions(s);if(s.length)setSelected(s[0].session_date)})
      .catch(e=>setError(String(e)))
  },[])

  useEffect(()=>{
    if(!selected)return
    setExpanded(null);setLoading(true);setError('')
    fetch(`/api/live-shadow/replay-ops/historical-oi/session?session_date=${encodeURIComponent(selected)}`)
      .then(async r=>{const v=await r.json();if(!r.ok)throw new Error(v?.detail||'Historical OI session unavailable');return v})
      .then(v=>setRows(v.rows||[]))
      .catch(e=>setError(String(e)))
      .finally(()=>setLoading(false))
  },[selected])

  const summary=useMemo(()=>{
    if(!rows.length)return null
    const last=rows[rows.length-1]
    return {count:rows.length,lastTime:last.time,lastPcr:last.m_pcr,lastPattern:last.pattern_family}
  },[rows])

  return <section className="hoi">
    <div className="hoi-head">
      <div><h3>Historical OI research</h3><p>90-session historical evidence source · separate from strict live-shadow replay.</p></div>
      <label>Date
        <select value={selected} onChange={e=>setSelected(e.target.value)}>
          {sessions.map(s=><option key={s.session_date} value={s.session_date}>{s.session_date} ({s.rows})</option>)}
        </select>
      </label>
    </div>

    {error&&<div className="hoi-error">{error}</div>}

    <div className="hoi-cards">
      <div><span>Sessions</span><b>{sessions.length||'—'}</b></div>
      <div><span>Rows this day</span><b>{summary?.count??'—'}</b></div>
      <div><span>Last checkpoint</span><b>{summary?.lastTime??'—'}</b></div>
      <div><span>Last moving PCR</span><b>{n(summary?.lastPcr,3)}</b></div>
    </div>

    <div className="hoi-table-wrap"><table className="hoi-table">
      <thead><tr>
        <th>Time</th><th>Spot</th><th>ATM</th><th>PCR</th><th>PCR Δ</th>
        <th>CE state</th><th>PE state</th><th>Pattern</th><th>Details</th>
      </tr></thead>
      <tbody>
        {rows.map((r,idx)=>{
          const key=r.timestamp||`${r.time}-${idx}`
          const open=expanded===key
          return <>
            <tr key={key}>
              <td>{r.time}</td><td>{n(r.spot)}</td><td>{n(r.moving_atm,0)}</td>
              <td>{n(r.m_pcr,3)}</td><td>{signed(r.m_pcr_change,3)}</td>
              <td>{r.ce_state||'—'}</td><td>{r.pe_state||'—'}</td><td>{r.pattern_family||'—'}</td>
              <td><button onClick={()=>setExpanded(open?null:key)}>{open?'Hide':'Audit'}</button></td>
            </tr>
            {open&&<tr key={`${key}-audit`}><td colSpan={9}><Audit row={r}/></td></tr>}
          </>
        })}
        {!loading&&!rows.length&&<tr><td colSpan={9}>No historical OI rows for this date.</td></tr>}
      </tbody>
    </table></div>
    <p className="hoi-note">Historical OI research evidence is separate from strict live-shadow replay readiness.</p>
  </section>
}
