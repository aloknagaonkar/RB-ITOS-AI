import {useEffect,useState} from 'react'
import {fetchStrikePositioning,type StrikePositioningResult,type PositioningHorizon} from './strikePositioning'
const n=(x:any)=>typeof x==='number'&&Number.isFinite(x)?x.toLocaleString('en-IN',{maximumFractionDigits:3}):'—'
const label=(s:string)=>s.replaceAll('_',' ')
export default function HilegaPcrWorkspace(){
 const [data,setData]=useState<any>(null),[error,setError]=useState(''),[horizon,setHorizon]=useState<PositioningHorizon>(300)
 useEffect(()=>{let active=true,running=false
 async function refresh(){if(running)return;running=true;try{
  const get=async(url:string)=>{const r=await fetch(url);if(!r.ok)throw Error(`PCR HTTP ${r.status}`);return r.json()}
  const state=await get('/api/state?history_limit=1'),latest=state.history?.[0]
  if(!latest){if(active){setData({state});setError('No PCR observations collected yet')}return}
  const [detail,positioning]=await Promise.all([get(`/api/observations/${latest.id}`),fetchStrikePositioning(state.config_id,horizon)])
  if(detail.config_id!==state.config_id)throw Error('PCR configuration changed; waiting for next refresh')
  if(active){setData({state,detail,positioning});setError('')}
 }catch(e){if(active)setError(String(e))}finally{running=false}}
 void refresh();const timer=setInterval(refresh,15000);return()=>{active=false;clearInterval(timer)}},[horizon])
 const state=data?.state,detail=data?.detail,records:StrikePositioningResult[]=data?.positioning??[]
 const sameObservation=records.filter(r=>r.observation_id===detail?.id)
 const parts=new Intl.DateTimeFormat('en',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date())
 const today=['year','month','day'].map(k=>parts.find(p=>p.type===k)?.value).join('-')
 const expired=state?.config?.expiry<today
 return <section className="panel"><h2>PCR & option positioning — fixed and moving ATM ±5</h2>
 <p>Research observations · option premium and OI changes · independent of Hilega entry/exit rules.</p>
 {error&&<p role="alert">{error} · Previous displayed observations may be stale.</p>}
 <p>Provider: {state?.config?.provider??'—'} · Collection: {state?.enabled?'ENABLED':'PAUSED'} · Worker: {state?.worker?.alive?'RUNNING':'UNAVAILABLE'} · Expiry: {state?.config?.expiry??'—'}{expired?' — EXPIRED':''} · Anchor: {state?.config?.anchor_time??'—'} IST · Updated: {detail?.recorded_at??'—'} · Age: {n(state?.receipt_age_seconds)} seconds</p>
 {state?.config?.wings!==undefined&&state.config.wings!==5&&<p role="alert">PCR configuration has ±{state.config.wings} wings. Select ±5 in Configuration to collect the requested ranges.</p>}
 {state?.config?.provider==='demo'&&<p role="alert">DEMO DATA — select Upstox in Configuration for market observations.</p>}
 {state?.collection_overdue&&<p role="alert">COLLECTION OVERDUE — check PCR worker and market data.</p>}
 <label>Price/OI comparison window <select value={horizon} onChange={e=>setHorizon(Number(e.target.value) as PositioningHorizon)}><option value={300}>5 minutes</option><option value={900}>15 minutes</option><option value={1800}>30 minutes</option></select></label>
 {(['fixed','moving'] as const).map(mode=>{const panel=detail?.evaluation?.results?.find((r:any)=>r.mode===mode),strikes:number[]=panel?.strikes??[]
 return <div key={mode}><h3>{mode==='fixed'?'Fixed morning ATM':'Moving current ATM'} ±{state?.config?.wings??5}</h3>
 <p>ATM {n(panel?.atm)} · PCR {n(panel?.pcr)} = total PE OI / total CE OI · Coverage {panel?.received??0}/{panel?.expected??22} · {panel?.status??'UNAVAILABLE'}</p>
 <div style={{overflowX:'auto'}}><table><thead><tr><th>Strike</th><th>CE OI</th><th>CE previous → current price</th><th>CE price Δ%</th><th>CE OI Δ%</th><th>CE positioning</th><th>PE OI</th><th>PE previous → current price</th><th>PE price Δ%</th><th>PE OI Δ%</th><th>PE positioning</th><th>Strike PCR</th></tr></thead><tbody>{strikes.map(strike=>{const ce=sameObservation.find(r=>r.strike===strike&&r.side==='CE'),pe=sameObservation.find(r=>r.strike===strike&&r.side==='PE')
 const oi=(side:string)=>{const c=detail.snapshot.catalog.find((c:any)=>c.strike===strike&&c.side===side);return detail.snapshot.quotes.find((q:any)=>q.key===c?.key)?.oi}
 const co=oi('CE'),po=oi('PE')
 return <tr key={strike}><th>{n(strike)}{strike===panel.atm?' ATM':''}</th><td>{n(co)}</td><td>{n(ce?.baseline_ltp)} → {n(ce?.current_ltp)}</td><td>{n(ce?.price_change_pct)}</td><td title={`OI ${n(ce?.baseline_oi)} → ${n(ce?.current_oi)}`}>{n(ce?.observed_oi_change_pct)}</td><td>{label(ce?.classification??'UNAVAILABLE')}</td><td>{n(po)}</td><td>{n(pe?.baseline_ltp)} → {n(pe?.current_ltp)}</td><td>{n(pe?.price_change_pct)}</td><td title={`OI ${n(pe?.baseline_oi)} → ${n(pe?.current_oi)}`}>{n(pe?.observed_oi_change_pct)}</td><td>{label(pe?.classification??'UNAVAILABLE')}</td><td>{n(co>0&&po!=null?po/co:null)}</td></tr>})}</tbody></table></div>
 {!strikes.length&&<p>Range unavailable; waiting for valid observations and fixed anchor.</p>}</div>})}
 <p>Long buildup: price ↑ / OI ↑ · Short buildup: price ↓ / OI ↑ · Long unwinding: price ↓ / OI ↓ · Short covering: price ↑ / OI ↓. Missing baseline is UNAVAILABLE. These labels describe each option contract, not a guaranteed Nifty direction.</p>
 </section>
}
