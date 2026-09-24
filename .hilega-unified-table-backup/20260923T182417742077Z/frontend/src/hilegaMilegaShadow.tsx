import { Fragment, useEffect, useMemo, useState } from 'react'

type AuditReport = {
  checkpoint:string
  mode:string
  strategy:{state_before:string|null;state_after:string|null;selected_route:string|null;route_b_suppressed_by_route_a_priority:boolean|null;events_emitted:string[]}
  bar:{open:number|null;high:number|null;low:number|null;close:number|null;volume:number|null}
  indicators:{rsi9:number|null;ema3_rsi:number|null;wma21_rsi:number|null;previous_rsi9:number|null;previous_ema3_rsi:number|null;previous_wma21_rsi:number|null}
  conditions:Record<string,boolean|null>
  route_a:{eligible:boolean|null;pass:boolean|null;fail_reasons:string[]}
  route_b:{eligible:boolean|null;pass:boolean|null;fail_reasons:string[]}
  transitions:Array<Record<string,any>>
  option_candidate:Record<string,any>|null
  option_market_snapshot:Record<string,any>|null
  option_lifecycle:{start:Record<string,any>|null;updates:Array<Record<string,any>>;exit:Record<string,any>|null}
  audit_integrity:{chain_ok:boolean|null;chain_issue:string|null;records:Array<Record<string,any>>}
  safety:{observation_only:boolean;execution_enabled:boolean;paper_order_enabled:boolean}
}

type Status = {
  observation_only:boolean
  execution_enabled:boolean
  paper_order_enabled:boolean
  step_audit_chain_ok:boolean
  step_audit_chain_issue:string|null
  latest_decision:Record<string,any>|null
  latest_option_shadow:Record<string,any>|null
}

const base='/api/live-shadow/hilega-milega'
const get=async<T,>(path:string):Promise<T>=>{
  const r=await fetch(base+path)
  if(!r.ok){const e=await r.json().catch(()=>null);throw new Error(e?.detail||'Hilega-Milega request failed')}
  return r.json()
}
const tm=(v:string|null|undefined)=>v?new Date(v).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const dt=(v:string|null|undefined)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const num=(v:any,d=2)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:d})
const words=(v:any)=>v==null?'—':String(v).replaceAll('_',' ')
const yn=(v:any)=>v==null?'NA':v?'YES':'NO'
const isEntry=(x:any)=>String(x?.event_type??'').startsWith('ENTRY_')
const isExit=(x:any)=>String(x?.event_type??'').includes('EXIT')
const firstEntry=(r:AuditReport)=>r.transitions.find(isEntry)??null
const firstExit=(r:AuditReport)=>r.transitions.find(isExit)??null
const lifecycleState=(r:AuditReport)=>r.option_lifecycle.exit?.status??r.option_lifecycle.updates.at(-1)?.status??r.option_lifecycle.start?.status??null

function AuditDetail({r}:{r:AuditReport}){
  const legs=(r.option_lifecycle.exit?.legs??r.option_lifecycle.updates.at(-1)?.legs??r.option_lifecycle.start?.legs??[]) as any[]
  const entry=firstEntry(r)
  const exit=firstExit(r)
  return <div className="hilega-audit-body">
    <div className="shadow-detail-grid" style={{gridTemplateColumns:'repeat(auto-fit,minmax(210px,1fr))'}}>
      <span>Checkpoint <b>{dt(r.checkpoint)}</b></span><span>Route <b>{words(r.strategy.selected_route)}</b></span>
      <span>State <b>{words(r.strategy.state_before)} → {words(r.strategy.state_after)}</b></span>
      <span>Entry <b>{entry?`${num(entry.price)} @ ${tm(entry.event_time??r.checkpoint)}`:'—'}</b><small>{entry?words(entry.source??entry.event_type):'No entry at this checkpoint'}</small></span>
      <span>Exit <b>{exit?`${num(exit.price)} @ ${tm(exit.event_time??r.checkpoint)}`:'—'}</b><small>{exit?words(exit.exit_reason??exit.source??exit.event_type):'No exit at this checkpoint'}</small></span>
      <span>Close <b>{num(r.bar.close)}</b></span>
      <span>RSI9 <b>{num(r.indicators.rsi9)}</b></span><span>EMA3 RSI <b>{num(r.indicators.ema3_rsi)}</b></span><span>WMA21 RSI <b>{num(r.indicators.wma21_rsi)}</b></span>
      <span>Previous RSI9 <b>{num(r.indicators.previous_rsi9)}</b></span><span>Previous EMA3 RSI <b>{num(r.indicators.previous_ema3_rsi)}</b></span><span>Previous WMA21 RSI <b>{num(r.indicators.previous_wma21_rsi)}</b></span>
      <span>RSI↑EMA <b>{yn(r.conditions.rsi_cross_ema_up)}</b></span><span>RSI↓WMA <b>{yn(r.conditions.rsi_cross_wma_down)}</b></span><span>RSI&gt;50 <b>{yn(r.conditions.rsi_gt_50)}</b></span>
      <span>RSI&gt;WMA <b>{yn(r.conditions.rsi_gt_wma)}</b></span><span>EMA&gt;WMA <b>{yn(r.conditions.ema_gt_wma)}</b></span><span>RSI rising <b>{yn(r.conditions.rsi_rising)}</b></span><span>EMA rising <b>{yn(r.conditions.ema_rising)}</b></span>
      <span>Route A <b>{yn(r.route_a.pass)}</b><small>{r.route_a.fail_reasons.join(', ')||'No failures'}</small></span>
      <span>Route B <b>{yn(r.route_b.pass)}</b><small>{r.route_b.fail_reasons.join(', ')||'No failures'}</small></span>
      <span>A priority <b>{yn(r.strategy.route_b_suppressed_by_route_a_priority)}</b></span>
      <span>Expiry <b>{String(r.option_candidate?.expiry??'—')}</b></span><span>ATM <b>{num(r.option_candidate?.atm,0)}</b></span>
      <span>Candidate status <b>{words(r.option_candidate?.status)}</b></span><span>Market snapshot <b>{words(r.option_market_snapshot?.status)}</b></span>
      <span>Lifecycle <b>{words(lifecycleState(r))}</b></span><span>Audit chain <b>{r.audit_integrity.chain_ok?'HEALTHY':'CHECK'}</b></span>
    </div>
    {legs.length>0&&<div className="hilega-audit-section"><b>ATM±2 CE entry / exit audit — independent shadow observations, not executed P&L</b><div className="shadow-table-scroll"><table className="shadow-table"><thead><tr><th>Role</th><th>Strike</th><th>CE entry price</th><th>CE exit price</th><th>Live premium</th><th>Realized pts</th><th>Realized %</th><th>Unrealized pts</th><th>MFE</th><th>MAE</th></tr></thead><tbody>{legs.map((x:any)=><tr key={x.instrument_key}><td>{x.relation_to_atm===0?'ATM':`ATM${x.relation_to_atm>0?'+':''}${x.relation_to_atm}`}</td><td>{num(x.strike,0)} CE</td><td>{num(x.entry_open)}</td><td>{num(x.exit_open)}</td><td>{num(x.latest_close)}</td><td>{num(x.realized_points)}</td><td>{x.realized_return_pct==null?"—":`${num(x.realized_return_pct)}%`}</td><td>{num(x.current_points)}</td><td>{num(x.mfe_points)}</td><td>{num(x.mae_points)}</td></tr>)}</tbody></table></div></div>}
    <div className="hilega-audit-section"><b>Option data availability</b><p>Only exact causal 1-minute option prices are displayed. Missing values mean unavailable or incomplete, not zero P&L.</p><div className="shadow-detail-grid"><span>Lifecycle issue <b>{String(r.option_lifecycle.exit?.issue??r.option_lifecycle.updates.at(-1)?.issue??r.option_lifecycle.start?.issue??"None recorded")}</b></span><span>Execution <b>DISABLED</b></span><span>Quantity <b>NONE</b></span></div></div><div className="hilega-audit-section"><b>Transitions</b><pre>{JSON.stringify(r.transitions,null,2)}</pre></div>
    <div className="hilega-audit-section"><b>Audit integrity</b><pre>{JSON.stringify(r.audit_integrity,null,2)}</pre></div>
  </div>
}


type TradeLeg={relation_to_atm:number;strike:number;instrument_key:string;entry_timestamp:string|null;entry_open:number|null;latest_close:number|null;current_points:number|null;current_return_pct:number|null;mfe_points:number|null;mae_points:number|null;exit_timestamp:string|null;exit_open:number|null;realized_points:number|null;realized_return_pct:number|null}
type Trade={signal_bar:string;signal_boundary?:string;signal_spot?:number;source:string|null;expiry:string|null;atm:number|null;status:string;complete:boolean;issue?:string|null;exit_reason?:string|null;legs:TradeLeg[]}
type Dashboard={account_pnl_rupees:null;warning:string;measurement:string;trade_count:number;complete_closed_count:number;active_count:number;incomplete_count:number;pending_exit_count?:number;by_role:Array<{role:number;closed_count:number;positive_count:number;total_realized_premium_points:number;mean_return_pct:number|null;open_count:number;missing_count:number}>;trades:Trade[]}
const role=(r:number)=>r===0?'ATM':`ATM${r>0?'+':''}${r}`
const signed=(v:number|null|undefined)=>v==null?'—':`${v>0?'+':''}${num(v)}`
export default function HilegaMilegaShadow(){
  const [status,setStatus]=useState<Status|null>(null)
  const [rows,setRows]=useState<AuditReport[]>([])
  const [dashboard,setDashboard]=useState<Dashboard|null>(null)
  const [expanded,setExpanded]=useState<string|null>(null)
  const [detail,setDetail]=useState<AuditReport|null>(null)
  const [auditLoading,setAuditLoading]=useState(false)
  const [error,setError]=useState('')
  const refresh=async()=>{
    const [s,a,d]=await Promise.all([get<Status>('/status'),get<AuditReport[]>('/audit-index?limit=200'),get<Dashboard>('/trade-dashboard')])
    setStatus(s);setRows(a);setDashboard(d);setError('')
  }
  useEffect(()=>{let active=true;const poll=()=>void refresh().catch(e=>active&&setError((e as Error).message));poll();const t=setInterval(poll,5000);return()=>{active=false;clearInterval(t)}},[])
  const activity=useMemo(()=>rows.filter(r=>r.transitions.length>0||(r.strategy.events_emitted||[]).length>0),[rows])
  const entries=useMemo(()=>activity.flatMap(r=>r.transitions.filter(isEntry).map(t=>({r,t}))),[activity])
  const exits=useMemo(()=>activity.flatMap(r=>r.transitions.filter(isExit).map(t=>({r,t}))),[activity])
  const latestEntry=entries[0]??null
  const latestExit=exits[0]??null
  const latestState=String(status?.latest_decision?.payload?.state_after??rows[0]?.strategy.state_after??'NO DATA')
  const detailBySignal=useMemo(()=>new Map((dashboard?.trades??[]).map(x=>[x.signal_bar,x])),[dashboard])
  const openAudit=async(r:AuditReport)=>{
    if(expanded===r.checkpoint){setExpanded(null);setDetail(null);return}
    setExpanded(r.checkpoint);setDetail(r);setAuditLoading(true)
    try{const response=await get<AuditReport>('/audit-detail?checkpoint='+encodeURIComponent(r.checkpoint));setDetail(response);setError('')}
    catch(e){setError(`Detailed audit failed: ${(e as Error).message}`)}finally{setAuditLoading(false)}
  }
  const openTradeAudit=async(checkpoint:string)=>{
    if(expanded===checkpoint){setExpanded(null);setDetail(null);return}
    const cached=rows.find(r=>r.checkpoint===checkpoint)
    setExpanded(checkpoint);setDetail(cached??null);setAuditLoading(true)
    try{const response=await get<AuditReport>('/audit-detail?checkpoint='+encodeURIComponent(checkpoint));setDetail(response);setError('')}
    catch(e){setError(`Detailed trade audit failed: ${(e as Error).message}`)}finally{setAuditLoading(false)}
  }
  return <div className="shadow-page hilega-page">
    {error&&<div className="banner error">{error}</div>}
    <div className="shadow-safety"><b>HILEGA-MILEGA · OBSERVATION ONLY</b><span>Execution disabled</span><span>Paper orders disabled</span><span>Five independent ATM±2 CE observations</span><span>Audit chain {status?.step_audit_chain_ok?'healthy':'check'}</span></div>
    <div className="shadow-metrics hilega-dashboard-summary">
      <article><span>Strategy state</span><b>{words(latestState)}</b><small>Latest recorded decision</small></article>
      <article><span>Last entry detected</span><b>{latestEntry?tm(latestEntry.t.event_time??latestEntry.r.checkpoint):'—'}</b><small>{latestEntry?`Route ${words(latestEntry.r.strategy.selected_route)} · NIFTY ${num(latestEntry.t.price)}`:'No entry recorded'}</small></article>
      <article><span>Last exit detected</span><b>{latestExit?tm(latestExit.t.event_time??latestExit.r.checkpoint):'—'}</b><small>{latestExit?`${words(latestExit.t.exit_reason??latestExit.t.event_type)} · NIFTY ${num(latestExit.t.price)}`:'No exit recorded'}</small></article>
      <article><span>Completed 5-leg lifecycles</span><b>{dashboard?.complete_closed_count??'—'}</b><small>{dashboard?`${dashboard.active_count} active · ${dashboard.pending_exit_count??0} pending exact exit · ${dashboard.incomplete_count} incomplete`:'Dashboard loading'}</small></article>
    </div>
    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>Shadow premium P&amp;L dashboard</h2><p>Realized option premium points for each CE strike independently. Never a combined portfolio return.</p></div><span className="pill teal">OBSERVATIONAL</span></div>
      {!dashboard?<div className="empty">Loading shadow economics…</div>:<>
        <div className="hilega-dashboard-warning">{dashboard.warning} Account P&amp;L (₹): <b>Not available without an executed quantity and costs.</b></div>
        <div className="shadow-table-scroll"><table className="shadow-table hilega-economics-table"><thead><tr><th>CE role</th><th>Completed trades</th><th>Positive</th><th>Realized premium points</th><th>Mean realized return</th><th>Active</th><th>Unavailable</th></tr></thead><tbody>
          {dashboard.by_role.map(x=><tr key={x.role}><td>{role(x.role)}</td><td>{x.closed_count}</td><td>{x.positive_count}</td><td className={x.closed_count?(x.total_realized_premium_points>=0?'positive':'negative'):''}>{x.closed_count?signed(x.total_realized_premium_points):'—'}</td><td>{x.mean_return_pct==null?'—':`${signed(x.mean_return_pct)}%`}</td><td>{x.open_count}</td><td>{x.missing_count}</td></tr>)}
        </tbody></table></div>
      </>}
    </section>
    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>CE entry / exit trade ledger</h2><p>Audit expands directly below the selected card/row, matching the historical replay interaction.</p></div><span className="pill teal">{dashboard?.trade_count??0} SHADOW SIGNALS</span></div>
      {!dashboard?.trades.length?<div className="empty">No CE shadow starts yet; historical NIFTY entries without exact option data are not assigned option P&amp;L.</div>:<div className="hilega-ledger">
        {dashboard.trades.map(t=>{
          const isOpen=expanded===t.signal_bar
          return <article className="hilega-trade-card" key={t.signal_bar}>
            <div className="hilega-trade-head"><div><b>{dt(t.signal_bar)}</b> · {words(t.source)} <span className="shadow-stage">{words(t.status)}</span><small>Expiry {t.expiry??'—'} · ATM {num(t.atm,0)} · Signal NIFTY {num(t.signal_spot)}</small></div>
              <button onClick={()=>void openTradeAudit(t.signal_bar)}>{isOpen?'Hide audit':'Audit ▾'}</button>
            </div>
            {t.status==='PENDING_EXACT_EXIT'&&<div className="hilega-dashboard-warning">Underlying strategy already exited. Awaiting original exact CE exit-minute OPEN at {tm((t as Trade & {pending_exit_boundary?:string|null}).pending_exit_boundary)}. Realized premium P&amp;L unavailable until all five exact prices are observed; tracking is frozen at the exit boundary.</div>}
            {t.issue&&<div className="hilega-dashboard-warning">Data limitation: {t.issue}</div>}
            {t.legs.length>0&&<div className="shadow-table-scroll"><table className="shadow-table hilega-economics-table"><thead><tr><th>CE</th><th>Entry time</th><th>Entry premium</th><th>Latest premium</th><th>Exit time</th><th>Exit premium</th><th>Realized pts</th><th>Realized %</th><th>Current pts</th><th>MFE</th><th>MAE</th></tr></thead><tbody>{t.legs.map(l=><tr key={l.instrument_key}><td>{role(l.relation_to_atm)} · {num(l.strike,0)} CE</td><td>{tm(l.entry_timestamp)}</td><td>{num(l.entry_open)}</td><td>{num(l.latest_close)}</td><td>{tm(l.exit_timestamp)}</td><td>{num(l.exit_open)}</td><td className={l.realized_points==null?'':l.realized_points>=0?'positive':'negative'}>{signed(l.realized_points)}</td><td>{l.realized_return_pct==null?'—':`${signed(l.realized_return_pct)}%`}</td><td>{signed(l.current_points)}</td><td>{num(l.mfe_points)}</td><td>{num(l.mae_points)}</td></tr>)}</tbody></table></div>}
            {isOpen&&<div className="hilega-inline-audit"><h3>Full detailed audit · {t.signal_bar}</h3>{auditLoading&&<p>Refreshing detailed audit…</p>}{detail&&<AuditDetail r={detail}/>}</div>}
          </article>
        })}
      </div>}
    </section>
    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>Underlying entry / exit activity and decision audit</h2><p>Underlying points are chart-validation observations, not option/account P&amp;L. Click Audit to expand in place.</p></div><span className="pill teal">{activity.length} EVENTS</span></div>
      {!activity.length?<div className="empty">No recorded entry / exit events yet.</div>:<div className="shadow-table-scroll"><table className="shadow-table hilega-activity-table"><thead><tr><th>Time</th><th>Event</th><th>Route</th><th>Underlying</th><th>Exit reason</th><th>Audit</th></tr></thead><tbody>
        {activity.map(r=>{
          const entry=firstEntry(r),exit=firstExit(r),e=entry??exit??r.transitions[0]
          const thisOpen=expanded===r.checkpoint
          const linked=detailBySignal.get(r.checkpoint)
          return <Fragment key={r.checkpoint}><tr><td>{tm(e?.event_time??r.checkpoint)}</td><td>{entry?'ENTRY DETECTED':exit?'EXIT':'STATE CHANGE'}</td><td>{words(r.strategy.selected_route)}</td><td>{num(e?.price??r.bar.close)}</td><td>{exit?words(exit.exit_reason??exit.event_type):'—'}</td><td><button onClick={()=>void openAudit(r)}>{thisOpen?'Hide audit':'Audit ▾'}</button></td></tr>
            {thisOpen&&<tr key={`${r.checkpoint}-audit`} className="hilega-expand-row"><td colSpan={6}><div className="hilega-inline-audit"><h3>Detailed decision audit · {dt(r.checkpoint)}</h3>{linked&&<p>Linked ATM±2 lifecycle: {words(linked.status)} · {linked.legs.length} exact CE legs</p>}{auditLoading&&<p>Refreshing detailed report…</p>}{detail&&<AuditDetail r={detail}/>}</div></td></tr>}
          </Fragment>
        })}
      </tbody></table></div>}
    </section>
  </div>
}
