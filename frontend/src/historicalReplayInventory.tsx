import {useEffect,useMemo,useState} from 'react'
import './historicalReplayInventory.css'

type Row={session_date:string;classification:string;snapshot_records:number;strict_covered:number;legacy_covered:number;expected_checkpoints:number;futures_status:string}
type Props={selectedDate:string;onSelectDate:(d:string)=>void}

export default function HistoricalReplayInventory({selectedDate,onSelectDate}:Props){
  const [rows,setRows]=useState<Row[]>([])
  const [counts,setCounts]=useState<Record<string,number>>({})
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const [filter,setFilter]=useState('ALL')

  const refresh=async()=>{
    setLoading(true);setError('')
    try{
      const r=await fetch('/api/live-shadow/replay-ops/inventory')
      const v=await r.json().catch(()=>({}))
      if(!r.ok) throw new Error(v?.detail||'Inventory unavailable')
      setRows(v.rows||[]);setCounts(v.counts||{})
    }catch(e){setError(String(e))}
    finally{setLoading(false)}
  }

  useEffect(()=>{void refresh()},[])
  const visible=useMemo(()=>filter==='ALL'?rows:rows.filter(r=>r.classification===filter),[rows,filter])

  return <section className="hri">
    <div className="hri-head">
      <div><h3>Replay session inventory</h3><p>See usable dates before checking them one by one.</p></div>
      <button disabled={loading} onClick={()=>void refresh()}>{loading?'Scanning…':'Refresh inventory'}</button>
    </div>
    {error&&<div className="hri-error">{error}</div>}
    <div className="hri-summary">
      {['ALL','STRICT_READY','LEGACY_COMPATIBLE','PARTIAL','UNAVAILABLE'].map(k=>
        <button key={k} className={filter===k?'active':''} onClick={()=>setFilter(k)}>
          {k.replaceAll('_',' ')} {k==='ALL'?rows.length:(counts[k]||0)}
        </button>
      )}
    </div>
    <div className="hri-table-wrap"><table className="hri-table">
      <thead><tr><th>Date</th><th>Status</th><th>Snapshots</th><th>Strict 30s</th><th>Legacy 65s</th><th>Futures</th><th></th></tr></thead>
      <tbody>
        {visible.map(r=><tr key={r.session_date} className={selectedDate===r.session_date?'selected':''}>
          <td>{r.session_date}</td><td>{r.classification.replaceAll('_',' ')}</td><td>{r.snapshot_records}</td>
          <td>{r.strict_covered}/{r.expected_checkpoints}</td><td>{r.legacy_covered}/{r.expected_checkpoints}</td>
          <td>{r.futures_status}</td><td><button onClick={()=>onSelectDate(r.session_date)}>Use date</button></td>
        </tr>)}
        {!loading&&!visible.length&&<tr><td colSpan={7}>No sessions in this category.</td></tr>}
      </tbody>
    </table></div>
    <p className="hri-note">STRICT READY = 74/74 within +30s. LEGACY COMPATIBLE = 74/74 only within +65s. Legacy replay is not enabled by this patch.</p>
  </section>
}
