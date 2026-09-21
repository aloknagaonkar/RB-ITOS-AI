import {useEffect,useMemo,useState} from 'react'
import './historicalOiResearch.css'
import HistoricalOiBuildPanel from './historicalOiBuildPanel'

type Source='CANONICAL'|'BUILT'|'ENRICHED'
type Session={session_date:string;rows:number;expiry?:string}
type Row={block?:string;source?:string;session_date:string;time:string;timestamp:string;spot:number|null;moving_atm:number|null;fixed_atm:number|null;m_ce_oi:number|null;m_pe_oi:number|null;m_ce_delta:number|null;m_pe_delta:number|null;m_ce_pct:number|null;m_pe_pct:number|null;m_activity:number|null;m_pcr_previous:number|null;m_pcr:number|null;m_pcr_change:number|null;m_common_strikes?:string;atm_ce_price_pct?:number|null;atm_pe_price_pct?:number|null;ce_state:string;pe_state:string;f_ce_delta?:number|null;f_pe_delta?:number|null;f_activity?:number|null;f_pcr:number|null;f_ce_pct?:number|null;f_pe_pct?:number|null;f_imbalance?:number|null;f_pcr_baseline?:number|null;f_pcr_change?:number|null;fixed_ce_oi_baseline_0920?:number|null;fixed_pe_oi_baseline_0920?:number|null;fixed_ce_oi?:number|null;fixed_pe_oi?:number|null;fixed_strikes?:string;fixed_complete?:boolean;moving_horizons?:Record<string,any>;forward_5m_points?:number|null;forward_10m_points?:number|null;forward_15m_points?:number|null;pattern_family:string}

const n=(v:any,d=2)=>v==null?'—':Number(v).toFixed(d)
const i=(v:any)=>v==null?'—':Number(v).toLocaleString()
const pct=(v:any)=>v==null?'—':`${Number(v)>=0?'+':''}${Number(v).toFixed(2)}%`
const signed=(v:any,d=0)=>v==null?'—':`${Number(v)>=0?'+':''}${Number(v).toFixed(d)}`
const pcrDir=(v:any)=>v==null?'—':Number(v)>0?'RISING':Number(v)<0?'FALLING':'FLAT'


type FieldState='AVAILABLE'|'DERIVED'|'SOURCE_MISSING'|'INCONSISTENT'
type ValidationItem={label:string;state:FieldState;detail:string}

const nearly=(a:any,b:any,tol=1e-6)=>{
  if(a==null||b==null)return false
  const x=Number(a),y=Number(b)
  return Number.isFinite(x)&&Number.isFinite(y)&&Math.abs(x-y)<=Math.max(tol,Math.abs(y)*1e-9)
}
const fstate=(v:any):FieldState=>v==null?'SOURCE_MISSING':'AVAILABLE'

function fixedValidation(row:Row):ValidationItem[]{
  const ceBase=row.fixed_ce_oi_baseline_0920
  const peBase=row.fixed_pe_oi_baseline_0920
  const ceNow=row.fixed_ce_oi
  const peNow=row.fixed_pe_oi
  const ceDelta=row.f_ce_delta
  const peDelta=row.f_pe_delta
  const imbalance=row.f_imbalance ?? (ceDelta!=null&&peDelta!=null?Number(peDelta)-Number(ceDelta):null)
  const basePcr=row.f_pcr_baseline ?? (ceBase!=null&&peBase!=null&&Number(ceBase)!==0?Number(peBase)/Number(ceBase):null)
  const currentPcr=row.f_pcr ?? (ceNow!=null&&peNow!=null&&Number(ceNow)!==0?Number(peNow)/Number(ceNow):null)
  const pcrChange=row.f_pcr_change ?? (basePcr!=null&&currentPcr!=null?Number(currentPcr)-Number(basePcr):null)
  const cePctExpected=ceBase!=null&&ceDelta!=null&&Number(ceBase)!==0?Number(ceDelta)/Number(ceBase)*100:null
  const pePctExpected=peBase!=null&&peDelta!=null&&Number(peBase)!==0?Number(peDelta)/Number(peBase)*100:null

  const out:ValidationItem[]=[
    {label:'Fixed strikes',state:fstate(row.fixed_strikes),detail:row.fixed_strikes?'Exact frozen 09:20 basket is present.':'Exact fixed strike identities are not present in this source.'},
    {label:'CE baseline OI',state:fstate(ceBase),detail:ceBase!=null?'09:20 CE baseline is present.':'CE baseline OI is not present in this source.'},
    {label:'PE baseline OI',state:fstate(peBase),detail:peBase!=null?'09:20 PE baseline is present.':'PE baseline OI is not present in this source.'},
    {label:'CE current OI',state:fstate(ceNow),detail:ceNow!=null?'Current fixed CE OI is present.':'Current fixed CE OI is not present in this source.'},
    {label:'PE current OI',state:fstate(peNow),detail:peNow!=null?'Current fixed PE OI is present.':'Current fixed PE OI is not present in this source.'},
  ]
  if(ceBase!=null&&ceNow!=null&&ceDelta!=null){
    out.push({label:'CE session ΔOI',state:nearly(Number(ceNow)-Number(ceBase),ceDelta)?'AVAILABLE':'INCONSISTENT',detail:`Expected ${signed(Number(ceNow)-Number(ceBase))}; source ${signed(ceDelta)}.`})
  }else out.push({label:'CE session ΔOI',state:ceDelta!=null?'AVAILABLE':'SOURCE_MISSING',detail:ceDelta!=null?'Stored ΔOI available; baseline/current pair unavailable for recomputation.':'CE session ΔOI missing.'})
  if(peBase!=null&&peNow!=null&&peDelta!=null){
    out.push({label:'PE session ΔOI',state:nearly(Number(peNow)-Number(peBase),peDelta)?'AVAILABLE':'INCONSISTENT',detail:`Expected ${signed(Number(peNow)-Number(peBase))}; source ${signed(peDelta)}.`})
  }else out.push({label:'PE session ΔOI',state:peDelta!=null?'AVAILABLE':'SOURCE_MISSING',detail:peDelta!=null?'Stored ΔOI available; baseline/current pair unavailable for recomputation.':'PE session ΔOI missing.'})

  out.push({label:'CE session %',state:row.f_ce_pct!=null?(cePctExpected==null?'AVAILABLE':nearly(row.f_ce_pct,cePctExpected)?'AVAILABLE':'INCONSISTENT'):(cePctExpected!=null?'DERIVED':'SOURCE_MISSING'),detail:row.f_ce_pct!=null?'Stored percentage available.':cePctExpected!=null?'Exactly derivable from baseline and ΔOI.':'CE baseline required.'})
  out.push({label:'PE session %',state:row.f_pe_pct!=null?(pePctExpected==null?'AVAILABLE':nearly(row.f_pe_pct,pePctExpected)?'AVAILABLE':'INCONSISTENT'):(pePctExpected!=null?'DERIVED':'SOURCE_MISSING'),detail:row.f_pe_pct!=null?'Stored percentage available.':pePctExpected!=null?'Exactly derivable from baseline and ΔOI.':'PE baseline required.'})
  out.push({label:'Session imbalance',state:row.f_imbalance!=null?'AVAILABLE':imbalance!=null?'DERIVED':'SOURCE_MISSING',detail:imbalance!=null?`PE ΔOI − CE ΔOI = ${signed(imbalance)}.`:'Both CE and PE session ΔOI required.'})
  out.push({label:'Baseline PCR',state:row.f_pcr_baseline!=null?'AVAILABLE':basePcr!=null?'DERIVED':'SOURCE_MISSING',detail:basePcr!=null?`PE baseline / CE baseline = ${n(basePcr,3)}.`:'Baseline CE and PE OI required.'})
  out.push({label:'Current PCR',state:row.f_pcr!=null?(currentPcr!=null&&nearly(row.f_pcr,currentPcr)?'AVAILABLE':'INCONSISTENT'):currentPcr!=null?'DERIVED':'SOURCE_MISSING',detail:currentPcr!=null?`PE current / CE current = ${n(currentPcr,3)}.`:'Current fixed CE and PE OI required.'})
  out.push({label:'PCR change',state:row.f_pcr_change!=null?'AVAILABLE':pcrChange!=null?'DERIVED':'SOURCE_MISSING',detail:pcrChange!=null?`Current PCR − baseline PCR = ${signed(pcrChange,3)}.`:'Baseline and current PCR required.'})
  return out
}

function movingValidation(row:Row):ValidationItem[]{
  const currentPcr=row.m_ce_oi!=null&&row.m_pe_oi!=null&&Number(row.m_ce_oi)!==0?Number(row.m_pe_oi)/Number(row.m_ce_oi):null
  const imbalance=row.m_ce_delta!=null&&row.m_pe_delta!=null?Number(row.m_pe_delta)-Number(row.m_ce_delta):null
  return [
    {label:'Current CE/PE OI',state:row.m_ce_oi!=null&&row.m_pe_oi!=null?'AVAILABLE':'SOURCE_MISSING',detail:'Both current moving-basket sides are required.'},
    {label:'Current PCR',state:row.m_pcr!=null?(currentPcr!=null&&nearly(row.m_pcr,currentPcr)?'AVAILABLE':'INCONSISTENT'):currentPcr!=null?'DERIVED':'SOURCE_MISSING',detail:currentPcr!=null?`PE / CE = ${n(currentPcr,3)}.`:'Current CE/PE OI unavailable.'},
    {label:'5m imbalance',state:imbalance!=null?'DERIVED':'SOURCE_MISSING',detail:imbalance!=null?`PE ΔOI − CE ΔOI = ${signed(imbalance)}.`:'5m CE/PE ΔOI required.'},
    {label:'5m PCR change',state:row.m_pcr_change!=null&&row.m_pcr_previous!=null&&row.m_pcr!=null?(nearly(Number(row.m_pcr)-Number(row.m_pcr_previous),row.m_pcr_change)?'AVAILABLE':'INCONSISTENT'):row.m_pcr_change!=null?'AVAILABLE':'SOURCE_MISSING',detail:'Checks current PCR minus previous same-strike PCR.'},
  ]
}

function ValidationBadge({items}:{items:ValidationItem[]}){
  const bad=items.filter(x=>x.state==='INCONSISTENT').length
  const missing=items.filter(x=>x.state==='SOURCE_MISSING').length
  const derived=items.filter(x=>x.state==='DERIVED').length
  const state=bad?'INCONSISTENT':missing?'PARTIAL':derived?'DERIVED_OK':'VALID'
  return <div className={`hoi-validation-summary hoi-validation-${state.toLowerCase()}`}><b>{state}</b><span>{items.length-bad-missing} usable · {derived} derived · {missing} source-missing · {bad} inconsistent</span></div>
}

function Audit({row}:{row:Row}){

  const fixedImbalance =
    row.f_imbalance ??
    ((row.f_pe_delta != null && row.f_ce_delta != null)
      ? Number(row.f_pe_delta) - Number(row.f_ce_delta)
      : null)

  const fixedBasePcr =
    row.f_pcr_baseline ??
    ((row.fixed_ce_oi_baseline_0920 != null &&
      row.fixed_pe_oi_baseline_0920 != null &&
      Number(row.fixed_ce_oi_baseline_0920) !== 0)
      ? Number(row.fixed_pe_oi_baseline_0920) /
        Number(row.fixed_ce_oi_baseline_0920)
      : null)

  const fixedCurrentPcr =
    row.f_pcr ??
    ((row.fixed_ce_oi != null &&
      row.fixed_pe_oi != null &&
      Number(row.fixed_ce_oi) !== 0)
      ? Number(row.fixed_pe_oi) / Number(row.fixed_ce_oi)
      : null)

  const fixedPcrChange =
    row.f_pcr_change ??
    ((fixedBasePcr != null && fixedCurrentPcr != null)
      ? Number(fixedCurrentPcr) - Number(fixedBasePcr)
      : null)

  const fixedCePct =
    row.f_ce_pct ??
    ((row.fixed_ce_oi_baseline_0920 != null &&
      row.f_ce_delta != null &&
      Number(row.fixed_ce_oi_baseline_0920) !== 0)
      ? Number(row.f_ce_delta) /
        Number(row.fixed_ce_oi_baseline_0920) * 100
      : null)

  const fixedPePct =
    row.f_pe_pct ??
    ((row.fixed_pe_oi_baseline_0920 != null &&
      row.f_pe_delta != null &&
      Number(row.fixed_pe_oi_baseline_0920) !== 0)
      ? Number(row.f_pe_delta) /
        Number(row.fixed_pe_oi_baseline_0920) * 100
      : null)

  const movingChecks=movingValidation(row)
  const fixedChecks=fixedValidation(row)

 const imbalance=(row.m_pe_delta==null||row.m_ce_delta==null)?null:row.m_pe_delta-row.m_ce_delta
 return <div className="hoi-audit">
  <div className="hoi-audit-title">{row.time} checkpoint audit · {row.source||row.block||'CANONICAL'}</div>
  <div className="hoi-audit-grid">
   <section><h4>Checkpoint context</h4><div><span>Timestamp</span><b>{row.timestamp}</b></div><div><span>Spot</span><b>{n(row.spot)}</b></div><div><span>Moving ATM</span><b>{n(row.moving_atm,0)}</b></div><div><span>Fixed ATM</span><b>{n(row.fixed_atm,0)}</b></div></section>
   <section><h4>Moving ATM OI</h4><ValidationBadge items={movingChecks}/><div><span>CE OI</span><b>{i(row.m_ce_oi)}</b></div><div><span>PE OI</span><b>{i(row.m_pe_oi)}</b></div><div><span>CE ΔOI</span><b>{signed(row.m_ce_delta)}</b></div><div><span>PE ΔOI</span><b>{signed(row.m_pe_delta)}</b></div><div><span>CE OI % change</span><b>{pct(row.m_ce_pct)}</b></div><div><span>PE OI % change</span><b>{pct(row.m_pe_pct)}</b></div><div><span>PE ΔOI − CE ΔOI</span><b>{signed(imbalance)}</b></div><div><span>Activity</span><b>{i(row.m_activity)}</b></div><div><span>Common strikes</span><b>{row.m_common_strikes||'—'}</b></div></section>
   <section><h4>PCR</h4><div><span>Previous PCR</span><b>{n(row.m_pcr_previous,3)}</b></div><div><span>Current PCR</span><b>{n(row.m_pcr,3)}</b></div><div><span>PCR change</span><b>{signed(row.m_pcr_change,3)}</b></div><div><span>PCR direction</span><b>{pcrDir(row.m_pcr_change)}</b></div></section>
   <section><h4>Moving same-strike 5m / 10m / 15m</h4>{[5,10,15].map(h=>{const x=row.moving_horizons?.[String(h)];return <div key={h} className="hoi-horizon-line"><span>{h}m</span><b>CE {signed(x?.ce_delta)} ({pct(x?.ce_pct)}) · PE {signed(x?.pe_delta)} ({pct(x?.pe_pct)}) · IMB {signed(x?.imbalance)} · PCR {n(x?.prior_pcr,3)} → {n(x?.current_pcr,3)} ({signed(x?.pcr_change,3)})</b></div>})}</section><section><h4>Positioning</h4><div><span>CE state (ATM)</span><b>{row.ce_state||'—'}</b></div><div><span>PE state (ATM)</span><b>{row.pe_state||'—'}</b></div><div><span>ATM CE premium %</span><b>{pct(row.atm_ce_price_pct)}</b></div><div><span>ATM PE premium %</span><b>{pct(row.atm_pe_price_pct)}</b></div><div><span>Pattern</span><b>{row.pattern_family||'—'}</b></div></section>
   <section><h4>Fixed 09:20 ATM ±5</h4><ValidationBadge items={fixedChecks}/><div><span>Fixed strikes</span><b>{row.fixed_strikes||'—'}</b></div><div><span>CE baseline OI</span><b>{i(row.fixed_ce_oi_baseline_0920)}</b></div><div><span>PE baseline OI</span><b>{i(row.fixed_pe_oi_baseline_0920)}</b></div><div><span>CE current OI</span><b>{i(row.fixed_ce_oi)}</b></div><div><span>PE current OI</span><b>{i(row.fixed_pe_oi)}</b></div><div><span>CE session ΔOI</span><b>{signed(row.f_ce_delta)}</b></div><div><span>PE session ΔOI</span><b>{signed(row.f_pe_delta)}</b></div><div><span>CE session %</span><b>{pct(fixedCePct)}</b></div><div><span>PE session %</span><b>{pct(fixedPePct)}</b></div><div><span>Session imbalance</span><b>{signed(fixedImbalance)}</b></div><div><span>Baseline PCR</span><b>{n(fixedBasePcr,3)}</b></div><div><span>Current PCR</span><b>{n(fixedCurrentPcr,3)}</b></div><div><span>PCR change</span><b>{signed(fixedPcrChange,3)}</b></div></section>
   <section><h4>Forward research context</h4><div><span>NIFTY +5m</span><b>{signed(row.forward_5m_points,2)} pts</b></div><div><span>NIFTY +10m</span><b>{signed(row.forward_10m_points,2)} pts</b></div><div><span>NIFTY +15m</span><b>{signed(row.forward_15m_points,2)} pts</b></div></section>
  </div>
  <div className="hoi-validation-details"><details><summary>Calculation/data validation</summary><div className="hoi-validation-list">{[...movingChecks,...fixedChecks].map((x,idx)=><div key={`${x.label}-${idx}`} className={`hoi-validation-row hoi-v-${x.state.toLowerCase()}`}><span>{x.label}</span><b>{x.state}</b><p>{x.detail}</p></div>)}</div></details></div>
    <p className="hoi-audit-note">Forward returns are retrospective research labels and are not inputs to checkpoint classification.</p>
 </div>
}

export default function HistoricalOiResearch(){
 const [source,setSource]=useState<Source>('CANONICAL')
 const [sessions,setSessions]=useState<Session[]>([])
 const [selected,setSelected]=useState('')
 const [rows,setRows]=useState<Row[]>([])
 const [loading,setLoading]=useState(false)
 const [error,setError]=useState('')
 const [expanded,setExpanded]=useState<string|null>(null)

 const sessionsUrl=source==='CANONICAL'?'/api/live-shadow/replay-ops/historical-oi/sessions':source==='ENRICHED'?'/api/live-shadow/replay-ops/historical-oi/enriched/sessions':'/api/live-shadow/replay-ops/historical-oi/built/sessions'
 const detailUrl=source==='CANONICAL'?'/api/live-shadow/replay-ops/historical-oi/session':source==='ENRICHED'?'/api/live-shadow/replay-ops/historical-oi/enriched/rows':'/api/live-shadow/replay-ops/historical-oi/built/session'

 const reload=async()=>{
  const r=await fetch(sessionsUrl);const v=await r.json().catch(()=>({}))
  if(!r.ok)throw new Error(v?.detail||'Historical OI sessions unavailable')
  const s:Session[]=v.sessions||[];setSessions(s);setSelected(cur=>s.some(x=>x.session_date===cur)?cur:(s[0]?.session_date||''))
 }
 useEffect(()=>{setError('');void reload().catch(e=>setError(String(e)))},[source])
 useEffect(()=>{
  if(!selected){setRows([]);return}
  setExpanded(null);setLoading(true);setError('')
  fetch(source==='ENRICHED'?`${detailUrl}?date=${encodeURIComponent(selected)}`:`${detailUrl}?session_date=${encodeURIComponent(selected)}`).then(async r=>{const v=await r.json().catch(()=>({}));if(!r.ok)throw new Error(v?.detail||'Historical OI session unavailable');return v}).then(v=>setRows(v.rows||[])).catch(e=>setError(String(e))).finally(()=>setLoading(false))
 },[selected,source])

 const summary=useMemo(()=>rows.length?{count:rows.length,lastTime:rows[rows.length-1].time,lastPcr:rows[rows.length-1].m_pcr}:null,[rows])

 return <section className="hoi">
  <HistoricalOiBuildPanel/>
  <div className="hoi-head"><div><h3>Historical OI research</h3><p>Canonical research and newly built dates stay separate.</p></div>
   <div className="hoi-source-controls">
    <label>Source<select value={source} onChange={e=>{setSource(e.target.value as Source);setSelected('')}}><option value="CANONICAL">Canonical 90-session</option><option value="BUILT">Newly built dates</option><option value="ENRICHED">Enriched</option></select></label>
    <label>Date<select value={selected} onChange={e=>setSelected(e.target.value)}>{sessions.map(s=><option key={s.session_date} value={s.session_date}>{s.session_date}{s.expiry?` → ${s.expiry}`:''} ({s.rows})</option>)}</select></label>
    <button onClick={()=>void reload().catch(e=>setError(String(e)))}>Refresh dates</button>
   </div>
  </div>
  {error&&<div className="hoi-error">{error}</div>}
  <div className="hoi-cards"><div><span>Source</span><b>{source==='CANONICAL'?'90-session canonical':source==='ENRICHED'?'Enriched':'Newly built'}</b></div><div><span>Sessions</span><b>{sessions.length||'—'}</b></div><div><span>Rows this day</span><b>{summary?.count??'—'}</b></div><div><span>Last checkpoint</span><b>{summary?.lastTime??'—'}</b></div><div><span>Last moving PCR</span><b>{n(summary?.lastPcr,3)}</b></div></div>
  <div className="hoi-table-wrap"><table className="hoi-table"><thead><tr><th>Time</th><th>Spot</th><th>ATM</th><th>PCR</th><th>PCR Δ</th><th>CE state</th><th>PE state</th><th>Pattern</th><th>Details</th></tr></thead><tbody>
   {rows.map((r,idx)=>{const key=r.timestamp||`${r.time}-${idx}`,open=expanded===key;return <><tr key={key}><td>{r.time}</td><td>{n(r.spot)}</td><td>{n(r.moving_atm,0)}</td><td>{n(r.m_pcr,3)}</td><td>{signed(r.m_pcr_change,3)}</td><td>{r.ce_state||'—'}</td><td>{r.pe_state||'—'}</td><td>{r.pattern_family||'—'}</td><td><button onClick={()=>setExpanded(open?null:key)}>{open?'Hide':'Audit'}</button></td></tr>{open&&<tr key={`${key}-a`}><td colSpan={9}><Audit row={r}/></td></tr>}</>})}
   {!loading&&!rows.length&&<tr><td colSpan={9}>No historical OI rows for this source/date.</td></tr>}
  </tbody></table></div>
  {source==='BUILT'&&<p className="hoi-note">Built dates are converted from isolated per-strike sidecar data and do not modify the frozen canonical 90-session dataset. CE/PE positioning state is the exact ATM strike's 5-minute state.</p>}
  {source==='ENRICHED'&&<p className="hoi-note">Enriched dates combine exact downloaded historical positioning with fixed 09:20 ATM ±5 and moving same-strike calculations. The frozen canonical dataset is not modified.</p>}
  {source==='ENRICHED'&&<p className="hoi-note">Enriched dates combine exact downloaded historical positioning with fixed 09:20 ATM ±5 and moving same-strike calculations. The frozen canonical dataset is not modified.</p>}
 </section>
}
