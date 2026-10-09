import {useEffect,useState} from 'react'
export const fmt=(x:any)=>typeof x==='number'&&Number.isFinite(x)?x.toLocaleString('en-IN',{maximumFractionDigits:3}):'—'
const words=(x:any)=>String(x??'UNAVAILABLE').replaceAll('_',' ')
const shared=new Map<string,{data:any;time:number;pending?:Promise<any>}>()
async function loadShared(at:string|undefined,horizon:number){
 const key=JSON.stringify([at??null,horizon]),old=shared.get(key)
 if(old?.pending)return old.pending
 if(old&&Date.now()-old.time<15000)return old.data
 const entry=old??{data:null,time:0};shared.set(key,entry)
 entry.pending=(async()=>{const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000)
 try{const params=new URLSearchParams({horizon:String(horizon)});if(at)params.set('at',at)
 const response=await fetch('/api/live-shadow/hilega-pcr/context?'+params,{signal:controller.signal})
 if(!response.ok)throw Error('PCR unavailable')
 entry.data=await response.json();entry.time=Date.now();return entry.data
 }catch{entry.data={status:'UNAVAILABLE',reason:'PCR_REQUEST_FAILED',panels:[],strikes:[]};entry.time=Date.now();return entry.data}
 finally{clearTimeout(timer);entry.pending=undefined;if(shared.size>128){const victim=[...shared.keys()].find(k=>k!==key&&!shared.get(k)?.pending);if(victim)shared.delete(victim)}}})()
 return entry.pending
}
export function usePcrContext(at?:string,expiry?:string,horizon=300){
 const [data,setData]=useState<any>(null)
 useEffect(()=>{let active=true
 const poll=async()=>{if(document.hidden)return;const x=await loadShared(at,horizon)
 if(active)setData(expiry&&x.expiry!==expiry?{status:'UNAVAILABLE',reason:'CONTRACT_EXPIRY_NOT_COLLECTED',panels:[],strikes:[]}:x)}
 setData(null);void poll();const interval=at?null:setInterval(poll,15000)
 document.addEventListener('visibilitychange',poll)
 return()=>{active=false;if(interval)clearInterval(interval);document.removeEventListener('visibilitychange',poll)}},[at,expiry,horizon])
 return data
}
export function strikeBias(data:any,strike:number,key:string){
 if(data?.status!=='AVAILABLE')return 'UNAVAILABLE'
 const row=data.strikes?.find((r:any)=>r.strike===strike&&(r.ce_key===key||r.pe_key===key))
 return row?.combined_bias??'UNAVAILABLE'
}
export function PcrSummary({panel,expand=false}:{panel:any;expand?:boolean}){
 return <div><h3>{panel.mode==='fixed'?'Fixed morning ATM':'Moving ATM'} · ATM {fmt(panel.atm)}</h3>
 <div style={{overflowX:'auto'}}><table><thead><tr><th>PCR</th><th>CE OI Δ%</th><th>PE OI Δ%</th><th>CE positioning</th><th>PE positioning</th><th>Combined bias</th></tr></thead><tbody><tr><td>{fmt(panel.pcr)}</td><td>{fmt(panel.ce_oi_change_pct)}</td><td>{fmt(panel.pe_oi_change_pct)}</td><td>{words(panel.ce_positioning)}</td><td>{words(panel.pe_positioning)}</td><td>{panel.combined_bias}</td></tr></tbody></table></div>
 {expand&&<details><summary>Expand {panel.strikes.length} strikes · coverage {panel.received??'—'}/{panel.expected??'—'}</summary><div style={{overflowX:'auto'}}><table><thead><tr><th>Strike</th><th>PCR</th><th>CE OI Δ%</th><th>CE positioning</th><th>PE OI Δ%</th><th>PE positioning</th><th>Combined bias</th></tr></thead><tbody>{panel.strikes.map((r:any)=><tr key={r.strike}><th>{fmt(r.strike)}</th><td>{fmt(r.pcr)}</td><td>{fmt(r.ce?.observed_oi_change_pct)}</td><td>{words(r.ce?.classification)}</td><td>{fmt(r.pe?.observed_oi_change_pct)}</td><td>{words(r.pe?.classification)}</td><td>{r.combined_bias}</td></tr>)}</tbody></table></div></details>}
 </div>
}
export default function HilegaPcrAuditCard({at}:{at:string}){
 const data=usePcrContext(at)
 return <article className="panel"><h3>PCR & positioning at this decision</h3><p>Decision boundary {at} · {data?.status??'LOADING'} · {data?.reason??''}</p>
 {data?.status==='AVAILABLE'&&<><p>Expiry {data.expiry} · Observation #{data.observation_id} · Available {data.available_at} · Age {fmt(data.age_seconds)}s · 5-minute baseline</p>{data.panels.map((p:any)=><PcrSummary key={p.mode} panel={p} expand/>)}</>}
 <small>Persisted observations available by this boundary only; no later market data. Missing historical PCR is unavailable.</small></article>
}
