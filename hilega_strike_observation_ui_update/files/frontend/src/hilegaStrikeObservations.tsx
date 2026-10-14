import {useEffect, useState} from 'react'

const n=(v:any)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-IN',{maximumFractionDigits:3}):'Unavailable'
const t=(v:any)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'Not recorded'
const list=(v:any)=>Array.isArray(v)?v:[]

function Audit({row,frame}:{row:any,frame:any}){
  const a=row.audit??{}
  return <details><summary>Why rank {row.rank}?</summary>
    <p>{a.selection_reason??'Selection reason was not recorded.'}</p>
    <p>Policy {frame.policy_version??'Not recorded'} · Signal {frame.signal??'Not recorded'} · Entry {t(frame.entry_timestamp)} · Quote {t(row.entry_quote_timestamp)}</p>
    <h4>Favourable conditions at selection</h4>
    {list(a.favourable_conditions).length?<ul>{list(a.favourable_conditions).map((s:any,i:number)=><li key={i}>{String(s)}</li>)}</ul>:<p>Not recorded.</p>}
    <h4>Filter evidence</h4><table className="shadow-table"><thead><tr><th>Check</th><th>Observed</th><th>Required</th><th>Result</th></tr></thead><tbody>{list(a.filters).map((f:any,i:number)=><tr key={i}><td>{f.name}</td><td>{String(f.observed??'Not recorded')}</td><td>{String(f.required??'Not recorded')}</td><td>{f.result??'Not recorded'}</td></tr>)}</tbody></table>
    <p>Delta {n(row.delta)} · Gamma {n(row.gamma)} · Theta {n(row.theta)} · Vega {n(row.vega)} · IV {n(row.iv)} · DTE {n(row.dte)}</p>
    <p>Entry bid / ask {n(row.entry_bid)} / {n(row.entry_ask)} · Bid / ask depth {n(row.entry_bid_quantity)} / {n(row.entry_ask_quantity)} · Spread {n(row.entry_spread_percent)}%</p>
    <p>Modelled ROI {n(row.modelled_roi_percent)}% · Gamma / premium {n(row.leverage_score)} · Distance to 0.45 delta {n(row.delta_target_distance)}</p>
    <h4>Ranking comparison</h4><p>{a.rank_comparison??'Comparison with other candidates was not recorded.'}</p>
    <h4>Frozen model assumptions</h4><pre>{JSON.stringify(frame.assumptions??{status:'Not recorded'},null,2)}</pre>
    <h4>Risk flags</h4><p>{list(a.risk_flags).length?list(a.risk_flags).join(' · '):'No risk assessment recorded.'}</p>
    <p>Invalidation spot {n(frame.assumptions?.invalidation_spot)} · Modelled premium at invalidation {n(row.invalidation_modelled_premium)} · Modelled change {n(row.invalidation_modelled_change)}</p>
    <p>Instrument {row.instrument_key} · Observation {frame.observation_id??'Not recorded'} · Entry snapshot {frame.entry_snapshot_id??'Not recorded'}</p>
  </details>
}

export default function HilegaStrikeObservations(){
  const [data,setData]=useState<any>(null),[error,setError]=useState(''),[received,setReceived]=useState(0),[clock,setClock]=useState(Date.now())
  useEffect(()=>{let active=true,busy=false;let controller:AbortController|null=null
    const poll=async()=>{if(busy||document.hidden)return;busy=true;const c=new AbortController();controller=c;const timer=setTimeout(()=>c.abort(),15000)
      try{const r=await fetch('/api/live-shadow/hilega-strike-observation/dashboard',{signal:c.signal});if(!r.ok)throw Error(`Observation view HTTP ${r.status}`);const d=await r.json();if(active){setData(d);setError('');setReceived(Date.now())}}catch(e){if(active)setError((e as Error).message)}finally{clearTimeout(timer);busy=false}}
    void poll();const interval=setInterval(()=>void poll(),10000),tick=setInterval(()=>setClock(Date.now()),5000)
    return()=>{active=false;clearInterval(interval);clearInterval(tick);controller?.abort()}
  },[])
  const stale=!!received&&clock-received>30000
  return <section className="panel shadow-panel"><h2>Strike Selection Observations · Top 5</h2>
    <p>Separate observation of ATM ±5 candidates. Each row is an alternative trade; hypothetical P&amp;L is not added to Sandbox P&amp;L. No orders are sent.</p>
    {error&&<div className="banner error">{error}</div>}{stale&&<div className="banner error">Observation view is stale; refresh before using displayed values.</div>}
    {!data?<p>Loading observations…</p>:<><p>{data.status==='NOT_CONNECTED'?'Observation collector not connected yet.':data.status.replaceAll('_',' ')} · Read {t(data.read_at)}</p>
      {!!list(data.errors).length&&<div className="banner error">{list(data.errors).join(' · ')}</div>}
      {!list(data.frames).length&&<div className="empty">No recorded strike evaluations. Ranking reasons and P&amp;L will appear only when evidence is available.</div>}
      {list(data.frames).map((frame:any,index:number)=><article className="panel" key={`${frame.observation_id}-${frame.timestamp}-${index}`}><h3>{frame.signal??'Signal unavailable'} · Spot {n(frame.spot)} · {t(frame.timestamp)}</h3><p>{frame.verdict??'Verdict not recorded'} · {frame.reason??''} · Policy {frame.policy_version??'Not recorded'}</p>
        <div className="shadow-table-scroll"><table className="shadow-table"><thead><tr><th>Rank</th><th>Strike</th><th>Modelled ROI</th><th>Entry ask</th><th>Current / exit bid</th><th>Option points</th><th>Hypothetical net P&amp;L / ROI</th><th>Selection audit</th></tr></thead><tbody>
          {Array.from({length:5},(_,i)=>{const row=list(frame.top5)[i];return row?<tr key={row.instrument_key}><td>{i+1}</td><td>{n(row.strike)} {row.option_type}<small>Quantity {n(row.quantity)}</small></td><td>{n(row.modelled_roi_percent)}%</td><td>{n(row.entry_ask)}</td><td>{n(row.state==='CLOSED'?row.exit_bid:row.current_bid)}<small>{t(row.state==='CLOSED'?row.exit_quote_timestamp:row.quote_timestamp)}</small></td><td>{stale?'Unavailable':n(row.points)}</td><td>{stale?'Unavailable':`₹${n(row.pnl_rupees)} / ${n(row.roi_percent)}%`}<small>{row.pnl_status} · Costs ₹{n(row.total_cost_rupees)}</small></td><td><Audit row={row} frame={frame}/></td></tr>:<tr key={i}><td>{i+1}</td><td colSpan={7}>NO_SUITABLE_CONTRACT · {frame.unfilled_slot_reason??'No additional eligible contract recorded; inspect rejection log.'}</td></tr>})}
        </tbody></table></div><details><summary>Rejected candidates and exact filter failures</summary>{list(frame.rejections).length?<ul>{list(frame.rejections).map((r:any,i:number)=><li key={i}>{r.strike} {r.option_type}: {r.step??'Step not recorded'} · {list(r.reasons).join(', ')||r.reason||'Reason not recorded'}</li>)}</ul>:<p>No rejection evidence recorded.</p>}</details>
      </article>)}
    </>}
  </section>
}
