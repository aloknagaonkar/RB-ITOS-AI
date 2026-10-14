import {useEffect,useState} from 'react'

type Trade={trade_id:string;status:string;direction:string;option_type:string;instrument_key:string;strike:number|null;expiry:string|null;quantity:number;entry_signal_time:string|null;exit_signal_time:string|null;entry_time:string|null;exit_time:string|null;entry_order_id:string|null;exit_order_id:string|null;entry_reference_price:number|null;exit_reference_price:number|null;current_option_ltp:number|null;quote_timestamp:string|null;estimated_points:number|null;estimated_pnl_rupees:number|null}
type Data={strategy:{active_strategy_id:string;armed_strategy_id:string;strategy_match:boolean;mode:string};worker:Record<string,any>;pnl:Record<string,number|null>;active_trade:Trade|null;completed_trades:Trade[];blocked_events:Record<string,any>[];last_refresh:string;safety:{sandbox_only:boolean;live_execution_enabled:boolean};warning:string}
const n=(v:any,d=2)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:d})
const money=(v:any)=>v==null?'—':`₹${n(v,2)}`
const t=(v:any)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const words=(v:any)=>String(v??'—').replaceAll('_',' ')
const cls=(v:any)=>v==null?'':Number(v)>=0?'positive':'negative'

export default function HilegaUpstoxSandboxDashboard(){
  const [data,setData]=useState<Data|null>(null)
  const [error,setError]=useState('')
  useEffect(()=>{let active=true;let busy=false;const poll=async()=>{if(!active||busy||document.hidden)return;busy=true;try{const r=await fetch('/api/live-shadow/hilega-upstox-sandbox/dashboard');if(!r.ok)throw new Error('Sandbox dashboard unavailable');const x=await r.json();if(active){setData(x);setError('')}}catch(e){if(active)setError((e as Error).message)}finally{busy=false}};void poll();const id=setInterval(()=>void poll(),5000);return()=>{active=false;clearInterval(id)}},[])
  if(error&&!data)return <section className="panel shadow-panel"><div className="banner error">{error}</div></section>
  if(!data)return <section className="panel shadow-panel"><div className="empty">Loading Upstox Sandbox status…</div></section>
  const p=data.pnl,w=data.worker,a=data.active_trade
  return <div className="hilega-sandbox-dashboard">
    <section className="panel shadow-panel hilega-strategy-identity">
      <div className="panel-heading"><div><div className="eyebrow">ACTIVE SANDBOX STRATEGY</div><h2>{data.strategy.active_strategy_id}</h2><p>{words(data.strategy.mode)} · Armed as {data.strategy.armed_strategy_id}</p></div><span className={`pill ${data.strategy.strategy_match?'teal':''}`}>{data.strategy.strategy_match?'STRATEGY VERIFIED':'RE-ARM REQUIRED'}</span></div>
      <div className="shadow-safety"><b>UPSTOX SANDBOX ONLY</b><span>Live execution disabled</span><span>Worker {w.running?'running':'stopped'}</span><span>{w.armed?'Armed':'Disarmed'} · {w.session_date??'No session'}</span><span>Kill switch {w.kill_switch?'ON':'OFF'}</span></div>
    </section>

    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>Continuous sandbox P&amp;L</h2><p>{data.warning}</p></div><span className="pill teal">REFRESHED {t(data.last_refresh)}</span></div>
      <div className="shadow-metrics hilega-dashboard-summary">
        <article><span>Total estimated P&amp;L</span><b className={cls(p.total_estimated_rupees)}>{money(p.total_estimated_rupees)}</b><small>Closed + current open estimate</small></article>
        <article><span>Open estimated P&amp;L</span><b className={cls(p.open_estimated_rupees)}>{money(p.open_estimated_rupees)}</b><small>{a?'One active sandbox trade':'No active trade'}</small></article>
        <article><span>Closed estimated P&amp;L</span><b className={cls(p.closed_estimated_rupees)}>{money(p.closed_estimated_rupees)}</b><small>Completed sandbox trades</small></article>
        <article><span>Gain / loss ratio</span><b>{n(p.gain_loss_ratio,3)}</b><small>Gross profit {money(p.gross_profit_rupees)} · loss {money(p.gross_loss_rupees)}</small></article>
        <article><span>Wins / losses</span><b>{p.wins??0} / {p.losses??0}</b><small>Win rate {p.win_rate_pct==null?'—':`${n(p.win_rate_pct)}%`}</small></article>
        <article><span>Orders</span><b>{w.accepted_orders??0} / {w.max_orders??0}</b><small>{w.orders_remaining??0} remaining</small></article>
      </div>
    </section>

    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>Current active sandbox trade</h2><p>Entry, current option quote and estimated position P&amp;L.</p></div><span className="pill teal">{a?'OPEN':'NO ACTIVE TRADE'}</span></div>
      {!a?<div className="empty">No active Upstox Sandbox trade.</div>:<div className="shadow-detail-grid">
        <span>Trade <b>{a.trade_id}</b></span><span>Direction <b>{a.direction} · {a.option_type}</b></span><span>Contract <b>{n(a.strike,0)} {a.option_type}</b><small>{a.expiry} · {a.instrument_key}</small></span><span>Quantity <b>{a.quantity}</b></span>
        <span>Entry signal <b>{t(a.entry_signal_time)}</b></span><span>Order submitted <b>{t(a.entry_time)}</b></span><span>Entry order <b>{a.entry_order_id??'—'}</b></span><span>Entry reference <b>{n(a.entry_reference_price)}</b></span><span>Current option LTP <b>{n(a.current_option_ltp)}</b><small>{t(a.quote_timestamp)}</small></span><span>Estimated points <b className={cls(a.estimated_points)}>{n(a.estimated_points)}</b></span><span>Estimated P&amp;L <b className={cls(a.estimated_pnl_rupees)}>{money(a.estimated_pnl_rupees)}</b></span>
      </div>}
    </section>

    <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Completed sandbox trades</h2><p>Entry and exit are joined by the immutable Hilega trade ID.</p></div><span className="pill teal">{data.completed_trades.length} CLOSED</span></div>
      {!data.completed_trades.length?<div className="empty">No completed sandbox trades.</div>:<div className="shadow-table-scroll"><table className="shadow-table"><thead><tr><th>Trade</th><th>Direction</th><th>Contract</th><th>Entry time / price</th><th>Exit time / price</th><th>Qty</th><th>Estimated pts</th><th>Estimated P&amp;L</th><th>Orders</th></tr></thead><tbody>{data.completed_trades.map(x=><tr key={x.trade_id}><td>{x.trade_id}</td><td>{x.direction}</td><td>{n(x.strike,0)} {x.option_type}<small>{x.expiry}</small></td><td>{t(x.entry_time)}<small>{n(x.entry_reference_price)}</small></td><td>{t(x.exit_time)}<small>{n(x.exit_reference_price)}</small></td><td>{x.quantity}</td><td className={cls(x.estimated_points)}>{n(x.estimated_points)}</td><td className={cls(x.estimated_pnl_rupees)}>{money(x.estimated_pnl_rupees)}</td><td>{x.entry_order_id}<small>{x.exit_order_id}</small></td></tr>)}</tbody></table></div>}
    </section>

    <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Blocked and failed sandbox events</h2><p>Nothing is silently treated as a trade.</p></div><span className="pill">{data.blocked_events.length}</span></div>{!data.blocked_events.length?<div className="empty">No blocked or failed events for this session.</div>:<pre>{JSON.stringify(data.blocked_events,null,2)}</pre>}</section>
  </div>
}
