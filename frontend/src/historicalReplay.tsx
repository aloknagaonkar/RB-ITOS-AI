import { useEffect, useMemo, useState } from 'react'
import './historicalReplay.css'
import HistoricalReplayOperations from './historicalReplayOperations'
import HilegaHistoricalReplay from './hilegaHistoricalReplay'
import HistoricalOiResearch from './historicalOiResearch'
import HistoricalReplayInventory from './historicalReplayInventory'

type Session = {
  session_date:string
  status:string
  checkpoint_count?:number|null
  processed_checkpoint_count?:number|null
  missing_checkpoint_count?:number|null
  observation_count?:number|null
  state_counts?:Record<string,number>
  step_audit_chain_ok?:boolean|null
}

type AuditRow = {
  checkpoint:string|null
  event_time:string
  observation_id:string|null
  stage:string
  status:string
  payload:Record<string,any>
}

type TimelineRow = {
  checkpoint:string
  snapshot_selection:AuditRow|null
  normalized_features:AuditRow|null
  data_health:AuditRow|null
  all3_decision:AuditRow|null
  candidate_detection:AuditRow|null
  candidate_steps:AuditRow[]
  observation_ids:string[]
  observation_events:Record<string,any[]>
  summary:{
    spot:number|null
    moving_atm:number|null
    state_5m:string|null
    state_10m:string|null
    state_15m:string|null
    all3_state:string|null
    candidate:string|null
    health:string|null
  }
}

const shortTime=(value?:string|null)=>{
  if(!value) return '—'
  const d=new Date(value)
  return Number.isNaN(d.getTime()) ? value.slice(11,16) : d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',hour12:false})
}

const n=(value:any,digits=2)=>value==null?'—':Number(value).toFixed(digits)

const isoDate=(d:Date)=>[
  d.getFullYear(),
  String(d.getMonth()+1).padStart(2,'0'),
  String(d.getDate()).padStart(2,'0'),
].join('-')

function recentPresetDates(days=45){
  const rows:string[]=[]
  const d=new Date()
  d.setHours(12,0,0,0)
  for(let i=0;i<days;i++){
    const day=d.getDay()
    if(day!==0 && day!==6) rows.push(isoDate(d))
    d.setDate(d.getDate()-1)
  }
  return rows
}

function badge(value?:string|null){
  const text=value||'—'
  const key=text.toLowerCase().replaceAll('_','-')
  return <span className={`hr-badge hr-${key}`}>{text}</span>
}

function Horizon({name,data}:{name:string,data:any}){
  if(!data) return <div className="hr-horizon"><b>{name}</b><span>Unavailable</span></div>
  return <div className="hr-horizon">
    <b>{name} {badge(data.state)}</b>
    <span>CE Δ {n(data.ce_delta,0)}</span>
    <span>PE Δ {n(data.pe_delta,0)}</span>
    <span>Imbalance {n(data.imbalance,0)}</span>
    <span>PCR {n(data.prior_pcr,4)} → {n(data.current_pcr,4)}</span>
    <span>PCR Δ {n(data.pcr_change,4)}</span>
  </div>
}

type ProgressItem = {
  timestamp:string
  source:'AUDIT'|'EVENT'
  stage:string
  status:string
  observation_id:string
  detail:string
  payload:Record<string,any>
  sort_order:number
  display_result?:string
  reason?:string
  next_action?:string
  terminal?:boolean
}

const eventOrder:Record<string,number> = {
  OBSERVATION_DETECTED:10,
  CANDLE2_CONFIRMED:20,
  FUTURES_ALIGNMENT_CHECKED:30,
  SPOT_LAG_CLASSIFIED:40,
  OPTION_RESOLVED:50,
  ENTRY_OPEN:60,
  ENTRY_OPENED:61,
  OPTION_MINUTE_HEALTH:70,
  OPTION_MINUTE:71,
  RISK_STATE_UPDATED:72,
  TRADE_CLOSED:90,
}

function firstValue(payload:Record<string,any>, keys:string[]){
  for(const key of keys){
    const value=payload?.[key]
    if(value!==undefined && value!==null && value!=='') return value
  }
  return null
}

function pct(value:any){
  if(value===undefined || value===null || value==='') return null
  const num=Number(value)
  if(Number.isNaN(num)) return String(value)
  return `${num>=0?'+':''}${num.toFixed(2)}%`
}

function money(value:any){
  if(value===undefined || value===null || value==='') return null
  const num=Number(value)
  return Number.isNaN(num) ? String(value) : num.toFixed(2)
}

function eventDetail(stage:string,payload:Record<string,any>){
  const p=payload||{}
  const parts:string[]=[]

  if(stage==='OBSERVATION_DETECTED'){
    const direction=firstValue(p,['direction','target_direction'])
    if(direction) parts.push(String(direction))
  }

  if(stage==='CANDLE2_CONFIRMED'){
    const spot=firstValue(p,['spot','spot_c2','candle2_spot'])
    if(spot!=null) parts.push(`spot ${money(spot)}`)
  }

  if(stage==='FUTURES_ALIGNMENT_CHECKED'){
    const state=firstValue(p,['futures_oi_state','state'])
    const aligned=firstValue(p,['aligned','is_aligned'])
    if(state) parts.push(String(state))
    if(aligned!==null) parts.push(`aligned ${aligned?'YES':'NO'}`)
  }

  if(stage==='SPOT_LAG_CLASSIFIED'){
    const classification=firstValue(p,['classification','spot_classification','spot_class'])
    if(classification) parts.push(String(classification))
  }

  if(stage==='OPTION_RESOLVED'){
    const atm=firstValue(p,['atm_strike','moving_atm','strike'])
    const side=firstValue(p,['option_side','side'])
    const key=firstValue(p,['option_instrument_key','instrument_key'])
    if(atm!=null || side) parts.push(`${atm??''} ${side??''}`.trim())
    if(key) parts.push(String(key))
  }

  if(stage==='ENTRY_OPEN' || stage==='ENTRY_OPENED'){
    const price=firstValue(p,['entry_price','price','open'])
    const key=firstValue(p,['option_instrument_key','instrument_key'])
    if(price!=null) parts.push(`entry ${money(price)}`)
    if(key) parts.push(String(key))
  }

  if(stage==='OPTION_MINUTE'){
    const o=firstValue(p,['open'])
    const h=firstValue(p,['high'])
    const l=firstValue(p,['low'])
    const c=firstValue(p,['close'])
    if([o,h,l,c].some(v=>v!=null)){
      parts.push(`O ${money(o)} H ${money(h)} L ${money(l)} C ${money(c)}`)
    }
  }

  if(stage==='OPTION_MINUTE_HEALTH'){
    const reason=firstValue(p,['reason','health_reason'])
    if(reason) parts.push(String(reason))
  }

  if(stage==='RISK_STATE_UPDATED'){
    const stop=firstValue(p,['active_stop','stop_price','stop'])
    const be=firstValue(p,['breakeven_armed','be_armed','breakeven_active'])
    const trail=firstValue(p,['trail_armed','trailing_armed','trail_active'])
    const mfe=firstValue(p,['mfe_pct','mfe_pct_points','mfe'])
    const mae=firstValue(p,['mae_pct','mae_pct_points','mae'])
    if(stop!=null) parts.push(`stop ${money(stop)}`)
    if(be!==null) parts.push(`BE ${be?'ON':'OFF'}`)
    if(trail!==null) parts.push(`trail ${trail?'ON':'OFF'}`)
    if(mfe!=null) parts.push(`MFE ${pct(mfe)}`)
    if(mae!=null) parts.push(`MAE ${pct(mae)}`)
  }

  if(stage==='TRADE_CLOSED'){
    const reason=firstValue(p,['exit_reason','reason'])
    const exit=firstValue(p,['exit_price','price'])
    const gross=firstValue(p,['gross_return_pct','gross_pct','gross_return'])
    const net=firstValue(p,['net_return_pct','net_pct','net_return'])
    const mfe=firstValue(p,['mfe_pct','mfe_pct_points','mfe'])
    const mae=firstValue(p,['mae_pct','mae_pct_points','mae'])
    if(reason) parts.push(String(reason))
    if(exit!=null) parts.push(`exit ${money(exit)}`)
    if(gross!=null) parts.push(`gross ${pct(gross)}`)
    if(net!=null) parts.push(`net ${pct(net)}`)
    if(mfe!=null) parts.push(`MFE ${pct(mfe)}`)
    if(mae!=null) parts.push(`MAE ${pct(mae)}`)
  }

  return parts.join(' · ')
}


function directionFromObservationId(observationId:string){
  if(observationId.includes('-BULLISH-')) return 'BULLISH'
  if(observationId.includes('-BEARISH-')) return 'BEARISH'
  return null
}

function futuresRequirement(direction:string|null){
  if(direction==='BULLISH') return 'LONG_BUILDUP or SHORT_COVERING'
  if(direction==='BEARISH') return 'SHORT_BUILDUP or LONG_UNWINDING'
  return 'direction-aligned futures state'
}

function normalizeResult(stage:string,status:string){
  if(stage==='C2_ELIGIBILITY' && status==='DUE') return 'ELIGIBLE'
  if(stage==='CANDLE2_CONFIRMED') return 'PASS'
  if(stage==='FUTURES_FETCH' && status==='AVAILABLE') return 'PASS'
  if(stage==='OPTION_RESOLVED') return 'PASS'
  if(stage==='ENTRY_OPEN' || stage==='ENTRY_OPENED') return 'OPEN'
  if(stage==='TRADE_CLOSED') return 'CLOSED'
  return status||'—'
}

function explainProgressItem(item:ProgressItem):ProgressItem{
  const p=item.payload||{}
  const direction=firstValue(p,['direction','target_direction']) || directionFromObservationId(item.observation_id)
  const futuresState=firstValue(p,['futures_oi_state','state'])
  const aligned=firstValue(p,['aligned','is_aligned'])

  let reason=''
  let nextAction=''
  let terminal=false

  switch(item.stage){
    case 'OBSERVATION_DETECTED':
      reason=`New ${direction||'directional'} ALL3 reversal candidate detected.`
      nextAction='Wait for the exact +5 minute C2 checkpoint.'
      break
    case 'C2_ELIGIBILITY':
      if(item.status==='DUE' || item.status==='ELIGIBLE'){
        reason='The required C2 checkpoint has been reached at exactly C1 + 5 minutes.'
        nextAction='Evaluate whether the same ALL3 direction survives at C2.'
      }else{
        reason=firstValue(p,['reason']) || `C2 eligibility status is ${item.status||'unknown'}.`
        nextAction='Do not advance until C2 timing requirements are satisfied.'
      }
      break
    case 'CANDLE2_CONFIRMED':
      reason=`The ${direction||'candidate'} ALL3 direction remained confirmed at C2.`
      nextAction='Fetch and evaluate completed futures OI at the same checkpoint.'
      break
    case 'FUTURES_FETCH':
      if(item.status==='AVAILABLE'){
        reason='Exact completed futures OI data is available for the confirmation checkpoint.'
        nextAction='Check whether the futures state supports the candidate direction.'
      }else{
        reason=firstValue(p,['reason']) || 'Required futures data is unavailable.'
        nextAction='Stop the candidate because futures confirmation cannot be evaluated.'
        terminal=true
      }
      break
    case 'FUTURES_ALIGNMENT_CHECKED':
      if(aligned===false || item.status==='MISALIGNED' || item.status==='REJECTED' || item.status==='FAIL'){
        reason=`Candidate=${direction||'UNKNOWN'} but futures=${futuresState||'UNKNOWN'}. ${direction||'This direction'} requires ${futuresRequirement(direction)}.`
        nextAction='Reject candidate. Do not resolve an option or open an entry.'
        terminal=true
      }else if(aligned===true || item.status==='ALIGNED' || item.status==='PASS'){
        reason=`Futures=${futuresState||'aligned state'} supports the ${direction||'candidate'} direction.`
        nextAction='Classify spot movement and continue to exact option resolution.'
      }else{
        reason=`Observed futures state: ${futuresState||'unknown'}. Required for ${direction||'candidate'}: ${futuresRequirement(direction)}.`
        nextAction='Use the recorded C2 decision to determine whether the candidate continues.'
      }
      break
    case 'C2_DECISION':
      if(item.status==='REJECTED'){
        reason=firstValue(p,['reason','rejection_reason']) ||
          `C2 candidate rejected. For ${direction||'this candidate'}, the futures confirmation did not satisfy ${futuresRequirement(direction)}.`
        nextAction='Strategy stops here. Option resolution and entry are not attempted.'
        terminal=true
      }else{
        reason=firstValue(p,['reason']) || `C2 decision=${item.status||'unknown'}.`
        nextAction='Follow the recorded C2 decision.'
      }
      break
    case 'SPOT_LAG_CLASSIFIED': {
      const classification=firstValue(p,['classification','spot_classification','spot_class'])
      reason=`Spot movement classified as ${classification||'recorded classification'} using C1 versus C2 spot.`
      nextAction='Resolve the exact ATM CE/PE for the confirmed direction.'
      break
    }
    case 'OPTION_RESOLVED':
      reason='Exact ATM option instrument resolved with no nearest-strike fallback.'
      nextAction='Wait for the exact next 1-minute candle open.'
      break
    case 'ENTRY_OPEN':
    case 'ENTRY_OPENED':
      reason='Exact next-minute option open is available and used as the hypothetical entry.'
      nextAction='Process each completed 1-minute option candle through stop/BE/trailing/time-exit logic.'
      break
    case 'OPTION_MINUTE_HEALTH':
      if(item.status==='ALLOWED' || item.status==='HEALTHY'){
        reason='Option minute passed data-health checks.'
        nextAction='Evaluate this completed minute against the active risk state.'
      }else{
        reason=firstValue(p,['reason','health_reason']) || 'Option minute failed data-health checks.'
        nextAction='Stop/incomplete the observation according to fail-closed rules.'
        terminal=true
      }
      break
    case 'OPTION_MINUTE':
      reason=item.status==='CLOSED'
        ? 'This completed minute triggered a terminal exit condition.'
        : 'Completed option minute evaluated against the current stop, breakeven and trailing state.'
      nextAction=item.status==='CLOSED'
        ? 'Record the terminal trade event.'
        : 'Continue to the next completed option minute unless another exit condition fires.'
      break
    case 'RISK_STATE_UPDATED':
      reason='Risk state recalculated from the completed option minute using the frozen stop/BE/trailing rules.'
      nextAction='Continue to the next completed option minute or close if an exit condition is met.'
      break
    case 'TRADE_CLOSED': {
      const reasonCode=firstValue(p,['exit_reason','reason'])
      reason=`Trade closed${reasonCode?` because ${reasonCode}`:''}.`
      nextAction='Terminal state reached; no further option minutes are processed for this observation.'
      terminal=true
      break
    }
    default:
      reason=firstValue(p,['reason','message']) || ''
      nextAction=''
  }

  return {
    ...item,
    display_result:normalizeResult(item.stage,item.status),
    reason,
    next_action:nextAction,
    terminal,
  }
}

function terminalExplanation(progress:ProgressItem[]){
  const terminal=[...progress].reverse().find(x=>x.terminal)
  if(!terminal) return null
  const direction=directionFromObservationId(terminal.observation_id)
  const futuresItem=progress.find(x=>x.stage==='FUTURES_ALIGNMENT_CHECKED')
  const futuresState=futuresItem ? firstValue(futuresItem.payload,['futures_oi_state','state']) : null
  return {
    title: terminal.stage==='TRADE_CLOSED' ? 'TRADE CLOSED' :
           terminal.stage==='C2_DECISION' || terminal.stage==='FUTURES_ALIGNMENT_CHECKED' ? 'CANDIDATE REJECTED' :
           'STRATEGY STOPPED',
    stopped_at:terminal.stage,
    result:terminal.display_result||terminal.status,
    direction,
    futures_state:futuresState,
    required_futures:direction ? futuresRequirement(direction) : null,
    reason:terminal.reason,
    next_action:terminal.next_action,
  }
}

function buildProgress(row:TimelineRow):ProgressItem[]{
  const items:ProgressItem[]=[]

  for(const step of row.candidate_steps||[]){
    items.push({
      timestamp:step.event_time || step.checkpoint || row.checkpoint,
      source:'AUDIT',
      stage:step.stage,
      status:step.status||'',
      observation_id:step.observation_id||'',
      detail:eventDetail(step.stage,step.payload||{}),
      payload:step.payload||{},
      sort_order:eventOrder[step.stage]??55,
    })
  }

  for(const [oid,events] of Object.entries(row.observation_events||{})){
    for(const event of events||[]){
      const stage=event.event_type||'EVENT'
      items.push({
        timestamp:event.event_time || event.timestamp || row.checkpoint,
        source:'EVENT',
        stage,
        status:event.state || event.status || '',
        observation_id:oid,
        detail:eventDetail(stage,event.payload||{}),
        payload:event.payload||{},
        sort_order:eventOrder[stage]??56,
      })
    }
  }

  return items.sort((a,b)=>{
    const ta=Date.parse(a.timestamp)
    const tb=Date.parse(b.timestamp)
    if(Number.isFinite(ta) && Number.isFinite(tb) && ta!==tb) return ta-tb
    if(a.timestamp!==b.timestamp) return a.timestamp.localeCompare(b.timestamp)
    if(a.sort_order!==b.sort_order) return a.sort_order-b.sort_order
    return a.source.localeCompare(b.source)
  }).map(explainProgressItem)
}

function TradeSummary({progress}:{progress:ProgressItem[]}){
  const option=progress.find(x=>x.stage==='OPTION_RESOLVED')
  const entry=[...progress].reverse().find(x=>x.stage==='ENTRY_OPENED' || x.stage==='ENTRY_OPEN')
  const futures=progress.find(x=>x.stage==='FUTURES_ALIGNMENT_CHECKED')
  const spot=progress.find(x=>x.stage==='SPOT_LAG_CLASSIFIED')
  const closed=[...progress].reverse().find(x=>x.stage==='TRADE_CLOSED')

  if(!option && !entry && !futures && !spot && !closed) return null

  const fields:{label:string,value:string|null}[]=[
    {label:'Futures',value:futures?.detail||null},
    {label:'Spot class',value:spot?.detail||null},
    {label:'Option',value:option?.detail||null},
    {label:'Entry',value:entry?.detail||null},
    {label:'Exit',value:closed?.detail||null},
  ]

  return <div className="hr-trade-summary">
    {fields.filter(x=>x.value).map(field=><div key={field.label}>
      <b>{field.label}</b>
      <span>{field.value}</span>
    </div>)}
  </div>
}


function TerminalPanel({progress}:{progress:ProgressItem[]}){
  const terminal=terminalExplanation(progress)
  if(!terminal) return null

  return <div className={`hr-terminal ${terminal.title==='CANDIDATE REJECTED'?'hr-terminal-rejected':'hr-terminal-closed'}`}>
    <div className="hr-terminal-title">{terminal.title}</div>
    <div className="hr-terminal-grid">
      <div><b>Stopped at</b><span>{terminal.stopped_at}</span></div>
      <div><b>Result</b><span>{terminal.result}</span></div>
      {terminal.direction&&<div><b>Candidate</b><span>{terminal.direction}</span></div>}
      {terminal.futures_state&&<div><b>Futures</b><span>{String(terminal.futures_state)}</span></div>}
      {terminal.required_futures&&<div><b>Required futures</b><span>{terminal.required_futures}</span></div>}
      <div className="hr-terminal-wide"><b>Reason</b><span>{terminal.reason}</span></div>
      <div className="hr-terminal-wide"><b>Next action</b><span>{terminal.next_action}</span></div>
    </div>
  </div>
}


type DecisionGate={
  id:string
  stage:string
  required:boolean
  result:'PASS'|'FAIL'|'INFO'|'INCOMPLETE'|'WAIT'|'NOT_APPLICABLE'
  expected:string
  actual:string
  reason:string
}

function gateResultFromStatus(status?:string|null):DecisionGate['result']{
  const s=(status||'').toUpperCase()
  if(['PASS','ALLOWED','AVAILABLE','ALIGNED','CONFIRMED','CLASSIFIED','RESOLVED','OPEN','OPENED','DUE','ELIGIBLE'].includes(s)) return 'PASS'
  if(['FAIL','FAILED','REJECTED','MISALIGNED','BLOCKED','MISSING'].includes(s)) return 'FAIL'
  if(['INCOMPLETE','UNAVAILABLE','STALE','OUT_OF_ORDER'].includes(s)) return 'INCOMPLETE'
  return 'WAIT'
}

function progressItem(progress:ProgressItem[],...stages:string[]){
  return progress.find(x=>stages.includes(x.stage))
}

function buildDecisionGates(row:TimelineRow,progress:ProgressItem[]):DecisionGate[]{
  const f=row.normalized_features?.payload||{}
  const horizons=f.horizons||{}
  const all3=(row.all3_decision?.status||f.all3_state||'').toUpperCase()
  const candidate=(row.candidate_detection?.status||'').toUpperCase()
  const direction=all3.startsWith('BULLISH')?'BULLISH':all3.startsWith('BEARISH')?'BEARISH':null

  const health=row.data_health
  const c2Eligibility=progressItem(progress,'C2_ELIGIBILITY')
  const c2Confirmed=progressItem(progress,'CANDLE2_CONFIRMED')
  const c2Decision=progressItem(progress,'C2_DECISION')
  const futuresFetch=progressItem(progress,'FUTURES_FETCH')
  const futuresAlign=progressItem(progress,'FUTURES_ALIGNMENT_CHECKED')
  const spotClass=progressItem(progress,'SPOT_LAG_CLASSIFIED')
  const option=progressItem(progress,'OPTION_RESOLVED','OPTION_RESOLUTION')
  const entry=progressItem(progress,'ENTRY_OPENED','ENTRY_OPEN')

  const gates:DecisionGate[]=[]

  gates.push({
    id:'DATA_HEALTH',stage:'Data health',required:true,
    result:health?.status==='ALLOWED'?'PASS':health?gateResultFromStatus(health.status):'INCOMPLETE',
    expected:'Checkpoint market data must be usable.',
    actual:health?.status||'No health result',
    reason:health?.payload?.health_reason || (health?.status==='ALLOWED'?'Required market data passed the health gate.':'Required market data did not pass the health gate.'),
  })

  const h=(name:string)=>{
    const x=horizons[name]||{}
    const state=x.state||x.direction||x.result||f[`state_${name}`]||'—'
    const imbalance=x.imbalance ?? x.oi_imbalance ?? null
    const pcrChange=x.pcr_change ?? x.regular_pcr_change ?? null
    return `${state} | imbalance=${imbalance==null?'—':n(imbalance,0)} | PCR Δ=${pcrChange==null?'—':n(pcrChange,3)}`
  }

  const all3Directional=all3==='BULLISH_ALL_3'||all3==='BEARISH_ALL_3'
  gates.push({
    id:'C1_ALL3',stage:'C1 ALL3 detection',required:true,
    result:all3Directional?'PASS':'FAIL',
    expected:'5m, 10m and 15m must agree as BULLISH or BEARISH.',
    actual:`5m ${h('5m')} ; 10m ${h('10m')} ; 15m ${h('15m')} ; ALL3=${all3||'—'}`,
    reason:all3Directional?`${all3} created a directional C1 condition.`:'No directional ALL3 condition exists at this checkpoint, so no new trade can start here.',
  })

  gates.push({
    id:'NEW_CANDIDATE',stage:'New candidate',required:true,
    result:candidate==='NEW_CANDIDATE'||candidate==='DETECTED'?'PASS':all3Directional?'FAIL':'NOT_APPLICABLE',
    expected:'Directional ALL3 must represent a new opposite candidate, not just an unchanged regime.',
    actual:candidate||'—',
    reason:candidate==='NEW_CANDIDATE'||candidate==='DETECTED'
      ?'A new strategy candidate was created.'
      :all3Directional?'Directional ALL3 exists, but the checkpoint did not create a new candidate.':'No directional ALL3 exists, so candidate detection is not applicable.',
  })

  if(progress.length){
    gates.push({
      id:'C2_TIMING',stage:'C2 timing',required:true,
      result:c2Eligibility?gateResultFromStatus(c2Eligibility.display_result||c2Eligibility.status):'WAIT',
      expected:'Exact C2 checkpoint at C1 + 5 minutes.',
      actual:c2Eligibility?.detail||c2Eligibility?.status||'Waiting for C2',
      reason:c2Eligibility?.reason||'Candidate cannot advance before the exact C2 checkpoint.',
    })

    let c2Result:DecisionGate['result']='WAIT'
    let c2Actual='Waiting for C2 persistence result'
    let c2Reason='The same ALL3 direction must survive at C2.'
    if(c2Confirmed){
      c2Result='PASS'
      c2Actual=c2Confirmed.detail||c2Confirmed.status||'C2 confirmed'
      c2Reason=c2Confirmed.reason||'The same ALL3 direction remained confirmed at C2.'
    }
    else if(c2Decision){
      c2Result=c2Decision.status==='CLASSIFIED'?'PASS':gateResultFromStatus(c2Decision.display_result||c2Decision.status)
      c2Actual=c2Decision.detail||c2Decision.status||'C2 decision recorded'
      c2Reason=c2Decision.reason||'The recorded C2 decision determined whether the candidate could continue.'
    }

    gates.push({
      id:'C2_PERSISTENCE',stage:'C2 persistence',required:true,result:c2Result,
      expected:`Same ${direction||'directional'} ALL3 must survive at C2.`,
      actual:c2Actual,reason:c2Reason,
    })

    gates.push({
      id:'FUTURES_DATA',stage:'Futures data',required:true,
      result:futuresFetch?gateResultFromStatus(futuresFetch.display_result||futuresFetch.status):'WAIT',
      expected:'Exact completed futures OI checkpoint must be available.',
      actual:futuresFetch?.detail||futuresFetch?.status||'Not reached',
      reason:futuresFetch?.reason||'Futures confirmation cannot run without completed futures data.',
    })

    const expectedFutures=direction==='BULLISH'?'LONG_BUILDUP or SHORT_COVERING':direction==='BEARISH'?'SHORT_BUILDUP or LONG_UNWINDING':'Directional candidate required'
    gates.push({
      id:'FUTURES_ALIGNMENT',stage:'Futures alignment',required:true,
      result:futuresAlign?gateResultFromStatus(futuresAlign.display_result||futuresAlign.status):c2Decision?.status==='REJECTED'?'FAIL':'WAIT',
      expected:expectedFutures,
      actual:futuresAlign?.detail||c2Decision?.detail||'Not reached',
      reason:futuresAlign?.reason||c2Decision?.reason||'Candidate direction must agree with the permitted futures OI states.',
    })

    gates.push({
      id:'SPOT_CLASS',stage:'Spot movement class',required:false,
      result:spotClass?'INFO':'NOT_APPLICABLE',
      expected:'Research classification only; not an entry gate.',
      actual:spotClass?.detail||'Not classified',
      reason:spotClass?.reason||'SPOT_LAG / SPOT_ALREADY_MOVED is recorded as context and does not independently permit or reject entry.',
    })

    gates.push({
      id:'OPTION_RESOLUTION',stage:'Exact ATM option',required:true,
      result:option?gateResultFromStatus(option.display_result||option.status):c2Decision?.status==='CLASSIFIED'?'WAIT':'NOT_APPLICABLE',
      expected:`Exact current ATM ${direction==='BEARISH'?'PE':direction==='BULLISH'?'CE':'option'}; no nearest-strike fallback.`,
      actual:option?.detail||option?.status||'Not reached',
      reason:option?.reason||'Entry requires an exact ATM instrument.',
    })

    gates.push({
      id:'ENTRY_OPEN',stage:'Next-minute entry',required:true,
      result:entry?'PASS':progress.some(x=>x.terminal)?'FAIL':'WAIT',
      expected:'Exact next-minute option open after all required gates pass.',
      actual:entry?.detail||entry?.status||'No entry opened',
      reason:entry?.reason||(progress.some(x=>x.terminal)?'Entry was not opened because an earlier required gate terminated the candidate.':'Waiting for all required checks and the causal next-minute entry price.'),
    })
  }

  return gates
}

function DecisionAudit({row,progress}:{row:TimelineRow,progress:ProgressItem[]}){
  const gates=buildDecisionGates(row,progress)
  const required=gates.filter(x=>x.required)
  const entry=gates.find(x=>x.id==='ENTRY_OPEN')
  const failed=required.find(x=>x.result==='FAIL'||x.result==='INCOMPLETE')
  const candidateStarted=progress.length>0 || ['NEW_CANDIDATE','DETECTED'].includes((row.candidate_detection?.status||'').toUpperCase())

  let finalTitle='NO TRADE CANDIDATE'
  let finalReason='This checkpoint did not create a new candidate.'
  let finalClass='hr-decision-neutral'
  if(entry?.result==='PASS'){finalTitle='TRADE TAKEN';finalReason='All required entry gates passed and the exact next-minute option entry was opened.';finalClass='hr-decision-pass'}
  else if(failed&&candidateStarted){finalTitle='TRADE NOT TAKEN';finalReason=`Stopped at ${failed.stage}: ${failed.reason}`;finalClass='hr-decision-fail'}
  else if(candidateStarted){finalTitle='CANDIDATE IN PROGRESS';finalReason='The candidate has not yet reached a terminal entry or rejection state.';finalClass='hr-decision-wait'}

  return <div className="hr-decision-audit">
    <div className={`hr-decision-final ${finalClass}`}><div><span>Final decision</span><b>{finalTitle}</b></div><p>{finalReason}</p></div>
    <div className="hr-decision-heading"><h4>Entry decision checks</h4><span>Required gates are evaluated independently. Context-only checks cannot reject a trade.</span></div>
    <div className="hr-decision-table-wrap"><table className="hr-decision-table">
      <thead><tr><th>Check</th><th>Role</th><th>Result</th><th>Expected</th><th>Actual evidence</th><th>Explanation</th></tr></thead>
      <tbody>{gates.map(g=><tr key={g.id} className={`hr-gate-${g.result.toLowerCase().replaceAll('_','-')}`}>
        <td><b>{g.stage}</b><code>{g.id}</code></td><td>{g.required?'REQUIRED':'CONTEXT'}</td><td>{badge(g.result)}</td><td>{g.expected}</td><td>{g.actual}</td><td>{g.reason}</td>
      </tr>)}</tbody>
    </table></div>
  </div>
}

function CheckpointDetail({row}:{row:TimelineRow}){
  const f=row.normalized_features?.payload||{}
  const horizons=f.horizons||{}
  const progress=buildProgress(row)

  return <div className="hr-detail">
    <div className="hr-detail-grid">
      <div><b>Spot</b><span>{n(f.spot)}</span></div>
      <div><b>Moving ATM</b><span>{n(f.moving_atm,0)}</span></div>
      <div><b>Health</b><span>{badge(row.data_health?.status)}</span></div>
      <div><b>ALL3</b><span>{badge(row.all3_decision?.status)}</span></div>
      <div><b>Candidate</b><span>{badge(row.candidate_detection?.status)}</span></div>
      <div><b>Exact strikes</b><span>{(f.moving_strikes||[]).join(', ')||'—'}</span></div>
    </div>

    <div className="hr-horizons">
      <Horizon name="5m" data={horizons['5m']}/>
      <Horizon name="10m" data={horizons['10m']}/>
      <Horizon name="15m" data={horizons['15m']}/>
    </div>

    <DecisionAudit row={row} progress={progress}/>
    <TradeSummary progress={progress}/>
    <TerminalPanel progress={progress}/>

    <div className="hr-progress-heading">
      <h4>Strategy progression</h4>
      <span>Chronological · audit + lifecycle events</span>
    </div>

    {!progress.length
      ? <div className="hr-empty">No candidate lifecycle at this checkpoint.</div>
      : <div className="hr-lifecycle">
          {progress.map((item,i)=><div className={`hr-life-row hr-life-${item.source.toLowerCase()} ${item.terminal?'hr-life-terminal':''}`} key={`${item.timestamp}-${item.stage}-${item.source}-${i}`}>
            <span className="hr-life-time">{shortTime(item.timestamp)}</span>
            <b className="hr-life-stage">{item.stage}</b>
            <div className="hr-life-explain">
              <div><span className="hr-life-label">Result</span>{badge(item.display_result||item.status||'—')}</div>
              {item.detail&&<div><span className="hr-life-label">Data</span><span>{item.detail}</span></div>}
              {item.reason&&<div><span className="hr-life-label">Reason</span><span>{item.reason}</span></div>}
              {item.next_action&&<div><span className="hr-life-label">Next</span><span>{item.next_action}</span></div>}
            </div>
            <code title={item.observation_id}>{item.observation_id}</code>
          </div>)}
        </div>}
  </div>
}
export default function HistoricalReplay(){
  const [sessions,setSessions]=useState<Session[]>([])
  const [selected,setSelected]=useState('')
  const [timeline,setTimeline]=useState<TimelineRow[]>([])
  const [status,setStatus]=useState<any>(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const [expanded,setExpanded]=useState<string|null>(null)
  const [refreshKey,setRefreshKey]=useState(0)
  const presetDates=useMemo(()=>{
    const values=new Set<string>([
      ...sessions.map(s=>s.session_date),
      ...recentPresetDates(45),
    ])
    return [...values].sort().reverse()
  },[sessions])

  useEffect(()=>{
    fetch('/api/live-shadow/replay/sessions')
      .then(r=>{if(!r.ok) throw new Error('Replay sessions unavailable'); return r.json()})
      .then(data=>{
        const rows:Session[]=data.sessions||[]
        setSessions(rows)
        if(rows.length) setSelected(current=>current||rows[0].session_date)
      })
      .catch(e=>setError(String(e)))
  },[])

  useEffect(()=>{
    if(!selected) return
    let active=true
    setLoading(true); setError('')
    const optionalJson=async(url:string)=>{
      const r=await fetch(url)
      if(r.status===404) return null
      if(!r.ok) throw new Error('Replay data unavailable')
      return r.json()
    }
    Promise.all([
      optionalJson(`/api/live-shadow/replay/status?date=${encodeURIComponent(selected)}`),
      optionalJson(`/api/live-shadow/replay/timeline?date=${encodeURIComponent(selected)}`),
    ]).then(([s,t])=>{
      if(!active)return
      setStatus(s?.status||null)
      setTimeline(t?.rows||[])
    }).catch(e=>{if(active)setError(String(e))})
      .finally(()=>{if(active)setLoading(false)})
    return()=>{active=false}
  },[selected,refreshKey])

  const closed=useMemo(()=>status?.state_counts?.CLOSED||0,[status])
  const open=useMemo(()=>['OPEN','BE_ARMED','TRAIL_ARMED'].reduce((x,k)=>x+(status?.state_counts?.[k]||0),0),[status])

  return <section className="historical-replay">
    <div className="hr-head">
      <div>
        <h2>Historical Replay</h2>
        <p>Current Live Shadow strategy · chronological causal replay · observation only</p>
      </div>
      <div className="hr-date-controls">
        <label>Quick date
          <select
            value={presetDates.includes(selected)?selected:''}
            onChange={e=>{if(e.target.value)setSelected(e.target.value)}}
          >
            <option value="">Select a date…</option>
            {presetDates.map(d=><option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <label>Custom date
          <input
            type="date"
            value={selected}
            onChange={e=>setSelected(e.target.value)}
          />
        </label>
      </div>
    </div>

    {error&&<div className="hr-error">{error}</div>}

    <HistoricalReplayInventory
      selectedDate={selected}
      onSelectDate={setSelected}
    />

    <HilegaHistoricalReplay />

    <HistoricalReplayOperations
      sessionDate={selected}
      onReplayComplete={()=>setRefreshKey(v=>v+1)}
    />

    <HistoricalOiResearch />


    <div className="hr-cards">
      <div><span>Analysis</span><b>{status?.status|| (loading?'LOADING':'—')}</b></div>
      <div><span>Checkpoints</span><b>{status?.processed_checkpoint_count??'—'} / {status?.checkpoint_count??'—'}</b></div>
      <div><span>Observations</span><b>{status?.observation_count??'—'}</b></div>
      <div><span>Open</span><b>{open}</b></div>
      <div><span>Closed</span><b>{closed}</b></div>
      <div><span>Audit chain</span><b>{status?.step_audit_chain_ok===true?'OK':status?.step_audit_chain_ok===false?'FAILED':'—'}</b></div>
    </div>

    <div className="hr-table-wrap">
      <table className="hr-table">
        <thead><tr>
          <th>Time</th><th>Spot</th><th>ATM</th>
          <th>5m</th><th>10m</th><th>15m</th><th>ALL3</th>
          <th>Candidate</th><th>Health</th><th>Details</th>
        </tr></thead>
        <tbody>
        {timeline.map(row=>{
          const isOpen=expanded===row.checkpoint
          return <>
            <tr key={row.checkpoint} className={row.observation_ids.length?'hr-candidate-row':''}>
              <td>{shortTime(row.checkpoint)}</td>
              <td>{n(row.summary.spot)}</td>
              <td>{n(row.summary.moving_atm,0)}</td>
              <td>{badge(row.summary.state_5m)}</td>
              <td>{badge(row.summary.state_10m)}</td>
              <td>{badge(row.summary.state_15m)}</td>
              <td>{badge(row.summary.all3_state)}</td>
              <td>{badge(row.summary.candidate)}</td>
              <td>{badge(row.summary.health)}</td>
              <td><button onClick={()=>setExpanded(isOpen?null:row.checkpoint)}>{isOpen?'Hide':'Audit'}</button></td>
            </tr>
            {isOpen&&<tr key={`${row.checkpoint}-detail`}><td colSpan={10}><CheckpointDetail row={row}/></td></tr>}
          </>
        })}
        {!loading&&!timeline.length&&<tr><td colSpan={10} className="hr-empty">No replay timeline found.</td></tr>}
        </tbody>
      </table>
    </div>
  </section>
}
