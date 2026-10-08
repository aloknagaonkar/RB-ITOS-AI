import {useEffect,useState} from 'react'

type Status={operational?:{session_date?:string;option_expiry?:string;option_expiry_source?:string};current_session_date?:string}
type Sandbox={active_trade?:{expiry?:string;instrument_key?:string;strike?:number;option_type?:string};worker?:{armed?:boolean;session_date?:string;kill_switch?:boolean;running?:boolean};last_refresh?:string}
export function expiryCheck(expiry:string|undefined,session:string|undefined){
  if(!expiry||!session||!/^\d{4}-\d{2}-\d{2}$/.test(expiry)||!/^\d{4}-\d{2}-\d{2}$/.test(session))return 'UNVERIFIED'
  const valid=(v:string)=>{const d=new Date(v+'T00:00:00Z');return !isNaN(d.getTime())&&d.toISOString().slice(0,10)===v}
  if(!valid(expiry)||!valid(session))return 'UNVERIFIED'
  return expiry<session?'EXPIRED':'VALID_DATE'
}
const time=(value:number)=>new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false})
export default function HilegaExpiryWorkspace(){
  const [status,setStatus]=useState<Status|null>(null),[sandbox,setSandbox]=useState<Sandbox|null>(null)
  const [checked,setChecked]=useState(0),[error,setError]=useState(''),[clock,setClock]=useState(Date.now())
  useEffect(()=>{let active=true,busy=false;let controller:AbortController|null=null
    const poll=async()=>{if(busy||document.hidden)return;busy=true;controller=new AbortController();const timer=setTimeout(()=>controller?.abort(),15000)
      try{const fetchJson=async(url:string)=>{const r=await fetch(url,{signal:controller!.signal,cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()}
        const [a,b]=await Promise.allSettled([fetchJson('/api/live-shadow/hilega-directional/status'),fetchJson('/api/live-shadow/hilega-upstox-sandbox/dashboard')])
        if(!active)return
        if(a.status==='fulfilled'){setStatus(a.value);setChecked(Date.now())}else setStatus(null)
        if(b.status==='fulfilled')setSandbox(b.value);else setSandbox(null)
        setError(a.status==='rejected'||b.status==='rejected'?'One or more status sources unavailable; affected checks are unverified.':'')
      }catch{if(active){setStatus(null);setSandbox(null);setError('Expiry status unavailable')}}finally{clearTimeout(timer);busy=false}}
    void poll();const id=setInterval(()=>void poll(),30000);const tick=setInterval(()=>setClock(Date.now()),5000)
    return()=>{active=false;controller?.abort();clearInterval(id);clearInterval(tick)}},[])
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(clock))
  const op=status?.operational,session=op?.session_date??status?.current_session_date
  const stale=!checked||clock-checked>90000||session!==today
  const selected=stale?'UNVERIFIED':expiryCheck(op?.option_expiry,session)
  const contract=sandbox?.active_trade,worker=sandbox?.worker
  const sandboxCheck=expiryCheck(contract?.expiry,today)
  const color=(state:string)=>state==='VALID_DATE'?'#16834b':state==='EXPIRED'?'#c53030':'#9a6700'
  return <section className="panel shadow-panel" aria-label="Expiry selection workspace">
    <div className="panel-heading"><div><h2>Expiry selection &amp; validation</h2><p>Current Hilega selection and the contract retained by an active Sandbox trade.</p></div><span className="pill" style={{color:color(selected)}}>{selected==='VALID_DATE'?'VALID EXPIRY DATE':selected==='EXPIRED'?'EXPIRED — CHECK REQUIRED':'UNVERIFIED'}</span></div>
    {error&&<div className="banner error">{error}</div>}
    <div className="shadow-table-scroll"><table className="shadow-table"><thead><tr><th>Check</th><th>Observed information</th><th>Result</th></tr></thead><tbody>
      <tr><td>Current session</td><td>{session??'Unavailable'} · Today {today}</td><td style={{color:stale?'#9a6700':'#16834b'}}>{stale?'UNVERIFIED / STALE':'CURRENT'}</td></tr>
      <tr><td>Hilega selected expiry</td><td>{op?.option_expiry??'Unavailable'}</td><td style={{color:color(selected)}}>{selected}</td></tr>
      <tr><td>Selection source</td><td>{op?.option_expiry_source??'Unavailable'}</td><td>{op?.option_expiry_source?.startsWith('AUTO')?'AUTOMATIC':'MANUAL OR UNVERIFIED'}</td></tr>
      <tr><td>Nearest eligible expiry</td><td>Provider candidate list is not supplied by this status endpoint.</td><td style={{color:'#9a6700'}}>UNVERIFIED</td></tr>
      <tr><td>Active Sandbox contract</td><td>{contract?`${contract.strike??'—'} ${contract.option_type??'—'} · ${contract.instrument_key??'—'} · expiry ${contract.expiry??'—'}`:'No active Sandbox trade'}</td><td style={{color:color(sandboxCheck)}}>{contract?sandboxCheck:'NOT APPLICABLE'}</td></tr>
      <tr><td>Sandbox session arm</td><td>{worker?.session_date??'Unavailable'} · {worker?.armed?'Armed':'Disarmed / unavailable'} · kill switch {worker?.kill_switch===false?'OFF':'ON / unavailable'}</td><td style={{color:worker?.running&&worker?.armed&&worker?.kill_switch===false&&worker?.session_date===today?'#16834b':'#c53030'}}>{!worker?'UNVERIFIED':worker.running&&worker.armed&&worker.kill_switch===false&&worker.session_date===today?'ARMED FOR TODAY':'BLOCKED'}</td></tr>
    </tbody></table></div>
    <p>Last status received: {checked?time(checked):'Pending'}. Refresh every 30 seconds; Hilega checks become unverified after 90 seconds. Date validity does not verify instrument tradability or a broker fill. An open trade retains its entry contract for exit.</p>
  </section>
}
