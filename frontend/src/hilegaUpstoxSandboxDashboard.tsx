import HilegaManualExit from './hilegaManualExit'
import {sessionDay,dateOptions,selectedTradeDay,TradeDateFilter} from './hilegaTradeDates'
import {usePcrContext,strikeBias} from './hilegaPcrContext'
import {useEffect,useState} from 'react'
const n=(v:any)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:2})
const money=(v:any)=>v==null?'Unavailable':`₹${n(v)}`
const t=(v:any)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const shortStatus=(status:string)=>status==='SELL_ACKNOWLEDGED'?'SELL ACK':status==='BUY_ACKNOWLEDGED'?'BUY ACK':status.replaceAll('_',' ')
const cls=(v:any)=>v==null?'':Number(v)>=0?'positive':'negative'
function Basket({trade}:{trade:any}){const pcr=usePcrContext(undefined,trade.expiry);const active=!['CLOSED_ACKNOWLEDGED','CANCELLED_UNFILLED'].includes(trade.status);return <article className="panel shadow-panel">
  <div className="panel-heading"><div><h3>{trade.direction} · {trade.trade_id}</h3><p>Signal {t(trade.signal_time)} · Expiry {trade.expiry} · {trade.status}</p><p>{trade.partial_basket?'PARTIAL BASKET: inspect per-leg acknowledgements.':'Five Sandbox contracts'} · {trade.missing_pnl_legs} legs with unavailable P&amp;L</p></div><b className={cls(trade.pnl_rupees)}>{money(trade.pnl_rupees)} {trade.missing_pnl_legs?'known-price subtotal':trade.legs.filter((l:any)=>l.entry_order_id).every((l:any)=>l.pnl_basis==='CONFIRMED_FILLS')?'confirmed':'estimated'}</b></div>
  <div className="shadow-table-scroll"><table className="shadow-table sandbox-compact-table"><thead><tr><th>Contract</th><th>Combined bias</th><th>Submission</th><th>Quantity</th><th>Entry time / price</th><th>Current quote / time</th><th>Exit time / price</th><th>Estimated points / P&amp;L</th><th>Order IDs</th></tr></thead><tbody>{trade.legs.map((leg:any)=><tr key={leg.role}>
    <td>ATM{leg.role===0?'':leg.role>0?`+${leg.role}`:leg.role} · {n(leg.strike)} {leg.option_type}<small>{leg.instrument_key}</small></td>
    <td title={active?"Current CE/PE combined bias for this strike; matching expiry PCR is required":"Historical bias was not saved for this completed trade"}>{active?strikeBias(pcr,leg.strike,leg.instrument_key):"Not recorded"}</td><td className="sandbox-submission" title={`${leg.status} · ${leg.pnl_basis==='CONFIRMED_FILLS'?'Confirmed execution evidence':'Order acknowledgement is not a fill confirmation'}`}>{shortStatus(leg.status)}</td><td>{leg.quantity}{leg.requested_quantity!=null&&<small>{leg.requested_quantity} requested</small>}</td>
    <td>{t(leg.entry_time)}<small>{n(leg.entry_price)}</small></td><td>{leg.exit_order_id?'—':n(leg.current_price)}<small>{t(leg.quote_timestamp)}</small></td>
    <td>{t(leg.exit_time)}<small>{n(leg.exit_price)}</small></td><td className={cls(leg.pnl_rupees)}>{n(leg.points)}<small>{money(leg.pnl_rupees)}</small></td>
    <td className="sandbox-order-ids"><details><summary>View IDs</summary><small>BUY: {leg.entry_order_id??'Not acknowledged'}</small><small>SELL: {leg.exit_order_id??'Not acknowledged'}</small></details></td>
  </tr>)}</tbody></table></div></article>}
export default function HilegaUpstoxSandboxDashboard(){
  const [tradeDate,setTradeDate]=useState('')
  const [data,setData]=useState<any>(null),[error,setError]=useState(''),[received,setReceived]=useState(0),[clock,setClock]=useState(Date.now())
  useEffect(()=>{let active=true,busy=false;let controller:AbortController|null=null
    const poll=async()=>{if(busy||document.hidden)return;busy=true;controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),15000)
      try{const r=await fetch('/api/live-shadow/hilega-upstox-sandbox/dashboard',{signal:controller.signal});if(!r.ok)throw new Error(`Sandbox dashboard HTTP ${r.status}`);const x=await r.json();if(active){setData(x);setError('');setReceived(Date.now())}}catch(e){if(active)setError((e as Error).message)}finally{clearTimeout(timeout);busy=false}}
    void poll();const poller=setInterval(()=>void poll(),10000),tick=setInterval(()=>setClock(Date.now()),5000);return()=>{active=false;clearInterval(poller);clearInterval(tick);controller?.abort()}
  },[])
  if(!data)return <section className="panel shadow-panel">{error||'Loading five-leg Sandbox status…'}</section>
  if(data.model!=='HILEGA_UPSTOX_SANDBOX_BASKET_V2')return <section className="panel shadow-panel"><h2>Five-leg Sandbox activation pending</h2><p>Restart the API and arm the five-leg worker. Existing one-contract history remains preserved.</p></section>
  const completedDates=dateOptions(data.completed_trades.map((x:any)=>x.session_date||sessionDay(x.signal_time)))
  const selectedDate=selectedTradeDay(tradeDate,completedDates)
  const completedTrades=data.completed_trades.filter((x:any)=>(x.session_date||sessionDay(x.signal_time))===selectedDate)
  const w=data.worker,p=data.pnl,overall=data.overall_pnl
  return <div className="hilega-sandbox-dashboard"><style>{`.sandbox-compact-table td small{display:block;margin-top:3px}.sandbox-compact-table .sandbox-submission{font-size:12px;white-space:nowrap}.sandbox-compact-table .sandbox-order-ids{font-size:12px}.sandbox-order-ids summary{cursor:pointer;white-space:nowrap}.sandbox-order-ids details[open] small{white-space:nowrap;font-variant-numeric:tabular-nums}`}</style>
    <section className="panel shadow-panel"><h2>{data.strategy.active_strategy_id} · Five actual Sandbox legs</h2><p>Armed strategy {data.strategy.armed_strategy_id??'Not armed'} · Session {w.session_date??'Unavailable'} · Worker {w.running?'running':'stopped'} · {w.armed?'armed':'disarmed'} · Kill switch {w.kill_switch?'ON':'OFF'}</p><p>No daily order-count cap · One lot per leg · Upstox Sandbox only · Live execution disabled</p>{w.entries_blocked&&<div className="banner error">New entries blocked: {w.failure_reason} · {t(w.failed_at)}. Known accepted legs may still follow their shadow exit while armed.</div>}</section>
    {error&&<div className="banner error">{error}</div>}{received&&clock-received>30000?<div className="banner error">Dashboard stale; displayed P&amp;L is not current.</div>:null}{data.quote_error&&<div className="banner error">{data.quote_error}</div>}
    <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Session Sandbox P&amp;L · {data.pnl_session_date??w.session_date}</h2><p>{data.warning}</p></div><span className="pill">{t(data.last_refresh)}</span></div>
      <div className="shadow-metrics hilega-dashboard-summary"><article><span>Total estimated P&amp;L</span><b className={cls(p.total_estimated_rupees)}>{money(p.total_estimated_rupees)}</b><small>{p.missing_pnl_legs} legs missing prices; totals are known-price subtotals</small></article><article><span>Open estimate</span><b className={cls(p.open_estimated_rupees)}>{money(p.open_estimated_rupees)}</b></article><article><span>Closed estimate</span><b className={cls(p.closed_estimated_rupees)}>{money(p.closed_estimated_rupees)}</b></article><article><span>Gain / loss ratio</span><b>{n(p.gain_loss_ratio)}</b><small>Gains {money(p.gross_profit_rupees)} · losses {money(p.gross_loss_rupees)}</small></article><article><span>Accepted order submissions</span><b>{w.accepted_orders_this_session}</b><small>No daily count limit · {w.open_legs} open acknowledged legs</small></article><article><span>Completed signal baskets</span><b>{p.completed_baskets??0}</b><small>{w.uncertain_requests} requests require reconciliation</small></article></div></section>
    {overall&&<section className="panel shadow-panel"><h2>Overall Sandbox P&amp;L · all retained sessions</h2><p>{overall.first_session??'No recorded sessions'} → {overall.last_session??'—'} · {overall.session_count} sessions. Restored from the persistent five-leg trade journal after refresh, restart or re-arm.</p><div className="shadow-metrics hilega-dashboard-summary">
      <article><span>Total estimated P&amp;L</span><b className={cls(overall.total_estimated_rupees)}>{money(overall.total_estimated_rupees)}</b><small>Closed + open · {overall.missing_pnl_legs} legs missing prices</small></article>
      <article><span>Closed estimated net</span><b className={cls(overall.closed_estimated_rupees)}>{money(overall.closed_estimated_rupees)}</b></article>
      <article><span>Open estimate</span><b className={cls(overall.open_estimated_rupees)}>{money(overall.open_estimated_rupees)}</b></article>
      <article><span>Gross gains / losses</span><b>{money(overall.gross_profit_rupees)} / {money(overall.gross_loss_rupees)}</b><small>Gain/loss ratio {n(overall.gain_loss_ratio)}</small></article>
      <article><span>Completed baskets</span><b>{overall.completed_baskets}</b><small>{overall.partial_baskets} partial baskets · totals use known prices</small></article>
    </div><p>Estimated option P&amp;L from recorded quotes; acknowledgements are not confirmed fills. Includes five-leg journal history across strategies, not older one-contract experiments.</p></section>}
    <HilegaManualExit/>
    <section className="panel shadow-panel"><h2>Current active Sandbox trade</h2>{!data.active_trades.length?<div className="empty">No active five-leg Sandbox basket.</div>:data.active_trades.map((x:any)=><Basket key={x.trade_id} trade={x}/>)}</section>
    <section className="panel shadow-panel"><h2>Completed Sandbox trades</h2><TradeDateFilter value={selectedDate} dates={completedDates} onChange={setTradeDate}><span>{completedTrades.length} of {data.completed_trades.length} completed baskets</span></TradeDateFilter>{!completedTrades.length?<div className="empty">No completed five-leg baskets for this session.</div>:completedTrades.map((x:any)=><Basket key={x.trade_id} trade={x}/>)}</section>
    <section className="panel shadow-panel"><h2>Skipped, blocked and reconciliation events</h2><pre>{JSON.stringify(data.events,null,2)}</pre></section>
  </div>
}
