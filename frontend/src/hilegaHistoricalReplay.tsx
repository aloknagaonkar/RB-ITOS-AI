import {useEffect, useMemo, useState} from 'react'
import './hilegaHistoricalReplay.css'

type Capture = {session_date:string;capture_id:string;expiry:string|null;has_manifest:boolean}
type Audit = {
 checkpoint:string;bar:Record<string,any>;indicators:Record<string,any>;
 conditions:Record<string,any>;strategy:Record<string,any>;
 route_a:Record<string,any>;route_b:Record<string,any>;
 transitions:Array<Record<string,any>>;
 option_candidate:Record<string,any>|null;
 option_market_snapshot:Record<string,any>|null;
 option_lifecycle:Record<string,any>;
 audit_integrity:Record<string,any>;
}
type Response = {session_date:string;capture_id:string;reports:Audit[];report_count:number;
 audit_chain_ok:boolean;audit_chain_issue:string|null;manifest:Record<string,any>;warning:string}
const fmt=(x:any)=> x===null||x===undefined?'—':String(x)
const time=(x:string)=>{const d=new Date(x); return Number.isNaN(d.getTime()) ? x.slice(11,16) : d.toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',hour12:false})}
const pretty=(x:any)=>JSON.stringify(x??{},null,2)

// Existing Historical Replay owns date selection; this adapter never runs a broker job.
export default function HilegaHistoricalReplay({selectedDate}:{selectedDate:string}){
 const [captures,setCaptures]=useState<Capture[]>([])
 const [captureId,setCaptureId]=useState('')
 const [data,setData]=useState<Response|null>(null)
 const [index,setIndex]=useState(0)
 const [playing,setPlaying]=useState(false)
 const [error,setError]=useState('')
 const [note,setNote]=useState('')
 const [reviews,setReviews]=useState<Record<string,{label:string;note:string}>>({})
 const available=useMemo(()=>captures.filter(c=>c.session_date===selectedDate),[captures,selectedDate])
 useEffect(()=>{
   let active=true
   fetch('/api/live-shadow/hilega-historical/sessions').then(async r=>{if(!r.ok)throw new Error(`Sessions HTTP ${r.status}`);return r.json()})
     .then(v=>{if(active)setCaptures(v.sessions||[])})
     .catch(e=>{if(active)setError(String(e))})
   return()=>{active=false}
 },[])
 useEffect(()=>{setCaptureId(available[0]?.capture_id||'');setData(null);setIndex(0);setPlaying(false);setError('')},[selectedDate,captures])
 useEffect(()=>{
   if(!captureId)return
   let active=true
   setData(null);setError('');setPlaying(false)
   fetch(`/api/live-shadow/hilega-historical/capture?capture_id=${encodeURIComponent(captureId)}`)
     .then(async r=>{if(!r.ok)throw new Error(`Capture HTTP ${r.status}: ${await r.text()}`);return r.json()})
     .then(v=>{if(active){setData(v);setIndex(0)}})
     .catch(e=>{if(active)setError(String(e))})
   return()=>{active=false}
 },[captureId])
 const reports=data?.reports||[]
 useEffect(()=>{if(!playing || !reports.length)return;const id=window.setInterval(()=>setIndex(i=>Math.min(i+1,reports.length-1)),1000);return()=>window.clearInterval(id)},[playing,reports.length])
 useEffect(()=>{if(index>=reports.length-1)setPlaying(false)},[index,reports.length])
 const reviewKey=`hime-review:${captureId}`
 useEffect(()=>{try{setReviews(JSON.parse(localStorage.getItem(reviewKey)||'{}'))}catch{setReviews({})}},[reviewKey])
 const current=reports[index]
 const key=current?.checkpoint||''
 useEffect(()=>setNote(reviews[key]?.note||''),[key,reviews])
 function mark(label:string){if(!current)return;const value={...reviews,[key]:{label,note}};setReviews(value);localStorage.setItem(reviewKey,JSON.stringify(value))}
 function exportReviews(){const value={capture_id:captureId,session_date:selectedDate,reviews};const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`${captureId}-manual-reviews.json`;a.click();URL.revokeObjectURL(url)}
 const bars=reports.slice(0,index+1).filter(r=>r.bar && r.bar.open!=null && r.bar.high!=null && r.bar.low!=null && r.bar.close!=null)
 const allMin=Math.min(...bars.map(r=>Number(r.bar.low))), allMax=Math.max(...bars.map(r=>Number(r.bar.high)))
 const range=Math.max(1,allMax-allMin)
 const width=Math.max(680,bars.length*11)
 const y=(v:number)=>18+(allMax-v)/range*180
 return <section className="hime-replay" aria-label="Hilega historical replay">
   <h3>Hilega-Milega · Historical candle review</h3>
   <p>Uses the existing historical evidence and shared live coordinator audit. Read-only; never starts another replay worker.</p>
   <label>Historical capture <select value={captureId} onChange={e=>setCaptureId(e.target.value)}>
     {!available.length&&<option value="">No Hilega capture for selected date</option>}
     {available.map(c=><option value={c.capture_id} key={c.capture_id}>{c.capture_id} · Expiry {fmt(c.expiry)}</option>)}
   </select></label>
   {error&&<p role="alert" className="hime-error">{error}</p>}
   {data&&<><div className="hime-meta"><span>Session {data.session_date}</span><span>Expiry {fmt(data.manifest.expiry)}</span><span>Audit chain {data.audit_chain_ok?'PASS':'FAIL'}</span><span>Checkpoints {reports.length}</span></div>
     <p className="hime-warning">{data.warning} {data.audit_chain_issue||''}</p>
     {current?<>
       <div className="hime-controls">
         <button onClick={()=>{setPlaying(false);setIndex(0)}}>Reset</button>
         <button disabled={index===0} onClick={()=>{setPlaying(false);setIndex(i=>i-1)}}>◀ Previous</button>
         <button onClick={()=>setPlaying(v=>!v)} disabled={index===reports.length-1}>{playing?'Pause':'Play'}</button>
         <button disabled={index===reports.length-1} onClick={()=>{setPlaying(false);setIndex(i=>i+1)}}>Next ▶</button>
         <label>Candle <input aria-label="Select candle" type="range" min={0} max={Math.max(0,reports.length-1)} value={index} onChange={e=>{setPlaying(false);setIndex(Number(e.target.value))}} /></label>
         <strong>{index+1}/{reports.length} · {time(current.checkpoint)} IST</strong>
       </div>
       {bars.length>0&&<div className="hime-chart-scroll"><svg role="img" aria-label="Historical Nifty candles, showing only candles through current replay time" width={width} height="225" viewBox={`0 0 ${width} 225`}>
         {bars.map((r,i)=>{const b=r.bar;const x=15+i*11;const o=y(Number(b.open));const c=y(Number(b.close));const h=y(Number(b.high));const l=y(Number(b.low));const up=Number(b.close)>=Number(b.open);return <g key={r.checkpoint}><title>{time(r.checkpoint)} O {b.open} H {b.high} L {b.low} C {b.close}</title><line x1={x+3} x2={x+3} y1={h} y2={l} stroke={up?'#188554':'#c24b4b'}/><rect x={x} y={Math.min(o,c)} width="6" height={Math.max(1,Math.abs(o-c))} fill={up?'#188554':'#c24b4b'}/></g>})}
       </svg><small>Audit-derived five-minute OHLC; future candles are hidden. Only checkpoints with recorded OHLC are charted.</small></div>}
       <div className="hime-cards">
         <div><b>Candle</b><p>O {fmt(current.bar.open)} · H {fmt(current.bar.high)} · L {fmt(current.bar.low)} · C {fmt(current.bar.close)}</p></div>
         <div><b>Strategy</b><p>{fmt(current.strategy.state_before)} → {fmt(current.strategy.state_after)}</p><p>Route {fmt(current.strategy.selected_route)}</p></div>
         <div><b>Indicators</b><p>RSI9 {fmt(current.indicators.rsi9)} · EMA3 {fmt(current.indicators.ema3_rsi)} · WMA21 {fmt(current.indicators.wma21_rsi)}</p></div>
         <div><b>Options</b><p>Candidate {fmt(current.option_candidate?.status)} · ATM {fmt(current.option_candidate?.atm)}</p></div>
       </div>
       <details open><summary>Opening / Route A / Route B and conditions</summary><pre>{pretty({strategy:current.strategy,conditions:current.conditions,route_a:current.route_a,route_b:current.route_b})}</pre></details>
       <details><summary>Entry / exit transitions</summary><pre>{pretty(current.transitions)}</pre></details>
       <details><summary>ATM±2 CE candidates and option market snapshot</summary><pre>{pretty({option_candidate:current.option_candidate,market_snapshot:current.option_market_snapshot})}</pre></details>
       <details><summary>Independent option lifecycle and premiums</summary><pre>{pretty(current.option_lifecycle)}</pre></details>
       <details><summary>Detailed audit integrity</summary><pre>{pretty(current.audit_integrity)}</pre></details>
       <div className="hime-review"><b>Manual review</b><textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="Compare with the Nifty chart; record an observation"/>
         <select aria-label="Review label" value={reviews[key]?.label||''} onChange={e=>mark(e.target.value)}><option value="">Unreviewed</option><option>Correct</option><option>Needs investigation</option><option>Possible missed opportunity</option><option>Possible incorrect entry or exit</option><option>Data discrepancy</option></select>
         <button onClick={()=>mark(reviews[key]?.label||'Needs investigation')}>Save observation</button><button onClick={exportReviews}>Export reviews JSON</button>
       </div>
     </>:<p>Capture has no detailed strategy checkpoints.</p>}
   </>}
 </section>
}
