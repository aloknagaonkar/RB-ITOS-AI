export default function HilegaExitPolicyEvidence({evidence:e,monitor:m}:{evidence?:any;monitor?:any}){
 if(!e)return null
 const updated=Object.prototype.hasOwnProperty.call(e,'normal_exit_pass')
 const text=(v:any)=>v===true?'PASS':v===false?'WAIT':'NOT RECORDED'
 return <section aria-label="Recorded exit policy evidence">
  <h4>{updated?'WMA40 / confirmed reversal exit':'Recorded dual exit'}</h4>
  <p>RSI9 opposite WMA: {text(e.rsi_opposite)} · EMA3 of RSI opposite WMA: {text(e.ema_opposite)}</p>
  {e.wma40_required&&<p>Bearish WMA21 of RSI9: {Number(e.wma21).toFixed(3)} · strictly above 40: {text(e.wma_above40)}. Dual exit and WMA permission must pass together.</p>}
  <p>Final decision: <strong>{updated?e.action:e.dual_exit_pass?'EXIT':'HOLD'}</strong></p>
  {updated&&<p>Normal exit permission: {text(e.normal_exit_pass)} · confirmed bullish reversal: {text(e.reversal_confirmed)}. Candidate or signal alone cannot reverse. Cutoff 14:55 IST.</p>}
  {m&&<details><summary>Bullish opposite confirmation — {m.confirmed?'CONFIRMED':'MONITORING'}</summary>
   <p>Independent monitoring while bearish; no additional position is opened. Full bullish entry and follow-up checks apply.</p>
   <pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(m,null,2)}</pre>
  </details>}
 </section>
}
