import {useEffect,useRef,useState} from 'react'
const newId=()=>{if(typeof crypto.randomUUID==='function')return crypto.randomUUID();const a=crypto.getRandomValues(new Uint8Array(16));a[6]=(a[6]&15)|64;a[8]=(a[8]&63)|128;const h=Array.from(a,x=>x.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`}
const labels:Record<string,string>={REQUESTED:'Exit requested',EXITING:'Exiting Sandbox positions',VERIFYING:'Checking remaining quantities',RECONCILIATION_REQUIRED:'Exit needs reconciliation; new entries paused',WAITING_FOR_STRATEGY_RESET:'Positions closed; waiting for strategy reset',READY_FOR_FRESH_SIGNAL:'Closed; waiting for a fresh signal'}
export default function HilegaManualExit(){
 const [state,setState]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const id=useRef<string|null>(null)
 useEffect(()=>{let active=true,inflight=false;const refresh=async()=>{
  if(inflight)return;inflight=true;const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000)
  try{const r=await fetch('/api/live-shadow/hilega-upstox-sandbox/manual-exit',{signal:controller.signal});if(!r.ok)throw new Error(`Exit status HTTP ${r.status}`);const x=await r.json();if(active){setState(x);setError('');if(x.request?.request_id===id.current)id.current=null}}catch(e){if(active)setError((e as Error).message)}finally{clearTimeout(timeout);inflight=false}}
  void refresh();const timer=setInterval(()=>void refresh(),5000);return()=>{active=false;clearInterval(timer)}
 },[])
 const request=state?.request,active=!!request&&request.status!=='READY_FOR_FRESH_SIGNAL'
 const submit=async()=>{
  if(busy||active||!state?.trade_ids?.length)return
  setBusy(true);setError('');id.current=id.current||newId();const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000)
  try{const r=await fetch('/api/live-shadow/hilega-upstox-sandbox/manual-exit',{method:'POST',signal:controller.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:id.current,session_date:state.session_date,expected_trade_ids:state.trade_ids,confirmation:'EXIT_ALL_SANDBOX_LEGS'})});const x=await r.json();if(!r.ok)throw new Error(x.detail||`Exit HTTP ${r.status}`);setState({...state,request:x});id.current=null}catch(e){setError((e as Error).message)}finally{clearTimeout(timeout);setBusy(false)}
 }
 return <section className="panel shadow-panel"><h2>Manual exit · Sandbox</h2><p>Close all open legs belonging to this strategy. New entries resume after closure and strategy reset, on a fresh signal.</p>
 <button type="button" disabled={busy||active||!state?.trade_ids?.length} onClick={()=>void submit()}>{busy?'Requesting exit…':'Exit all Sandbox positions'}</button>
 {request&&<p role="status">{labels[request.status]||request.status}{request.last_error?` · ${request.last_error}`:''}</p>}
 {error&&<div className="banner error">{error}</div>}
 {request?.legs?.length>0&&<details><summary>Exit progress by leg</summary><table className="shadow-table"><thead><tr><th>Contract</th><th>Filled BUY quantity</th><th>Remaining quantity</th><th>Confirmed P&amp;L</th></tr></thead><tbody>{request.legs.map((l:any)=><tr key={`${l.trade_id}-${l.role}`}><td>{l.contract.strike} {l.contract.option_type}</td><td>{l.confirmed_buy?.filled??'Checking'}</td><td>{l.remaining_quantity??'Checking'}</td><td>{l.confirmed_pnl_rupees==null?'Pending':`₹${Number(l.confirmed_pnl_rupees).toFixed(2)}`}</td></tr>)}</tbody></table></details>}
 </section>
}
