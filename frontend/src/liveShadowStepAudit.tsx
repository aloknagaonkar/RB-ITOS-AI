import { useEffect, useState } from 'react'

type StepAuditRow = {
  sequence:number
  event_time:string
  checkpoint:string|null
  observation_id:string|null
  stage:string
  status:string
  payload:Record<string,any>
}
type StepAuditResponse = { chain_ok:boolean; chain_issue:string|null; rows:StepAuditRow[] }

const words=(v:string|null|undefined)=>v ? v.replaceAll('_',' ') : '—'
const tm=(v:string|null|undefined)=>v?new Date(v).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const num=(v:any,d=2)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:d})
const pcrchg=(v:any)=>v==null?'—':`${Number(v)>=0?'+':''}${Number(v).toFixed(4)}`

function Badge({value}:{value:string}) {
  const x=value.toLowerCase()
  const good=['healthy','allowed','calculated','selected','available','detected','open','closed','classified','resolved']
  const bad=['failed','missing','blocked','incomplete','rejected','unhealthy','stale','out of order']
  const cls=good.some(k=>x.includes(k))?'good':bad.some(k=>x.includes(k))?'bad':'neutral'
  return <span className={`step-badge ${cls}`}>{words(value)}</span>
}

export default function LiveShadowStepAudit() {
  const [data,setData]=useState<StepAuditResponse>({chain_ok:true,chain_issue:null,rows:[]})
  const [expanded,setExpanded]=useState<number|null>(null)
  useEffect(()=>{
    let active=true
    const poll=()=>fetch('/api/live-shadow/step-audit?limit=300').then(r=>r.json()).then(v=>{if(active)setData(v)}).catch(()=>{})
    poll(); const timer=setInterval(poll,3000)
    return()=>{active=false;clearInterval(timer)}
  },[])
  const latest=data.rows.find(r=>r.stage==='NORMALIZED_FEATURES')
  return <section className="panel shadow-panel step-audit-panel">
    <div className="panel-heading">
      <div><h2>Live reasoning & step audit</h2><p>Every checkpoint and decision, including no-trade decisions.</p></div>
      <Badge value={data.chain_ok?'AUDIT HEALTHY':'AUDIT BROKEN'}/>
    </div>
    {latest && <div className="checkpoint-reasoning">
      <div className="checkpoint-title">
        <b>Latest checkpoint {tm(latest.checkpoint)}</b>
        <span>Spot {num(latest.payload.spot)}</span>
        <span>ATM {num(latest.payload.moving_atm,0)}</span>
        <Badge value={String(latest.payload.all3_state??'UNKNOWN')}/>
      </div>
      <div className="horizon-grid">
        {['5m','10m','15m'].map(h=>{
          const x=latest.payload.horizons?.[h]??{}
          return <article key={h}>
            <div><strong>{h}</strong><Badge value={String(x.state??'NA')}/></div>
            <dl>
              <div><dt>CE Δ</dt><dd>{num(x.ce_delta,0)}</dd></div>
              <div><dt>PE Δ</dt><dd>{num(x.pe_delta,0)}</dd></div>
              <div><dt>Imalance</dt><dd>{num(x.imbalance,0)}</dd></div>
              <div><dt>PCR</dt><dd>{num(x.current_pcr,4)}</dd></div>
              <div><dt>PCR Δ</dt><dd>{pcrchg(x.pcr_change)}</dd></div>
            </dl>
          </article>
        })}
      </div>
    </div>}
    {!data.rows.length?<div className="empty">No step-audit records yet.</div>:
    <div className="step-table-wrap"><table className="shadow-table step-table">
      <thead><tr><th>#</th><th>Time</th><th>Checkpoint</th><th>Step</th><th>Status</th><th>Observation</th><th>Audit</th></tr></thead>
      <tbody>{data.rows.map(r=><>
        <tr key={`r-${r.sequence}`} onClick={()=>setExpanded(expanded===r.sequence?null:r.sequence)}>
          <td>{r.sequence}</td><td>{tm(r.event_time)}</td><td>{tm(r.checkpoint)}</td><td>{words(r.stage)}</td><td><Badge value={r.status}/></td><td className="mono">{r.observation_id??'—'}</td><td>{expanded===r.sequence?'Hide':'Details'}</td>
        </tr>
        {expanded===r.sequence&&<tr key={`d-${r.sequence}`} className="step-detail-row"><td colSpan={7}><pre>{JSON.stringify(r.payload,null,2)}</pre></td></tr>}
      </>)}</tbody>
    </table></div>}
  </section>
}
