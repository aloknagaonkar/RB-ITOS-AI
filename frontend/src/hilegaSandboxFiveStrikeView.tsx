import {useEffect,useState} from 'react'
import {matchSandbox,strikeRows} from './hilegaSandboxFiveStrikeModel.mjs'
const num=(v:any)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:2})
const ts=(v:any)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const tone=(v:any)=>v==null?'':v>=0?'positive':'negative'
export default function HilegaSandboxFiveStrikeView(){
  const [shadow,setShadow]=useState<any>(null),[sandbox,setSandbox]=useState<any>(null)
  const [error,setError]=useState(''),[updated,setUpdated]=useState<number|null>(null),[clock,setClock]=useState(Date.now())
  useEffect(()=>{let active=true,busy=false;let controller:AbortController|null=null
    const poll=async()=>{if(busy||document.hidden)return;busy=true;controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),15000)
      try{const urls=['/api/live-shadow/hilega-directional/trade-dashboard','/api/live-shadow/hilega-upstox-sandbox/dashboard'];const values=await Promise.all(urls.map(async url=>{const r=await fetch(url,{signal:controller!.signal});if(!r.ok)throw new Error(`Trade details HTTP ${r.status}`);return r.json()}));if(active){setShadow(values[0]);setSandbox(values[1]);setUpdated(Date.now());setError('')}}catch(e){if(active)setError((e as Error).message)}finally{clearTimeout(timeout);busy=false}}
    void poll();const interval=setInterval(()=>void poll(),10000);const tick=setInterval(()=>setClock(Date.now()),5000);return()=>{active=false;clearInterval(interval);clearInterval(tick);controller?.abort()}
  },[])
  const day=sandbox?.worker?.session_date
  const trades=(shadow?.trades??[]).filter((t:any)=>(t.signal_bar??'').slice(0,10)===day)
  const sandboxTrades=[sandbox?.active_trade,...(sandbox?.completed_trades??[])].filter(Boolean)
  const stale=updated!=null&&clock-updated>30000
  return <section className="panel shadow-panel">
    <div className="panel-heading"><div><h2>Sandbox signal · five-strike comparison</h2><p>ATM−2 through ATM+2 follow the shadow signal. Only the marked contract has Sandbox order acknowledgements. All displayed premium P&amp;L is estimated from observed quotes.</p></div><span className="pill">{day??'SESSION UNAVAILABLE'}</span></div>
    {error&&<div className="banner error">{error} · displayed values may be stale</div>}
    {stale&&<div className="banner error">Refresh is stale. Values are not current.</div>}
    <p>Refresh: {updated?ts(new Date(updated).toISOString()):'Waiting'} · Four comparison rows are observation only. Five-strike P&amp;L is not included in the Sandbox account total.</p>
    {!shadow||!sandbox?<div className="empty">Loading five-strike evidence…</div>:!trades.length?<div className="empty">No recorded five-strike lifecycle for this session. Earlier missing prices are not reconstructed.</div>:trades.map((trade:any)=>{
      const actual=matchSandbox(trade,sandboxTrades),rows=strikeRows(trade,actual)
      return <article className="panel shadow-panel" key={`${trade.direction}:${trade.signal_bar}`}>
        <div className="panel-heading"><div><h3>{trade.direction} · {trade.option_side} · {trade.status}</h3><p>Signal candle {ts(trade.signal_bar)} · Decision {ts(trade.signal_boundary)} · Expiry {trade.expiry??'Unavailable'} · ATM {num(trade.atm)}</p><p>{actual?`Sandbox trade ${actual.trade_id} · BUY acknowledged ${ts(actual.entry_time)} · SELL acknowledged ${ts(actual.exit_time)}`:'No uniquely matched Sandbox submission. This signal may be pre-arm, skipped or blocked; see dispatch reasons below.'}</p><p>Exit reason: {trade.exit_reason??'Not exited'} {trade.issue&&`· ${trade.issue}`}</p></div></div>
        <div className="shadow-table-scroll"><table className="shadow-table"><thead><tr><th>Strike / contract</th><th>Mode / state</th><th>Entry time / premium</th><th>Exit time / premium</th><th>Latest premium / quote minute</th><th>Estimated points / return</th><th>Comparison quantity / estimated ₹</th><th>MFE / MAE points</th><th>Sandbox order IDs</th></tr></thead><tbody>{rows.map((r:any)=><tr key={r.role}>
          <td>ATM{r.role===0?'':r.role>0?`+${r.role}`:r.role} · {num(r.leg?.strike)} {trade.option_side}<small>{r.leg?.instrument_key??'Instrument unavailable'}</small></td>
          <td>{r.selected?'SANDBOX SELECTED':'OBSERVATION ONLY'}<small>{r.state}</small></td>
          <td>{ts(r.leg?.entry_timestamp)}<small>{num(r.entry)}</small></td><td>{ts(r.leg?.exit_timestamp)}<small>{num(r.exit)}</small></td>
          <td>{num(r.mark)}<small>{ts(trade.status==='CLOSED'?r.leg?.exit_timestamp:r.leg?.latest_completed_minute)}</small></td>
          <td className={tone(r.points)}>{num(r.points)}<small>{r.points!=null&&r.entry>0?`${num(r.points/r.entry*100)}%`:'—'}</small></td>
          <td className={tone(r.estimated_rupees)}>{r.comparison_quantity??'Quantity unavailable'}<small>{r.estimated_rupees==null?'—':`₹${num(r.estimated_rupees)} hypothetical`}</small></td>
          <td>{num(r.leg?.mfe_points)} / {num(r.leg?.mae_points)}</td>
          <td>{r.selected?actual.entry_order_id??'Unavailable':'No order'}<small>{r.selected?actual.exit_order_id??'Exit not acknowledged':'—'}</small></td>
        </tr>)}</tbody></table></div>
        {actual&&<p>Selected-contract Sandbox quote estimate: {num(actual.estimated_points)} points · ₹{num(actual.estimated_pnl_rupees)}. This uses order-time reference quotes and can differ from the shadow candle-open comparison above. Confirmed fill P&amp;L is unavailable.</p>}
      </article>
    })}
  </section>
}
