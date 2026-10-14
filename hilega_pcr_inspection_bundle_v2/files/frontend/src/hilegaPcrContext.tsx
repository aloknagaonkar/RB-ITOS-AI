import {useEffect,useState} from 'react'
export const fmt=(x:any)=>typeof x==='number'&&Number.isFinite(x)?x.toLocaleString('en-IN',{maximumFractionDigits:3}):'—'
const words=(x:any)=>String(x??'UNAVAILABLE').replaceAll('_',' ')
export function usePcrContext(at?:string,expiry?:string,horizon=300){
 const [data,setData]=useState<any>(null)
 useEffect(()=>{let active=true,busy=false;let controller:AbortController|null=null
 const poll=async()=>{if(busy)return;busy=true;controller=new AbortController();const timer=setTimeout(()=>controller?.abort(),10000)
 try{const params=new URLSearchParams({horizon:String(horizon)});if(at)params.set('at',at);if(expiry)params.set('expiry',expiry)
 const r=await fetch('/api/live-shadow/hilega-pcr/context?'+params,{signal:controller.signal});if(!r.ok)throw Error('PCR unavailable')
 const x=await r.json();if(active)setData(x)}catch{if(active)setData({status:'UNAVAILABLE',reason:'PCR_REQUEST_FAILED',panels:[],strikes:[]})}finally{busy=false;clearTimeout(timer)}}
 void poll();const interval=at?null:setInterval(poll,15000);return()=>{active=false;controller?.abort();if(interval)clearInterval(interval)}},[at,expiry,horizon])
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
