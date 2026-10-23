import HilegaExitPolicyEvidence from './hilegaExitPolicyEvidence'
type Step={label:string;status:string;value:string;rule:string;explanation:string}
const value=(v:any)=>v==null?'Not recorded':typeof v==='number'?v.toFixed(4):String(v)
const result=(v:any)=>v===true?'PASS':v===false?'WAIT':'UNAVAILABLE'
const step=(label:string,pass:any,observed:string,rule:string,explanation:string):Step=>({label,status:result(pass),value:observed,rule,explanation})
export function entryInspection(c:Record<string,any>):Step[]{
 if(c.policy_name==='BULLISH_GAP2_FULL_WMA2'){
  const e=c.ema10_entry??{}
  const rows:Step[]=[
   {label:'Completed 5m / retained candidate',status:'INFO',value:value(c.signal_available_at),rule:'No persistence or ten-minute expiry',explanation:'Signal qualification and later follow-up are distinct.'},
   step('Signal WMA strength',c.wma_threshold_pass,value(c.directional_wma_strength),'>=0.75','Follow-up price route may bypass fresh strength.'),
   step('Positive directional gap',c.gap_positive_pass,value(c.current_gap),'>0; bullish qualified signal additionally >=2','Gap uses EMA3 and WMA21 of RSI9.'),
   step('Gap expansion',c.gap_expanding_pass,value(c.gap_delta),'>0 versus previous completed 5m','Follow-up price route is an alternative to fresh strength/gap.')]
  for(const [key,label] of Object.entries({price_position_pass:'Signal close versus price EMA10',slope_pass:'Signal price EMA10 slope',candle_colour_pass:'Signal candle colour',rsi_continuation_pass:'Signal RSI40/60 momentum',fresh_signal_alignment_pass:'Signal RSI/EMA/WMA alignment',bullish_signal_gap_pass:'Bullish signal gap >=2',full_wma_pass:'Bullish full WMA magnitude >=2',followup_colour_pass:'Follow-up candle colour',followup_rsi_direction_pass:'Follow-up RSI direction',followup_price_pass:'Follow-up price route',fresh_strength_gap_pass:'Follow-up fresh strength/gap route'})){
   if(key in e)rows.push(step(label,e[key],value(e[key]),'Recorded policy requirement','See recorded evidence for stage-specific values.'))
  }
  rows.push({label:'Recorded decision',status:c.status==='ENTRY'?'PASS':'WAIT',value:value(c.status),rule:'Full confirmation only; candidate alone is not entry',explanation:(c.reasons??[]).join(' · ')})
  return rows
 }
 return [
  step('T+10 confirmation window',c.confirmation_window_pass,`Signal available ${value(c.signal_available_at)} · decision ${value(c.decision_timestamp)}`,'Within the recorded ten-minute confirmation window','A setup does not permit an entry after its confirmation window.'),
  step('Directional WMA21 strength',c.wma_threshold_pass,`Current strength ${value(c.directional_wma_strength)}`,'>= 0.75','Bullish measures current WMA minus reference WMA; bearish reverses the sign.'),
  step('Later one-minute persistence',c.persistence_pass,`Previous strength ${value(c.previous_directional_wma_strength)} → current ${value(c.directional_wma_strength)} · armed ${value(c.armed_at)}`,'Previous and current >= 0.75; adjacent minutes; later arm confirmation','The arm minute cannot confirm itself. Exit-boundary replacement uses the recorded same-boundary confirmation rule.'),
  step('Positive directional EMA3–WMA21 gap',c.gap_positive_pass,`EMA3 ${value(c.current_ema3)} · WMA21 ${value(c.current_wma21)} · gap ${value(c.current_gap)}`,'> 0','Bullish: EMA minus WMA. Bearish: WMA minus EMA.'),
  step('Gap expansion',c.gap_expanding_pass,`Previous gap ${value(c.previous_gap)} → current ${value(c.current_gap)} · change ${value(c.gap_delta)}`,'Current gap > previous adjacent-minute gap','A wide gap alone does not establish expansion.'),
  {label:'RSI9 / EMA3 / WMA21 alignment',status:'DIAGNOSTIC',value:`RSI9 ${value(c.current_rsi9)} · EMA3 ${value(c.current_ema3)} · WMA21 ${value(c.current_wma21)} · aligned ${value(c.directional_alignment_diagnostic)}`,rule:'Diagnostic at minute confirmation',explanation:'This flag is not an extra mandatory entry gate.'},
  {label:'EMA3 continuation',status:'DIAGNOSTIC',value:`Directional change ${value(c.ema3_continuation_delta)}`,rule:'Diagnostic only',explanation:'This value does not independently accept or reject the entry.'},
  {label:'Recorded entry decision',status:c.status==='ENTRY'?'PASS':c.status==='WAIT'?'WAIT':'UNAVAILABLE',value:value(c.status),rule:'All mandatory gates pass and owner/cutoff permit entry',explanation:(c.reasons??[]).join(' · ')||'No recorded rejection reasons.'}
 ]
}
export function exitInspection(e:Record<string,any>):Step[]{
 const bullish=e.direction==='BULLISH';const comparison=bullish?'below':'above'
 return [
  step('RSI9 opposite WMA21',e.rsi_opposite,`RSI9 ${value(e.rsi9)} · WMA21 ${value(e.wma21)}`,`RSI9 strictly ${comparison} WMA21`,'This can raise the first exit warning.'),
  step('EMA3 opposite WMA21',e.ema_opposite,`EMA3 ${value(e.ema3)} · WMA21 ${value(e.wma21)}`,`EMA3 strictly ${comparison} WMA21`,'EMA3 must also confirm the reversal.'),
  step('Dual exit prerequisite',e.dual_exit_pass,`Recorded dual-exit result ${value(e.dual_exit_pass)}`,'Both conditions on a completed five-minute candle','For the WMA40 policy this alone is insufficient for bearish exit; see final exit permission above.')
 ]
}
function Steps({rows}:{rows:Step[]}){return <div className="hd-scroll"><table className="hd-table"><thead><tr><th>Monitored step</th><th>Status</th><th>Observed value</th><th>Required rule</th><th>Explanation</th></tr></thead><tbody>{rows.map((s,i)=><tr key={i}><td>{s.label}</td><td><span className={`hd-badge ${s.status==='PASS'?'hd-pass':s.status==='WAIT'?'hd-fail':'hd-neutral'}`}>{s.status}</span></td><td>{s.value}</td><td>{s.rule}</td><td>{s.explanation}</td></tr>)}</tbody></table></div>}
export default function HilegaAlignmentAuditInspection({report:r}:{report:any}){
 const c=r.conditions??{},setup=c.canonical_setup??{},checks=c.wma_gap_checks??[],exit=c.exit_validation
 const combined=checks.some((x:any)=>x.policy_name==='BULLISH_GAP2_FULL_WMA2')||exit?.wma40_required!==undefined
 return <section><h4>{r.strategy?.strategy_id} · strategy inspection</h4>
 {combined?<p>Combined policy: completed 5m signal and follow-up; price EMA10 signal checks, bullish gap and full WMA magnitude ≥2. Bearish exit: dual exit AND WMA&gt;40, or fully confirmed bullish reversal. Cutoff 14:55.</p>:<p>Legacy alignment strategy; inspect its recorded strategy configuration.</p>}
 <h4>Setup evidence</h4><p>Completed five-minute indicator candle: {value(c.indicator_timestamp)}. Previous five-minute indicator values are not recorded in this row.</p>
 <p>Canonical accepted events: {(setup.canonical_setup_events??[]).join(' · ')||'None emitted at this checkpoint'} · suppressed events: {(setup.canonical_suppressed_events??[]).join(' · ')||'None recorded'}</p>
 {(c.setup_attempts??[]).map((s:any,i:number)=><p key={i}>Setup armed: {value(s.direction)} · {value(s.source)} · {value(s.time)}</p>)}
 <details><summary>Recorded bullish / bearish canonical setup conditions</summary><pre>{JSON.stringify({bullish:setup.canonical_bullish_conditions,bearish:setup.canonical_bearish_conditions},null,2)}</pre></details>
 <h4>Entry confirmation</h4>{checks.length?checks.map((check:any,i:number)=><div key={i}><p><b>{check.direction}</b> · previous minute {value(check.previous_timestamp)} → current minute {value(check.minute_timestamp)}</p><Steps rows={entryInspection(check)}/></div>):<p>No pending entry was evaluated at this checkpoint. This is not a failed entry check.</p>}
 <HilegaExitPolicyEvidence evidence={exit} monitor={c.opposite_confirmation}/><h4>Five-minute dual-exit validation</h4>{exit?<><p>Exit direction: {value(exit.direction)}</p><Steps rows={exitInspection(exit)}/></>:<p>No active-trade five-minute exit evaluation was recorded at this checkpoint.</p>}
 <p>First exit warning: {value(c.exit_warning_time)} · Session cutoff: 14:55 IST · Existing exit precedes a permitted replacement entry.</p>
 <details><summary>Raw recorded entry / exit evidence</summary><pre>{JSON.stringify({checks,exit,setup_attempts:c.setup_attempts},null,2)}</pre></details>
 </section>
}
