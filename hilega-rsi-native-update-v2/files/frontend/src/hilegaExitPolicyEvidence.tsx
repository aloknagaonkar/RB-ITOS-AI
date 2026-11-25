export default function HilegaExitPolicyEvidence({evidence:e,monitor:m}:{evidence?:any;monitor?:any}){
 if(!e)return null
 if(e.policy_id==='RSI_TWO_ROUTE_CONFIRMED_MIDPOINT'){
  const state=(v:any)=>v===true?'PASS':v===false?'WAIT':'NOT RECORDED'
  const checks:Record<string,string>={signal_midpoint_price_breach:'Close beyond fixed original signal midpoint',rsi5_opposite50:'RSI5 opposite 50',rsi9_opposite50:'RSI9 opposite 50',signal_midpoint_rsi_confirmed_exit:'Confirmed midpoint exit: all three together',wma50_exit:'WMA21(RSI9) opposite 50',opposite_ema_boundary_exit:'Close beyond opposite EMA30 boundary',all_three_exit:'Original all-three momentum / WMA / price exit',opposite_entry_exit:'Fully qualified opposite entry'}
  return <section aria-label="RSI Two Route exit evidence"><h4>Confirmed midpoint / all-three exit</h4>
   <p>Fixed original signal midpoint: {e.signal_midpoint}. CE: close below midpoint and RSI5/RSI9 below50. PE: close above midpoint and RSI5/RSI9 above50. Equality waits.</p>
   {Object.entries(checks).map(([key,label])=><p key={key}>{label}: <strong>{state(e[key])}</strong></p>)}
   <p>Final decision: <strong>{e.action??'HOLD'}</strong> · Session close15:30 IST. Exit is processed before an opposite entry.</p>
  </section>
 }
 const updated=Object.prototype.hasOwnProperty.call(e,'normal_exit_pass')
 const text=(v:any)=>v===true?'PASS':v===false?'WAIT':'NOT RECORDED'
 return <section aria-label="Recorded exit policy evidence">
  <h4>{updated?'WMA40 / confirmed reversal exit':'Recorded dual exit'}</h4>
  <p>RSI9 opposite WMA: {text(e.rsi_opposite)} · EMA3 of RSI opposite WMA: {text(e.ema_opposite)}</p>
  {e.wma40_required&&<p>Bearish WMA21 of RSI9: {Number(e.wma21).toFixed(3)} · strictly above 40: {text(e.wma_above40)}. Dual exit and WMA permission must pass together.</p>}
  <p>Final decision: <strong>{updated?e.action:e.dual_exit_pass?'EXIT':'HOLD'}</strong></p>
  {updated&&<p>Normal exit permission: {text(e.normal_exit_pass)} · confirmed bullish reversal: {text(e.reversal_confirmed)}. Candidate or signal alone cannot reverse. Session end {e.session_end_IST??'14:55'} IST.</p>}
  {m&&<details><summary>Bullish opposite confirmation — {m.confirmed?'CONFIRMED':'MONITORING'}</summary>
   <p>Independent monitoring while bearish; no additional position is opened. Full bullish entry and follow-up checks apply.</p>
   <pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(m,null,2)}</pre>
  </details>}
 </section>
}
