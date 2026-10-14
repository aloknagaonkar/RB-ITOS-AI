import {useEffect,useState} from 'react'
const at=(s?:string)=>s?new Date(s).toLocaleString('en-GB',{timeZone:'Asia/Kolkata',hour12:false}):'Unavailable'
export default function OperationalReadiness({expanded=false}:{expanded?:boolean}){
 const [data,setData]=useState<any>(null),[error,setError]=useState(''),[received,setReceived]=useState(0),[clock,setClock]=useState(Date.now())
 useEffect(()=>{let active=true,busy=false;let controller:AbortController|null=null
  const poll=async()=>{if(busy)return;busy=true;controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),6000)
   try{const r=await fetch('/api/data-health/readiness',{signal:controller.signal,cache:'no-store'});if(!r.ok)throw Error(`Readiness check unavailable (HTTP ${r.status})`);const x=await r.json();if(active){setData(x);setReceived(Date.now());setError('')}}catch(e){if(active)setError((e as Error).message)}finally{clearTimeout(timeout);busy=false}}
  void poll();const timer=setInterval(()=>void poll(),15000),tick=setInterval(()=>setClock(Date.now()),5000);return()=>{active=false;controller?.abort();clearInterval(timer);clearInterval(tick)}
 },[])
 const stale=!!data&&(data.monitor_stale||clock-received>45000),alerts=(data?.alerts??[]).filter((a:any)=>a.active),bad=!!error||stale||['NOT_READY','MONITOR_ERROR','MONITOR_UNAVAILABLE'].includes(data?.status),last=(data?.notifications??[]).slice(-5).reverse()
 return <section className="panel" aria-label="Operational readiness" style={{borderColor:bad?'#e77777':undefined}}>
  <div role={bad?'alert':'status'} aria-live="polite"><b>{bad?'NOT READY':data?.status??'Checking readiness'} · {data?.session_date??'Current session'}</b> · <span>{stale?'Independent monitor stale':error||`${data?.phase?.replaceAll('_',' ')??''} · Checked ${at(data?.checked_at)}`}</span></div>
  {alerts.map((a:any)=><div className="banner error" key={a.id}><b>{a.component}{a.escalated?' · persistent failure':''}</b>: {a.message}<small style={{display:'block'}}>First detected {at(a.first_seen)} · Last detected {at(a.last_seen)} · Last successful {at(a.last_successful)}</small></div>)}
  {!expanded&&!bad&&last[0]?.kind==='RECOVERY'&&<p>Recovered: {last[0].message} · {at(last[0].timestamp)}</p>}
  {expanded&&<>
   <h2>Pre-market readiness and live components</h2><p>Independent checks every 15 seconds. Readiness does not submit orders or arm sandbox. Analytics credentials are checked with a read-only quote request. Sandbox token presence is checked; monitoring never submits a test order.</p>
   <div className="shadow-table-scroll"><table className="shadow-table"><thead><tr><th>Check</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{(data?.checks??[]).map((c:any)=><tr key={c.id}><td>{c.label}</td><td>{c.status}</td><td>{c.message}</td></tr>)}</tbody></table></div>
   <h3>Schedule · IST</h3><p>08:45 warmup validation · 08:50 repair · 09:00 configuration and sandbox · 09:10 final report · 09:15 live monitoring</p>
   <p>Warmup sessions validated: {data?.warmup?.complete_sessions??'Unavailable'}. Missing calendar dates are not verified holidays.</p>
   {(data?.recovered_entries??[]).map((r:any)=><p key={r.entry_time}>Recovered shadow entry {at(r.entry_time)} — {r.sandbox_submitted?'sandbox submission recorded separately':'no sandbox order recorded; recovered events are not automatically submitted'}.</p>)}
   <h3>Recent notifications</h3>{last.length?last.map((n:any,i:number)=><p key={`${n.timestamp}-${i}`}><b>{n.kind}</b> · {at(n.timestamp)} · {n.message}</p>):<p>No recorded notifications.</p>}
  </>}
 </section>
}
