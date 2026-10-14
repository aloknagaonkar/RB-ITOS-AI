import {useEffect,useState} from 'react'
import {usePcrContext,PcrSummary} from './hilegaPcrContext'
export default function HilegaPcrWorkspace(){
 const [horizon,setHorizon]=useState(300),[state,setState]=useState<any>(null),[error,setError]=useState('')
 const data=usePcrContext(undefined,undefined,horizon)
 useEffect(()=>{let active=true;const refresh=async()=>{try{const r=await fetch('/api/state?history_limit=1');if(!r.ok)throw Error('Collection status unavailable');const x=await r.json();if(active){setState(x);setError('')}}catch(e){if(active)setError(String(e))}};void refresh();const t=setInterval(refresh,15000);return()=>{active=false;clearInterval(t)}},[])
 return <section className="panel"><h2>PCR & option positioning — fixed and moving ATM ±5</h2>
 <p>Upstox observations · Collection {state?.enabled?'ENABLED':'PAUSED / UNAVAILABLE'} · Worker {state?.worker?.alive?'RUNNING':'UNAVAILABLE'} · Expiry {data?.expiry??state?.config?.expiry??'—'} · Updated {data?.available_at??'—'} · {data?.status??'LOADING'} {data?.reason??error}</p>
 {state?.config?.wings!==undefined&&state.config.wings!==5&&<p role="alert">Configured range is ±{state.config.wings}; select ±5 in Configuration.</p>}
 <label>Comparison <select value={horizon} onChange={e=>setHorizon(Number(e.target.value))}><option value={300}>5 minutes</option><option value={900}>15 minutes</option><option value={1800}>30 minutes</option></select></label>
 {data?.panels?.map((p:any)=><PcrSummary key={p.mode} panel={p} expand/>)}
 {!data?.panels?.length&&<p>Fixed and moving totals unavailable until fresh same-session Upstox observations are collected.</p>}
 <small>PCR = total PE OI / total CE OI. OI Δ% compares summed OI of the same contracts. Positioning and bias are diagnostic; conflicting evidence is MIXED, missing evidence UNAVAILABLE.</small>
 </section>
}
