import {useEffect,useMemo,useState} from 'react'

type Leg={
  relation_to_atm:number|null
  strike:number|null
  side:string
  instrument_key:string
  entry_timestamp:string|null
  entry_open:number|null
  latest_close:number|null
  current_points:number|null
  current_return_pct:number|null
  mfe_points:number|null
  mae_points:number|null
  exit_timestamp:string|null
  exit_open:number|null
  realized_points:number|null
  realized_return_pct:number|null
}
type Trade={
  direction:'BULLISH'|'BEARISH'|string
  option_side:'CE'|'PE'|string
  signal_bar:string|null
  signal_boundary:string|null
  signal_spot:number|null
  source:string|null
  expiry:string|null
  atm:number|null
  status:string
  complete:boolean
  issue:string|null
  exit_reason:string|null
  legs:Leg[]
}
type Dashboard={
  model:string
  session_date:string
  directional_trade_count:number
  trade_count:number
  active_count:number
  complete_closed_count:number
  pending_exit_count:number
  incomplete_count:number
  accepted_bullish_trades:number
  accepted_bearish_trades:number
  warning:string
  coverage_note:string
  trades:Trade[]
}

const tm=(v:string|null|undefined)=>v?new Date(v).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false,hour:'2-digit',minute:'2-digit'}):'—'
const num=(v:any,d=2)=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:d})
const words=(v:any)=>v==null?'—':String(v).replaceAll('_',' ')
const signed=(v:number|null|undefined)=>v==null?'—':`${v>0?'+':''}${num(v)}`
const role=(r:number|null)=>r==null?'—':r===0?'ATM':`ATM${r>0?'+':''}${r}`

export default function HilegaDirectionalReplayTrades({sessionDate}:{sessionDate:string}){
  const [data,setData]=useState<Dashboard|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)

  useEffect(()=>{
    let active=true
    if(!sessionDate){setData(null);return}
    const run=async()=>{
      setBusy(true);setError('')
      try{
        const r=await fetch(`/api/live-shadow/hilega-historical/directional-dashboard?session_date=${encodeURIComponent(sessionDate)}`)
        if(!r.ok)throw new Error(`Directional dashboard HTTP ${r.status}: ${await r.text()}`)
        const body=await r.json() as Dashboard
        if(active)setData(body)
      }catch(e){
        if(active){setData(null);setError(String(e))}
      }finally{if(active)setBusy(false)}
    }
    void run()
    return()=>{active=false}
  },[sessionDate])

  const activeTrades=useMemo(()=>data?.trades.filter(t=>String(t.status).toUpperCase()==='ACTIVE')??[],[data])
  const exitedTrades=useMemo(()=>data?.trades.filter(t=>String(t.status).toUpperCase()!=='ACTIVE')??[],[data])

  if(!sessionDate)return null
  if(busy)return <section className="panel shadow-panel"><div className="empty">Loading directional option shadow trades…</div></section>
  if(error)return <section className="panel shadow-panel"><div className="hilega-dashboard-warning">{error}</div></section>
  if(!data)return null

  const table=(t:Trade,closed:boolean)=>{
    const side=t.option_side
    return <div className="shadow-table-scroll"><table className="shadow-table hilega-economics-table">
      <thead><tr>
        <th>{side}</th><th>Entry time</th><th>Entry premium</th>
        {closed&&<><th>Exit time</th><th>Exit premium</th><th>Realized pts</th><th>Realized %</th></>}
        {!closed&&<><th>Latest premium</th><th>Current pts</th><th>Current %</th></>}
        <th>MFE</th><th>MAE</th>
      </tr></thead>
      <tbody>{t.legs.map((l,i)=><tr key={l.instrument_key||`${t.signal_bar}-${i}`}>
        <td>{role(l.relation_to_atm)} · {num(l.strike,0)} {side}</td>
        <td>{tm(l.entry_timestamp)}</td><td>{num(l.entry_open)}</td>
        {closed&&<><td>{tm(l.exit_timestamp)}</td><td>{num(l.exit_open)}</td>
          <td className={l.realized_points==null?'':l.realized_points>=0?'positive':'negative'}>{signed(l.realized_points)}</td>
          <td>{l.realized_return_pct==null?'—':`${signed(l.realized_return_pct)}%`}</td></>}
        {!closed&&<><td>{num(l.latest_close)}</td>
          <td className={l.current_points==null?'':l.current_points>=0?'positive':'negative'}>{signed(l.current_points)}</td>
          <td>{l.current_return_pct==null?'—':`${signed(l.current_return_pct)}%`}</td></>}
        <td>{num(l.mfe_points)}</td><td>{num(l.mae_points)}</td>
      </tr>)}</tbody>
    </table></div>
  }

  const card=(t:Trade,closed:boolean)=><article className="hilega-trade-card" key={`${t.direction}-${t.signal_bar}-${t.option_side}`}>
    <div className="hilega-trade-head"><div>
      <b>{words(t.direction)} · {t.option_side}</b> · {words(t.source)}
      <span className="shadow-stage">{words(t.status)}</span>
      <small>
        Signal {tm(t.signal_bar)} · Entry {tm(t.signal_boundary||t.legs[0]?.entry_timestamp)}
        {' · '}Expiry {t.expiry??'—'} · ATM {num(t.atm,0)} · Signal NIFTY {num(t.signal_spot)}
        {closed&&<> · Exit {tm(t.legs[0]?.exit_timestamp)} · Reason {words(t.exit_reason)}</>}
      </small>
    </div></div>
    {t.issue&&<div className="hilega-dashboard-warning">Data limitation: {t.issue}</div>}
    {t.legs.length?table(t,closed):<div className="empty">No exact option-leg lifecycle recorded for this accepted directional trade.</div>}
  </article>

  return <>
    <div className="shadow-metrics hilega-dashboard-summary">
      <article><span>Directional trades</span><b>{data.directional_trade_count??data.trade_count}</b><small>Accepted coordinator entries</small></article>
      <article><span>Bullish / CE</span><b>{data.accepted_bullish_trades}</b><small>Historical directional replay</small></article>
      <article><span>Bearish / PE</span><b>{data.accepted_bearish_trades}</b><small>Historical directional replay</small></article>
      <article><span>Complete lifecycles</span><b>{data.complete_closed_count}</b><small>{data.incomplete_count} incomplete · {data.pending_exit_count} pending exact exit</small></article>
    </div>

    <section className="panel shadow-panel">
      <div className="panel-heading"><div>
        <h2>Active option shadow trade</h2>
        <p>Same directional presentation as live shadow: bullish uses CE ATM±2; bearish uses PE ATM±2.</p>
      </div><span className="pill teal">{activeTrades.length?`${activeTrades.length} ACTIVE`:'NO ACTIVE TRADE'}</span></div>
      {!activeTrades.length?<div className="empty">No active trade at end-of-session replay.</div>:<div className="hilega-ledger">{activeTrades.map(t=>card(t,false))}</div>}
    </section>

    <section className="panel shadow-panel">
      <div className="panel-heading"><div>
        <h2>Exited option shadow trades</h2>
        <p>Combined accepted bullish CE and bearish PE lifecycles from recorded historical evidence.</p>
      </div><span className="pill teal">{exitedTrades.length} EXITED</span></div>
      <div className="hilega-dashboard-warning">{data.coverage_note}</div>
      {!exitedTrades.length?<div className="empty">No directional option shadow trades recorded for this session.</div>:<div className="hilega-ledger">{exitedTrades.map(t=>card(t,true))}</div>}
    </section>
  </>
}
