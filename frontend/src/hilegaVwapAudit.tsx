import {useEffect,useState} from 'react'

const n=(v:any)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-IN',{maximumFractionDigits:2}):'Unavailable'
const t=(v:any)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'Not recorded'

export default function HilegaVwapAudit({at,allowedUntil}:{at:string;allowedUntil?:string}){
  const [data,setData]=useState<any>(null),[error,setError]=useState('')
  const future=!!allowedUntil&&new Date(at).getTime()>new Date(allowedUntil).getTime()
  useEffect(()=>{
    let active=true,busy=false
    let controller:AbortController|null=null
    setData(null);setError('')
    const load=async()=>{
      if(future||busy||document.hidden)return
      busy=true;controller=new AbortController()
      const timer=setTimeout(()=>controller?.abort(),10000)
      try{
        const response=await fetch('/api/live-shadow/hilega-vwap-observation/inspection?at='+encodeURIComponent(at),{signal:controller.signal})
        if(!response.ok)throw Error(`VWAP observation HTTP ${response.status}`)
        const frame=await response.json()
        if(active){setData(frame);setError('')}
      }catch(e){if(active)setError((e as Error).message)}
      finally{clearTimeout(timer);busy=false}
    }
    void load()
    const interval=setInterval(()=>void load(),30000)
    return()=>{active=false;clearInterval(interval);controller?.abort()}
  },[at,future])
  return <section className="hilega-audit-section hilega-vwap-evidence"><style>{`.hilega-vwap-evidence td small{display:block;margin-top:4px;line-height:1.4}.hilega-vwap-evidence td{vertical-align:top}`}</style><h4>VWAP observation · no entry or exit gate</h4>
    <p>NIFTY futures close versus the same contract’s cumulative session VWAP proxy. Uses only five-minute candles complete by this decision. Strategy decisions are unchanged.</p>
    {future?<p>Not yet available at the selected replay time.</p>:<>
      {error&&<p>VWAP refresh error: {error}. Retained evidence below may be from an earlier refresh.</p>}
      {!data?<p>{error?'VWAP evidence unavailable.':'Loading VWAP evidence…'}</p>:<>
        {!data.rows?.length?<p>No usable VWAP evidence for decision {t(at)}. The collector retries every minute; this view refreshes every 30 seconds. Missing evidence is not a failed strategy check.</p>:<div className="hd-scroll shadow-table-scroll"><table className="hd-table shadow-table"><thead><tr><th>Observation</th><th>Direction context</th><th>Futures close</th><th>VWAP</th><th>Price position</th><th>Distance</th><th>Direction agreement</th><th>Timing / source</th></tr></thead><tbody>{data.rows.map((r:any,i:number)=><tr key={`${r.kind}-${r.source}-${i}`}><td>{r.kind==='ARMED_CANDIDATE'?'CANDIDATE ARMED':String(r.kind).replaceAll('_',' ')}<small>{r.source}</small></td><td>{r.direction==='NONE'?'No directional context':r.direction}<small>{r.context_type==='ARMED_CANDIDATE'?'Pending candidate; entry not confirmed':r.context_type==='ACTIVE_POSITION'?'Active position':r.context_type==='EXITING_POSITION'?'Exiting position':r.kind==='SETUP'?'New setup':r.kind==='CONFIRMED_ENTRY'?'Confirmed entry':''}</small></td><td>{n(r.futures_close)}</td><td>{n(r.vwap)}</td><td>{r.price_position}</td><td>{n(r.distance_points)} points</td><td>{r.direction_agrees_with_vwap==null?'NOT APPLICABLE':r.price_position==='AT'?'NEUTRAL':r.direction_agrees_with_vwap?'AGREES':'OPPOSES'}<small>Observation only</small></td><td>Decision {t(r.signal_time)}<small>Candle available {t(r.candle_available_at)} · age {n(r.age_at_signal_seconds)} seconds</small><small>{r.instrument_key} · {r.origin}</small><small>{r.reconstructed||r.origin==='RECONSTRUCTED_FROM_SAVED_FUTURES'?'Reconstructed evidence; does not prove capture at decision time':`Collected ${t(r.collected_at)}; journal storage alone does not prove capture at decision time`}</small></td></tr>)}</tbody></table></div>}
        {!!data.superseded_context_rows&&<p>Armed-candidate evidence replaces an earlier neutral context display. Original journal records are retained.</p>}
        {!!data.issues?.length&&<p>Data issues: {data.issues.join(' · ')}</p>}
        {!!data.rows?.length&&<details><summary>VWAP calculation and raw evidence</summary><p>Session resets at 09:15 IST. VWAP = cumulative [(high + low + close) / 3 × volume] / cumulative volume. Only completed five-minute candles are used. Saved-data reconstruction is labelled separately.</p><pre>{JSON.stringify(data.rows,null,2)}</pre></details>}
      </>}
    </>}
  </section>
}
