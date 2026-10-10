import {useState} from 'react'
const n=(v:any)=>v==null?'—':Number(v).toFixed(3)
const tm=(v:any)=>v?String(v).slice(11,16):'—'
export default function HilegaAlignmentReplay({data,visibleUntil,onSelected}: {data:any;visibleUntil?:string;onSelected?:(checkpoint:string)=>void}){
 const [only5m,setOnly5m]=useState(false)
 const rows=(data.audit??[]).filter((a:any)=>(!visibleUntil||a.checkpoint<=visibleUntil)&&(!only5m||a.five_minute_label||a.transitions?.length))
 const ledger=(data.trades??[]).filter((t:any)=>!visibleUntil||t.entry_time<=visibleUntil).map((t:any)=>{if(!visibleUntil||t.exit_time<=visibleUntil)return t;const last=[...(data.audit??[])].reverse().find((a:any)=>a.checkpoint<=visibleUntil);return {...t,exit_time:null,exit_price:null,exit_reason:'ACTIVE AT REPLAY CHECKPOINT',points:last?.active_trade?.nifty_points,warning_time:t.warning_time&&t.warning_time<=visibleUntil?t.warning_time:null,mfe_points:null,giveback_points:null}})
 return <section className="panel" aria-label="V2 alignment dual exit research">
  <h3>V2 · alignment setup + dual exit · research</h3>
  <p>V1 setup OR completed five-minute directional ordering with positive expanding minute gap. Strength ≥0.75, later persistence, ten-minute window. Exit when both RSI9 and EMA3 are beyond WMA21. Forced exit 14:55 IST. EMA/WMA are on RSI9.</p>
  <details><summary>Exact strategy configuration and evidence provenance</summary><pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify({rules:data.rules,manifest:data.manifest},null,2)}</pre></details>
  <h4>Trades · Nifty points</h4><div style={{overflowX:'auto'}}><table><thead><tr><th>Direction</th><th>Setup source</th><th>Signal IST</th><th>Entry IST</th><th>Entry Nifty</th><th>RSI warning IST</th><th>Exit IST</th><th>Exit Nifty</th><th>Points</th><th>Maximum favourable</th><th>Giveback</th><th>Exit reason</th></tr></thead><tbody>
   {ledger.map((t:any)=><tr key={t.trade_id}><td>{t.direction}</td><td>{t.setup_source}</td><td>{tm(t.signal_time)}</td><td>{tm(t.entry_time)}</td><td>{n(t.entry_price)}</td><td>{tm(t.warning_time)}</td><td>{tm(t.exit_time)}</td><td>{n(t.exit_price)}</td><td>{n(t.points)}</td><td>{n(t.mfe_points)}</td><td>{n(t.giveback_points)}</td><td>{t.exit_reason}</td></tr>)}
  </tbody></table></div>
  <h4>Decision audit · every minute and five-minute close</h4>
  <label><input type="checkbox" checked={only5m} onChange={e=>setOnly5m(e.target.checked)}/> Five-minute closes and trade transitions only</label>
  <div style={{overflowX:'auto'}}><table><thead><tr><th>Decision IST</th><th>5m candle label</th><th>Nifty</th><th>Owner before → after</th><th>Events in order</th><th>Inspection</th></tr></thead><tbody>
  {rows.map((a:any,i:number)=><tr key={`${a.checkpoint}-${i}`}><td>{tm(a.checkpoint)}</td><td>{tm(a.five_minute_label)}</td><td>{n(a.nifty_close)}</td><td>{a.owner_before??'—'} → {a.owner_after}</td><td>{(a.transitions??[]).map((e:any)=>`${e.event} ${e.direction}`).join(' → ')||'Evaluate / wait'}</td><td><details><summary onClick={()=>onSelected?.(a.checkpoint)}>View conditions</summary>
   <p>Completed 5m: RSI {n(a.completed_5m_indicators?.rsi9)} · EMA {n(a.completed_5m_indicators?.ema3)} · WMA {n(a.completed_5m_indicators?.wma21)}</p>
   <p>Provisional: RSI {n(a.indicators?.rsi9)} · EMA {n(a.indicators?.ema3)} · WMA {n(a.indicators?.wma21)}</p>
   <p>5m changes: RSI {n(a.five_minute_changes?.rsi9)} · EMA {n(a.five_minute_changes?.ema3)} · WMA {n(a.five_minute_changes?.wma21)}</p>
   {a.active_trade&&<p>Active {a.active_trade.direction} · entry {tm(a.active_trade.entry_time)} at {n(a.active_trade.entry_price)} · current Nifty points {n(a.active_trade.nifty_points)}</p>}
   {a.exit_validation&&<p>Five-minute exit check: RSI opposite {a.exit_validation.rsi_opposite?'PASS':'WAIT'} · EMA opposite {a.exit_validation.ema_opposite?'PASS':'WAIT'} · both {a.exit_validation.dual_exit_pass?'EXIT':'HOLD'}</p>}
   <p>First RSI exit warning: {tm(a.exit_warning_time)}</p>
   {(a.checks??[]).map((c:any,j:number)=><div key={j}><strong>{c.direction} · {c.status}</strong><p>Previous minute {tm(c.previous_timestamp)} → current {tm(c.minute_timestamp)}; decision {tm(c.decision_timestamp)}</p><table><thead><tr><th>Condition</th><th>Previous</th><th>Current</th><th>Result</th></tr></thead><tbody>
    <tr><td>RSI9</td><td>{n(c.previous_rsi9)}</td><td>{n(c.current_rsi9)}</td><td>Diagnostic</td></tr>
    <tr><td>EMA3 of RSI9</td><td>{n(c.previous_ema3)}</td><td>{n(c.current_ema3)}</td><td>Diagnostic</td></tr>
    <tr><td>WMA21 of RSI9</td><td>{n(c.previous_wma21)}</td><td>{n(c.current_wma21)}</td><td>Diagnostic</td></tr>
    <tr><td>WMA strength ≥0.75</td><td>{n(c.previous_directional_wma_strength)}</td><td>{n(c.directional_wma_strength)}</td><td>{c.wma_threshold_pass?'PASS':'WAIT'}</td></tr>
    <tr><td>Positive gap</td><td>{n(c.previous_gap)}</td><td>{n(c.current_gap)}</td><td>{c.gap_positive_pass?'PASS':'WAIT'}</td></tr>
    <tr><td>Gap expansion &gt;0</td><td>{n(c.previous_gap)}</td><td>Δ {n(c.gap_delta)}</td><td>{c.gap_expanding_pass?'PASS':'WAIT'}</td></tr>
    <tr><td>Later persistence</td><td colSpan={2}>Armed {tm(c.armed_at)}</td><td>{c.persistence_pass?'PASS':'WAIT'}</td></tr>
    <tr><td>Ten-minute window</td><td colSpan={2}>Signal available {tm(c.signal_available_at)}</td><td>{c.confirmation_window_pass?'PASS':'BLOCKED'}</td></tr>
   </tbody></table><p>{c.reasons?.join(' · ')||'All entry checks passed'}</p></div>)}
   <details><summary>Full setup, exit and transition evidence</summary><pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(a,null,2)}</pre></details>
  </details></td></tr>)}
  </tbody></table></div>
 </section>
}
