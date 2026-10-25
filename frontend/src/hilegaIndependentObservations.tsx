import {useEffect,useState} from 'react'
import {fetchLive,startLivePolling,useActiveLiveMarks} from './hilegaLivePolling'
import {LiveMarkHeaders,LiveMarkCells,LiveTradeTotal} from './hilegaActiveLiveMarkCells'

const n=(v:any)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-IN',{maximumFractionDigits:2}):'—'
const ts=(v:any)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'

export default function HilegaIndependentObservations({sandboxTrades=[]}:{sandboxTrades?:any[]}){
  const [data,setData]=useState<any>(null),[error,setError]=useState('')
  const liveMarks=useActiveLiveMarks()
  const [received,setReceived]=useState(0),[clock,setClock]=useState(Date.now())
  useEffect(()=>{
    let active=true,busy=false
    let controller:AbortController|null=null
    const poll=async()=>{
      if(busy||document.hidden)return
      busy=true
      controller=new AbortController()
      const timeout=setTimeout(()=>controller?.abort(),12000)
      try{
        const r=await fetchLive('/api/live-shadow/hilega-directional/trade-dashboard',controller.signal)
        if(!r.ok)throw new Error(`Observation HTTP ${r.status}`)
        const p=await r.json()
        if(p.model!=='HILEGA_DIRECTIONAL_SHADOW_DASHBOARD_V1'||!Array.isArray(p.trades))throw new Error('Unexpected observation response')
        if(active){setData(p);setError('');setReceived(Date.now())}
      }catch(e){if(active)setError((e as Error).message)}
      finally{clearTimeout(timeout);busy=false}
    }
    const stop=startLivePolling(poll,5000)
    const tick=setInterval(()=>setClock(Date.now()),5000)
    return()=>{active=false;stop();clearInterval(tick);controller?.abort()}
  },[])
  const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(clock))
  const trades=(data?.trades??[]).filter((t:any)=>String(t.signal_boundary??t.signal_bar??'').slice(0,10)===day)
  const refreshStale=!!error||!received||clock-received>30000
  return <section className="panel shadow-panel">
    <div className="panel-heading"><div><h2>Independent observation · five contracts</h2><p>Confirmed bullish signal → CE · bearish signal → PE. Tracks confirmed strategy entries and exits independently of Sandbox fills; candidate and follow-up events do not open positions.</p></div><span className="pill">{day}</span></div>
    <p>Hypothetical candle-based P&amp;L. Entry/exit use exact minute opens; marks use completed minute closes. Fees, spreads and slippage excluded. These five contracts are not Greek-policy rankings.</p>
    <p>Last dashboard refresh: {ts(received?new Date(received).toISOString():null)}</p>
    {liveMarks.error&&<p>Live quote update unavailable: {liveMarks.error}. Recorded candle marks are retained.</p>}
    {error&&<div className="banner error">{error} · retained values may be stale</div>}
    {!data?<div className="empty">Loading observation evidence…</div>:!trades.length?<div className="empty">No option lifecycle recorded for today. No entry prices have been invented.</div>:trades.map((trade:any)=>{
      const matches=sandboxTrades.filter((t:any)=>t.direction===trade.direction&&t.expiry===trade.expiry&&t.signal_time===trade.signal_boundary)
      return <details className="panel shadow-panel" key={`${trade.direction}:${trade.signal_bar}:${trade.strategy_version??'legacy'}`} open={trade.status==='ACTIVE'}>
        <summary style={{cursor:'pointer'}}>{trade.direction} · {trade.option_side} · {ts(trade.signal_boundary??trade.signal_bar)} · {trade.status}</summary>
        <p>Strategy {trade.policy_id??'Legacy recorded policy'} · {trade.strategy_version??'Version not recorded'}</p>
        <p>Expiry {trade.expiry??'Unavailable'} · Source {trade.source??'Unavailable'} · Exit {trade.exit_reason??'Pending'}</p>
        <LiveTradeTotal trade={trade} find={liveMarks.find}/>
        {trade.issue&&<div className="banner error">{trade.issue}</div>}
        {trade.status==='MANUAL_RELEASED'&&<p>Manual exit ended this observation. An exact option closing price was not recorded; closing P&amp;L remains unavailable.</p>}
        {!(trade.legs??[]).length?<p>Exact option entry evidence unavailable.</p>:<div className="shadow-table-scroll"><table className="shadow-table">
          <thead><tr><th>Strike</th><th>Entry / time</th><th>Latest premium / minute</th><th>Exit / time</th><th>Points / ROI</th><th>Hypothetical one-lot ₹ P&amp;L</th><th>Evidence</th><LiveMarkHeaders/></tr></thead>
          <tbody>{trade.legs.map((leg:any)=>{
            const closed=trade.status==='CLOSED',active=trade.status==='ACTIVE'
            const markTime=Date.parse(leg.latest_completed_minute??'')
            const stale=active&&(refreshStale||!Number.isFinite(markTime)||markTime>clock||clock-markTime>180000)
            const points=closed?leg.realized_points:active&&!stale?leg.current_points:null
            const roi=closed?leg.realized_return_pct:active&&!stale?leg.current_return_pct:null
            const contracts=matches.length===1?(matches[0].legs??[]).filter((l:any)=>l.instrument_key===leg.instrument_key&&l.strike===leg.strike&&l.option_type===trade.option_side):[]
            const lot=contracts.length===1?contracts[0].lot_size:null
            const rupees=typeof points==='number'&&Number.isInteger(lot)&&lot>0?points*lot:null
            return <tr key={leg.instrument_key}>
              <td>{n(leg.strike)} {trade.option_side}<small>{leg.instrument_key}</small></td>
              <td>{n(leg.entry_open)}<small>{ts(leg.entry_timestamp)}</small></td>
              <td>{n(leg.latest_close)}<small>{ts(leg.latest_completed_minute)}</small></td>
              <td>{n(leg.exit_open)}<small>{ts(leg.exit_timestamp)}</small></td>
              <td>{n(points)}<small>{n(roi)}{roi!=null?'%':''}</small></td>
              <td>{rupees==null?'Unavailable':`₹${n(rupees)}`}<small>{rupees==null?'Missing mark or unique lot-size metadata':`${lot} units · hypothetical`}</small></td>
              <td>{stale?'STALE / MISSING MARK':closed?'EXACT CANDLE EXIT':active?'COMPLETED MINUTE MARK':'FINAL PRICE UNAVAILABLE'}</td>
              <LiveMarkCells mark={active?liveMarks.find(trade,leg.instrument_key):null}/>
            </tr>
          })}</tbody>
        </table></div>}
      </details>
    })}
    <p>Observation results are separate from Sandbox account P&amp;L. No orders are submitted by this panel.</p>
  </section>
}
