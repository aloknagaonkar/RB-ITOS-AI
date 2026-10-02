from pathlib import Path

tsx = Path("frontend/src/historicalReplay.tsx")
css = Path("frontend/src/historicalReplay.css")

text = tsx.read_text(encoding="utf-8")
original = text

old_type = '''type ProgressItem = {
  timestamp:string
  source:'AUDIT'|'EVENT'
  stage:string
  status:string
  observation_id:string
  detail:string
  payload:Record<string,any>
  sort_order:number
}'''
new_type = '''type ProgressItem = {
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
}'''

if old_type in text:
    text = text.replace(old_type, new_type, 1)
elif "display_result?:string" not in text:
    raise SystemExit("SAFE STOP: ProgressItem type anchor not found")

anchor = "function buildProgress(row:TimelineRow):ProgressItem[]{"
if anchor not in text:
    raise SystemExit("SAFE STOP: buildProgress anchor not found")

helpers = r'''
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

'''

if "function explainProgressItem(" not in text:
    text = text.replace(anchor, helpers + anchor, 1)

old_return = '''  return items.sort((a,b)=>{
    const ta=Date.parse(a.timestamp)
    const tb=Date.parse(b.timestamp)
    if(Number.isFinite(ta) && Number.isFinite(tb) && ta!==tb) return ta-tb
    if(a.timestamp!==b.timestamp) return a.timestamp.localeCompare(b.timestamp)
    if(a.sort_order!==b.sort_order) return a.sort_order-b.sort_order
    return a.source.localeCompare(b.source)
  })
}'''
new_return = '''  return items.sort((a,b)=>{
    const ta=Date.parse(a.timestamp)
    const tb=Date.parse(b.timestamp)
    if(Number.isFinite(ta) && Number.isFinite(tb) && ta!==tb) return ta-tb
    if(a.timestamp!==b.timestamp) return a.timestamp.localeCompare(b.timestamp)
    if(a.sort_order!==b.sort_order) return a.sort_order-b.sort_order
    return a.source.localeCompare(b.source)
  }).map(explainProgressItem)
}'''

if old_return in text:
    text = text.replace(old_return, new_return, 1)
elif ").map(explainProgressItem)" not in text:
    raise SystemExit("SAFE STOP: buildProgress return block not found")

checkpoint_anchor = "function CheckpointDetail({row}:{row:TimelineRow}){"
if checkpoint_anchor not in text:
    raise SystemExit("SAFE STOP: CheckpointDetail anchor not found")

terminal_component = r'''
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

'''

if "function TerminalPanel(" not in text:
    text = text.replace(checkpoint_anchor, terminal_component + checkpoint_anchor, 1)

trade_summary_anchor = '''    <TradeSummary progress={progress}/>

    <div className="hr-progress-heading">'''
replacement_summary = '''    <TradeSummary progress={progress}/>
    <TerminalPanel progress={progress}/>

    <div className="hr-progress-heading">'''

if trade_summary_anchor in text:
    text = text.replace(trade_summary_anchor, replacement_summary, 1)
elif "<TerminalPanel progress={progress}/>" not in text:
    raise SystemExit("SAFE STOP: TradeSummary render anchor not found")

old_row = '''          {progress.map((item,i)=><div className={`hr-life-row hr-life-${item.source.toLowerCase()}`} key={`${item.timestamp}-${item.stage}-${item.source}-${i}`}>
            <span className="hr-life-time">{shortTime(item.timestamp)}</span>
            <b>{item.stage}</b>
            <span className="hr-life-detail">{item.detail || (item.status?String(item.status):'—')}</span>
            <span className="hr-life-status">{item.status?badge(item.status):null}</span>
            <code title={item.observation_id}>{item.observation_id}</code>
          </div>)}'''
new_row = '''          {progress.map((item,i)=><div className={`hr-life-row hr-life-${item.source.toLowerCase()} ${item.terminal?'hr-life-terminal':''}`} key={`${item.timestamp}-${item.stage}-${item.source}-${i}`}>
            <span className="hr-life-time">{shortTime(item.timestamp)}</span>
            <b className="hr-life-stage">{item.stage}</b>
            <div className="hr-life-explain">
              <div><span className="hr-life-label">Result</span>{badge(item.display_result||item.status||'—')}</div>
              {item.detail&&<div><span className="hr-life-label">Data</span><span>{item.detail}</span></div>}
              {item.reason&&<div><span className="hr-life-label">Reason</span><span>{item.reason}</span></div>}
              {item.next_action&&<div><span className="hr-life-label">Next</span><span>{item.next_action}</span></div>}
            </div>
            <code title={item.observation_id}>{item.observation_id}</code>
          </div>)}'''

if old_row in text:
    text = text.replace(old_row, new_row, 1)
elif "hr-life-explain" not in text:
    raise SystemExit("SAFE STOP: lifecycle row render anchor not found")

tsx.write_text(text, encoding="utf-8")

css_text = css.read_text(encoding="utf-8")
marker = "/* HISTORICAL_REPLAY_EXPLAINABILITY_V1_2 */"
if marker not in css_text:
    css_text += r'''

/* HISTORICAL_REPLAY_EXPLAINABILITY_V1_2 */
.hr-terminal{
  margin-top:12px;
  border:1px solid var(--border,#3f5664);
  border-radius:10px;
  padding:12px;
}
.hr-terminal-rejected{border-color:#a43838}
.hr-terminal-closed{border-color:#566e7a}
.hr-terminal-title{
  font-weight:800;
  letter-spacing:.04em;
  margin-bottom:10px;
}
.hr-terminal-rejected .hr-terminal-title{color:#d94b4b}
.hr-terminal-grid{
  display:grid;
  grid-template-columns:repeat(3,minmax(170px,1fr));
  gap:8px;
}
.hr-terminal-grid>div{
  border:1px solid var(--border,#344650);
  border-radius:8px;
  padding:8px 10px;
  display:flex;
  flex-direction:column;
  gap:4px;
}
.hr-terminal-grid b{
  font-size:10px;
  text-transform:uppercase;
  opacity:.68;
}
.hr-terminal-wide{grid-column:1/-1}
.hr-life-row{
  grid-template-columns:64px 205px minmax(420px,1fr) minmax(190px,260px);
  align-items:start;
}
.hr-life-terminal{
  border-left:3px solid #a43838;
  padding-left:8px;
}
.hr-life-stage{padding-top:4px}
.hr-life-explain{
  display:grid;
  gap:4px;
  white-space:normal;
}
.hr-life-explain>div{
  display:grid;
  grid-template-columns:58px minmax(0,1fr);
  gap:8px;
  align-items:start;
}
.hr-life-label{
  font-size:9px;
  text-transform:uppercase;
  opacity:.58;
  letter-spacing:.05em;
  padding-top:3px;
}
.hr-life-explain .hr-badge{justify-self:start}
.hr-life-row code{padding-top:4px}
@media(max-width:1100px){
  .hr-terminal-grid{grid-template-columns:repeat(2,minmax(150px,1fr))}
  .hr-terminal-wide{grid-column:1/-1}
  .hr-life-row{grid-template-columns:60px 180px minmax(260px,1fr)}
  .hr-life-row code{display:none}
}
@media(max-width:700px){
  .hr-terminal-grid{grid-template-columns:1fr}
  .hr-terminal-wide{grid-column:auto}
  .hr-life-row{grid-template-columns:54px 1fr}
  .hr-life-explain{grid-column:2}
}
'''
    css.write_text(css_text, encoding="utf-8")

if text == original:
    print("No TSX changes were needed.")
else:
    print("Patched Historical Replay Explainability V1.2.")
