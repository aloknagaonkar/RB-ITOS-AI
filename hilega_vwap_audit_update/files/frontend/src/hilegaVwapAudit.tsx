import {useEffect,useState} from 'react'

const n=(v:any)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-IN',{maximumFractionDigits:2}):'Unavailable'
const t=(v:any)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'Not recorded'

export default function HilegaVwapAudit({at,allowedUntil}:{at:string;allowedUntil?:string}){
  const [data,setData]=useState<any>(null),[error,setError]=useState('')
  const future=!!allowedUntil&&new Date(at).getTime()>new Date(allowedUntil).getTime()
  useEffect(()=>{let active=true;const c=new AbortController();setData(null);setError('')
    if(future)return()=>c.abort()
    const timer=setTimeout(()=>c.abort(),10000)
    void fetch('/api/live-shadow/hilega-vwap-observation/inspection?at='+encodeURIComponent(at),{signal:c.signal})
      .then(r=>{if(!r.ok)throw Error(`VWAP observation HTTP ${r.status}`);return r.json()})
      .then(d=>{if(active)setData(d)}).catch(e=>{if(active)setError((e as Error).message)}).finally(()=>clearTimeout(timer))
    return()=>{active=false;clearTimeout(timer);c.abort()}
  },[at,future])
  return <section className="hilega-audit-section"><h4>VWAP observation · no entry or exit gate</h4>
    <p>NIFTY futures price versus the same contract’s cumulative session VWAP proxy. This is separate enrichment; the recorded strategy decision is unchanged.</p>
    {future?<p>Not yet available at the selected replay time.</p>:error?<p>{error}</p>:!data?<p>Loading VWAP evidence…</p>:<>
      {!data.rows?.length?<p>No VWAP observation recorded for this exact setup/entry checkpoint. Run the independent collector; missing evidence does not mean a failed strategy check.</p>:<div className="hd-scroll shadow-table-scroll"><table className="hd-table shadow-table"><thead><tr><th>Observation</th><th>Direction</th><th>Futures price</th><th>VWAP</th><th>Price position</th><th>Distance</th><th>Direction agreement</th><th>Timing / source</th></tr></thead><tbody>{data.rows.map((r:any,i:number)=><tr key={i}><td>{r.kind.replaceAll('_',' ')}<small>{r.source}</small></td><td>{r.direction}</td><td>{n(r.futures_close)}</td><td>{n(r.vwap)}</td><td>{r.price_position}</td><td>{n(r.distance_points)} points</td><td>{r.price_position==='AT'?'NEUTRAL':r.direction_agrees_with_vwap?'AGREES':'OPPOSES'}<small>Observation only</small></td><td>Signal {t(r.signal_time)}<small>Candle available {t(r.candle_available_at)} · age {n(r.age_at_signal_seconds)} seconds</small><small>{r.instrument_key} · {r.origin}</small></td></tr>)}</tbody></table></div>}
      {!!data.issues?.length&&<p>Data issues: {data.issues.join(' · ')}</p>}
      {!!data.rows?.length&&<details><summary>VWAP calculation and raw evidence</summary><p>Session resets at 09:15 IST. VWAP = cumulative [(high + low + close) / 3 × volume] / cumulative volume. Five-minute candles must be complete by the signal. Historical retrieval is reconstructed evidence; a journal row alone does not prove it was captured at signal time.</p><pre>{JSON.stringify(data.rows,null,2)}</pre></details>}
    </>}
  </section>
}
