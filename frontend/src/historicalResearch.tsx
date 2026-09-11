import { useMemo, useState } from 'react'

type Status = 'AVAILABLE'|'UNAVAILABLE'
type HistoricalStrike = {
  provenance:string; strike:number; call_oi:number|null; put_oi:number|null;
  previous_call_oi:number|null; previous_put_oi:number|null;
  call_oi_change:number|null; put_oi_change:number|null;
  call_oi_change_pct:number|null; put_oi_change_pct:number|null;
  pcr:number|null; status:Status; issues:string[]
}
type HistoricalPanel = {
  provenance:string; mode:'fixed'|'moving'|'full_reconstructed'; atm:number|null; strikes:number[];
  expected_contracts:number|null; received_oi_contracts:number|null;
  call_oi:number|null; put_oi:number|null; previous_call_oi:number|null; previous_put_oi:number|null;
  call_oi_change:number|null; put_oi_change:number|null; call_oi_change_pct:number|null; put_oi_change_pct:number|null;
  pcr:number|null; status:Status; issues:string[]
}
type HistoricalObservation = {
  provenance:string; timestamp:string; session_date:string; underlying:string; expiry:string; spot:number; moving_atm:number;
  strike_results:HistoricalStrike[]; fixed_panel:HistoricalPanel; moving_panel:HistoricalPanel; full_reconstructed_panel:HistoricalPanel
}
type HistoricalSession = {
  status:Status; underlying:string; session_date:string; expiry:string; wings:number; strike_interval:number;
  provenance:string; observations:HistoricalObservation[]; issues:string[]
}

const palette = {fixed:'#52dac0',moving:'#a499ff',full:'#8d9eae'}
const fmt=(v:number|null|undefined,d=2)=>v==null?'—':v.toLocaleString('en-IN',{maximumFractionDigits:d})
const signed=(v:number|null|undefined,d=2)=>v==null?'—':`${v>0?'+':''}${fmt(v,d)}`
const t=(iso:string)=>new Date(iso).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',hour12:false})

async function fetchHistorical(underlying:string,sessionDate:string,expiry:string,wings:number):Promise<HistoricalSession>{
  const query=new URLSearchParams({underlying,session_date:sessionDate,expiry,wings:String(wings)})
  const response=await fetch(`/api/research/historical/pcr?${query}`)
  if(!response.ok){
    const value=await response.json().catch(()=>null)
    throw new Error(typeof value?.detail==='string'?value.detail:'Historical session request failed.')
  }
  return response.json()
}

function HistoricalChart({observations,selected,onSelect}:{observations:HistoricalObservation[];selected:number;onSelect:(index:number)=>void}){
  const series=observations.flatMap(o=>[o.fixed_panel.pcr,o.moving_panel.pcr,o.full_reconstructed_panel.pcr].filter((v):v is number=>v!=null))
  if(!series.length)return <div className="empty">No valid historical PCR observations.</div>
  const low=Math.min(...series,1)-.06, high=Math.max(...series,1)+.06
  const x=(i:number)=>55+i*865/Math.max(1,observations.length-1)
  const y=(v:number)=>220-(v-low)/(high-low)*185
  const modes:[keyof typeof palette,(o:HistoricalObservation)=>number|null][]=[
    ['fixed',o=>o.fixed_panel.pcr],['moving',o=>o.moving_panel.pcr],['full',o=>o.full_reconstructed_panel.pcr]
  ]
  return <svg viewBox="0 0 960 270" role="img" aria-label="Historical PCR comparison">
    {[0,1,2,3,4].map(i=>{const value=low+(high-low)*i/4;return <g key={i}><line x1="55" x2="920" y1={y(value)} y2={y(value)} stroke="#25343f" strokeDasharray="3 5"/><text x="8" y={y(value)+4}>{value.toFixed(2)}</text></g>})}
    {modes.map(([mode,get])=>{let path='',pen=false;observations.forEach((o,i)=>{const v=get(o);if(v==null){pen=false;return}path+=`${pen?'L':'M'}${x(i)},${y(v)} `;pen=true});return <path key={mode} d={path} fill="none" stroke={palette[mode]} strokeWidth={mode==='full'?1.5:2.5}/>})}
    {observations.map((o,i)=><rect key={o.timestamp} x={x(i)-2} y="25" width={Math.max(4,860/observations.length)} height="200" fill={i===selected?'#ffffff12':'transparent'} className="chart-hit" onClick={()=>onSelect(i)}><title>{t(o.timestamp)} · Spot {fmt(o.spot)}</title></rect>)}
    <text x="55" y="252">{t(observations[0].timestamp)}</text><text x="920" y="252" textAnchor="end">{t(observations.at(-1)!.timestamp)} IST</text>
  </svg>
}

function PanelCard({title,panel,color}:{title:string;panel:HistoricalPanel;color:string}){
  return <article className="metric" style={{borderTopColor:color}}><div className="metric-title"><span>{title}</span><span className="mini-dot" style={{background:color}}/></div>
    <div className="metric-value"><span className="metric-current-label">PCR</span>{panel.pcr==null?'—':panel.pcr.toFixed(3)}</div>
    <div className="trend-metrics"><span>ATM <b>{fmt(panel.atm,0)}</b></span><span>Call OI <b>{fmt(panel.call_oi,0)}</b></span><span>Put OI <b>{fmt(panel.put_oi,0)}</b></span><span>Status <b>{panel.status}</b></span></div>
    <div className="metric-sub"><span>{panel.received_oi_contracts??0}/{panel.expected_contracts??0} contracts</span><span>{panel.strikes.length} strikes</span></div>
  </article>
}

export default function HistoricalResearch({defaultUnderlying,defaultExpiry,defaultWings}:{defaultUnderlying:string;defaultExpiry:string;defaultWings:number}){
  const [underlying,setUnderlying]=useState(defaultUnderlying)
  const [sessionDate,setSessionDate]=useState('2026-09-08')
  const [expiry,setExpiry]=useState(defaultExpiry)
  const [wings,setWings]=useState(defaultWings)
  const [session,setSession]=useState<HistoricalSession|null>(null)
  const [selected,setSelected]=useState(0)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const load=async()=>{setBusy(true);setError('');try{const value=await fetchHistorical(underlying,sessionDate,expiry,wings);setSession(value);setSelected(Math.min(5,Math.max(0,value.observations.length-1)))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  const observation=session?.observations[selected]??null
  const anchor=useMemo(()=>session?.observations.find(o=>o.fixed_panel.status==='AVAILABLE')??null,[session])
  return <>
    <section className="panel historical-controls"><div className="panel-heading"><div><h2>Historical session</h2><p>Reconstruct one deterministic PCR session from Upstox expired option candles.</p></div><span className="pill teal">RESEARCH ONLY</span></div>
      <div className="historical-form"><label>Underlying<input value={underlying} onChange={e=>setUnderlying(e.target.value)}/></label><label>Session date<input type="date" value={sessionDate} onChange={e=>setSessionDate(e.target.value)}/></label><label>Expiry<input type="date" value={expiry} onChange={e=>setExpiry(e.target.value)}/></label><label>Wings<input type="number" min="0" max="20" value={wings} onChange={e=>setWings(Number(e.target.value))}/></label><button className="primary" disabled={busy||!underlying||!sessionDate||!expiry} onClick={()=>void load()}>{busy?'Loading…':'Load session'}</button></div>
      {error&&<div className="historical-error">{error}</div>}
    </section>
    {!session?<div className="empty historical-empty">Choose a session and expiry, then load historical research data.</div>:<>
      <div className="historical-summary"><span>Status <b>{session.status}</b></span><span>Observations <b>{session.observations.length}</b></span><span>Anchor <b>{anchor?t(anchor.timestamp):'Unavailable'}</b></span><span>Fixed ATM <b>{fmt(anchor?.fixed_panel.atm,0)}</b></span><span>Provenance <b>{session.provenance}</b></span></div>
      {observation&&<div className="metrics"><PanelCard title="Fixed morning ATM" panel={observation.fixed_panel} color={palette.fixed}/><PanelCard title="Moving ATM" panel={observation.moving_panel} color={palette.moving}/><PanelCard title="Full reconstructed" panel={observation.full_reconstructed_panel} color={palette.full}/></div>}
      <section className="panel"><div className="panel-heading"><div><h2>Historical PCR timeline</h2><p>{session.session_date} · {session.observations.length} one-minute observations</p></div><select aria-label="Historical timestamp" value={selected} onChange={e=>setSelected(Number(e.target.value))}>{session.observations.map((o,i)=><option key={o.timestamp} value={i}>{t(o.timestamp)} · Spot {fmt(o.spot)}</option>)}</select></div>
        <div className="legend"><span><i style={{background:palette.fixed}}/>Fixed</span><span><i style={{background:palette.moving}}/>Moving</span><span><i style={{background:palette.full}}/>Full reconstructed</span><small>Click the chart to inspect a minute</small></div><HistoricalChart observations={session.observations} selected={selected} onSelect={setSelected}/>
      </section>
      {observation&&<section className="panel"><div className="panel-heading"><div><h2>Timestamp inspector</h2><p>{t(observation.timestamp)} IST · Spot {fmt(observation.spot)} · Moving ATM {fmt(observation.moving_atm,0)}</p></div><span className="pill">{observation.provenance}</span></div>
        <div className="historical-table-scroll"><table><thead><tr><th>Strike</th><th>Call OI</th><th>Call ΔOI</th><th>Call ΔOI%</th><th>Put OI</th><th>Put ΔOI</th><th>Put ΔOI%</th><th>Strike PCR</th><th>Status</th></tr></thead><tbody>{observation.strike_results.map(row=><tr key={row.strike}><td>{fmt(row.strike,0)}</td><td>{fmt(row.call_oi,0)}</td><td>{signed(row.call_oi_change,0)}</td><td>{row.call_oi_change_pct==null?'—':`${signed(row.call_oi_change_pct,2)}%`}</td><td>{fmt(row.put_oi,0)}</td><td>{signed(row.put_oi_change,0)}</td><td>{row.put_oi_change_pct==null?'—':`${signed(row.put_oi_change_pct,2)}%`}</td><td>{row.pcr?.toFixed(3)??'—'}</td><td>{row.status}</td></tr>)}</tbody></table></div>
        <div className="panel-foot">Historical values are reconstructed from one-minute expired option candles. Missing provider values remain unavailable; they are never replaced with zero.</div>
      </section>}
    </>}
  </>
}
