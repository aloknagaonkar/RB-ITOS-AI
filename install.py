#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

BACKEND = Path("backend/market_lab/hilega_milega_audit_report_v1.py")
SHADOW = Path("frontend/src/hilegaMilegaShadow.tsx")
TABLE = Path("frontend/src/hilegaDecisionTable.tsx")

BACKEND_OLD = """    if p.get("entry_time") == checkpoint:
        return True
    details = p.get("details") or {}
"""
BACKEND_NEW = """    if p.get("entry_time") == checkpoint:
        return True
    # UNDERLYING_5M_BUILD uses a runtime event timestamp and stores the candle
    # checkpoint in payload.bar_timestamp. Include it in read-only report
    # evidence so the UI can show the actual processing time.
    if p.get("bar_timestamp") == checkpoint:
        return True
    details = p.get("details") or {}
"""

TRADE_TYPE_OLD = """type Trade={signal_bar:string;signal_boundary?:string;signal_spot?:number;source:string|null;expiry:string|null;atm:number|null;status:string;complete:boolean;issue?:string|null;exit_reason?:string|null;legs:TradeLeg[]}"""
TRADE_TYPE_NEW = """type Trade={signal_bar:string;signal_boundary?:string;signal_spot?:number;source:string|null;expiry:string|null;atm:number|null;status:string;complete:boolean;issue?:string|null;exit_reason?:string|null;pending_exit_boundary?:string|null;legs:TradeLeg[]}"""

HELPERS_OLD = """const role=(r:number)=>r===0?'ATM':`ATM${r>0?'+':''}${r}`
const signed=(v:number|null|undefined)=>v==null?'—':`${v>0?'+':''}${num(v)}`
export default function HilegaMilegaShadow(){"""
HELPERS_NEW = """const role=(r:number)=>r===0?'ATM':`ATM${r>0?'+':''}${r}`
const signed=(v:number|null|undefined)=>v==null?'—':`${v>0?'+':''}${num(v)}`
const plusMinutes=(v:string|null|undefined,m:number)=>{
  if(!v)return null
  const ms=new Date(v).getTime()
  return Number.isFinite(ms)?new Date(ms+m*60_000).toISOString():null
}
const candleWindow=(v:string|null|undefined)=>{
  if(!v)return '—'
  return `${tm(v).slice(0,5)}–${tm(plusMinutes(v,5)).slice(0,5)}`
}
const firstLegTime=(t:Trade,key:'entry_timestamp'|'exit_timestamp')=>t.legs.map(l=>l[key]).find(Boolean)??null
export default function HilegaMilegaShadow(){"""

MEMO_OLD = """  const latestEntry=entries[0]??null
  const latestExit=exits[0]??null
  const latestState=String(status?.latest_decision?.payload?.state_after??rows[0]?.strategy.state_after??'NO DATA')
"""
MEMO_NEW = """  const latestEntry=entries[0]??null
  const latestExit=exits[0]??null
  const latestState=String(status?.latest_decision?.payload?.state_after??rows[0]?.strategy.state_after??'NO DATA')
  const activeTrades=useMemo(()=>dashboard?.trades.filter(t=>String(t.status).toUpperCase()==='ACTIVE')??[],[dashboard])
  const exitedTrades=useMemo(()=>dashboard?.trades.filter(t=>String(t.status).toUpperCase()!=='ACTIVE')??[],[dashboard])
"""

OLD_SECTIONS = """    <section className="panel shadow-panel">
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
"""

ACTIVE_SECTION = """    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>Active CE shadow trade</h2><p>Only the currently active bullish CE observation is shown here. It disappears after strategy exit.</p></div><span className="pill teal">{activeTrades.length?`${activeTrades.length} ACTIVE`:'NO ACTIVE TRADE'}</span></div>
      {!dashboard?<div className="empty">Loading active trade…</div>:!activeTrades.length?<div className="empty">No active CE shadow trade.</div>:<div className="hilega-ledger">
        {activeTrades.map(t=>{
          const isOpen=expanded===t.signal_bar
          const entryTime=firstLegTime(t,'entry_timestamp')
          return <article className="hilega-trade-card" key={t.signal_bar}>
            <div className="hilega-trade-head"><div>
              <b>Signal candle {candleWindow(t.signal_bar)}</b> · {words(t.source)} <span className="shadow-stage">ACTIVE</span>
              <small>Decision boundary {tm(t.signal_boundary??plusMinutes(t.signal_bar,5))} · CE entry {tm(entryTime)} · Expiry {t.expiry??'—'} · ATM {num(t.atm,0)} · Signal NIFTY {num(t.signal_spot)}</small>
            </div><button onClick={()=>void openTradeAudit(t.signal_bar)}>{isOpen?'Hide audit':'Audit ▾'}</button></div>
            {t.issue&&<div className="hilega-dashboard-warning">Data limitation: {t.issue}</div>}
            {t.legs.length>0&&<div className="shadow-table-scroll"><table className="shadow-table hilega-economics-table"><thead><tr><th>CE</th><th>Entry time</th><th>Entry premium</th><th>Latest premium</th><th>Current pts</th><th>Current %</th><th>MFE</th><th>MAE</th></tr></thead><tbody>{t.legs.map(l=><tr key={l.instrument_key}><td>{role(l.relation_to_atm)} · {num(l.strike,0)} CE</td><td>{tm(l.entry_timestamp)}</td><td>{num(l.entry_open)}</td><td>{num(l.latest_close)}</td><td className={l.current_points==null?'':l.current_points>=0?'positive':'negative'}>{signed(l.current_points)}</td><td>{l.current_return_pct==null?'—':`${signed(l.current_return_pct)}%`}</td><td>{num(l.mfe_points)}</td><td>{num(l.mae_points)}</td></tr>)}</tbody></table></div>}
            {isOpen&&<div className="hilega-inline-audit"><h3>Full detailed audit · {t.signal_bar}</h3>{auditLoading&&<p>Refreshing detailed audit…</p>}{detail&&<AuditDetail r={detail}/>}</div>}
          </article>
        })}
      </div>}
    </section>
"""

EXIT_SECTION = """    <section className="panel shadow-panel">
      <div className="panel-heading"><div><h2>Exited CE shadow trades</h2><p>Completed and pending-exact-exit observations. Each ATM±2 CE remains an independent shadow observation.</p></div><span className="pill teal">{exitedTrades.length} EXITED</span></div>
      {!dashboard?<div className="empty">Loading exited trades…</div>:!exitedTrades.length?<div className="empty">No exited CE shadow trades yet.</div>:<div className="hilega-ledger">
        {exitedTrades.map(t=>{
          const isOpen=expanded===t.signal_bar
          const entryTime=firstLegTime(t,'entry_timestamp')
          const exitTime=firstLegTime(t,'exit_timestamp')
          return <article className="hilega-trade-card" key={t.signal_bar}>
            <div className="hilega-trade-head"><div>
              <b>Signal candle {candleWindow(t.signal_bar)}</b> · {words(t.source)} <span className="shadow-stage">{words(t.status)}</span>
              <small>Decision boundary {tm(t.signal_boundary??plusMinutes(t.signal_bar,5))} · CE entry {tm(entryTime)} · CE exit {tm(exitTime)} · Expiry {t.expiry??'—'} · ATM {num(t.atm,0)} · Signal NIFTY {num(t.signal_spot)} · Exit reason {words(t.exit_reason)}</small>
            </div><button onClick={()=>void openTradeAudit(t.signal_bar)}>{isOpen?'Hide audit':'Audit ▾'}</button></div>
            {String(t.status).toUpperCase()==='PENDING_EXACT_EXIT'&&<div className="hilega-dashboard-warning">Underlying strategy has exited. Awaiting the exact causal CE exit-minute OPEN at {tm(t.pending_exit_boundary)}. Realized premium points remain unavailable until exact prices are recorded.</div>}
            {t.issue&&<div className="hilega-dashboard-warning">Data limitation: {t.issue}</div>}
            {t.legs.length>0&&<div className="shadow-table-scroll"><table className="shadow-table hilega-economics-table"><thead><tr><th>CE</th><th>Entry time</th><th>Entry premium</th><th>Exit time</th><th>Exit premium</th><th>Realized pts</th><th>Realized %</th><th>MFE</th><th>MAE</th></tr></thead><tbody>{t.legs.map(l=><tr key={l.instrument_key}><td>{role(l.relation_to_atm)} · {num(l.strike,0)} CE</td><td>{tm(l.entry_timestamp)}</td><td>{num(l.entry_open)}</td><td>{tm(l.exit_timestamp)}</td><td>{num(l.exit_open)}</td><td className={l.realized_points==null?'':l.realized_points>=0?'positive':'negative'}>{signed(l.realized_points)}</td><td>{l.realized_return_pct==null?'—':`${signed(l.realized_return_pct)}%`}</td><td>{num(l.mfe_points)}</td><td>{num(l.mae_points)}</td></tr>)}</tbody></table></div>}
            {isOpen&&<div className="hilega-inline-audit"><h3>Full detailed audit · {t.signal_bar}</h3>{auditLoading&&<p>Refreshing detailed audit…</p>}{detail&&<AuditDetail r={detail}/>}</div>}
          </article>
        })}
      </div>}
    </section>
"""

CANDLE_SECTION_END = """      <HilegaDecisionTable reports={rows as HilegaAudit[]} mode="LIVE"
        fetchDetail={detailedAudit}
        emptyMessage="No completed live strategy checkpoints available yet." />
    </section>
  </div>
}"""
CANDLE_SECTION_END_NEW = """      <HilegaDecisionTable reports={rows as HilegaAudit[]} mode="LIVE"
        fetchDetail={detailedAudit}
        emptyMessage="No completed live strategy checkpoints available yet." />
    </section>
""" + EXIT_SECTION + """  </div>
}"""

TABLE_HELPER_OLD = """export const shortDateTime = (x:any) => {
  if(!x)return '—'
  const d=new Date(String(x))
  if(Number.isNaN(d.getTime()))return String(x)
  const parts=new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).formatToParts(d)
  const get=(t:string)=>parts.find(x=>x.type===t)?.value??''
  return `${get('month')}/${get('day')} ${get('hour')}:${get('minute')}`
}
"""

TABLE_HELPER_NEW = TABLE_HELPER_OLD + """
const candleTiming=(r:HilegaAudit)=>{
  const start=new Date(String(r.checkpoint))
  if(Number.isNaN(start.getTime()))return {window:shortDateTime(r.checkpoint),processed:null as string|null,label:null as string|null}
  const end=new Date(start.getTime()+5*60_000)
  const day=new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',month:'2-digit',day:'2-digit'}).format(start)
  const hm=(d:Date)=>d.toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false,hour:'2-digit',minute:'2-digit'})
  const hms=(x:any)=>{
    if(!x)return null
    const d=new Date(String(x))
    return Number.isNaN(d.getTime())?null:d.toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'})
  }
  const records=list(r.audit_integrity?.records)
  const processed=records.find((x:any)=>x.stage==='UNDERLYING_5M_BUILD')
  const recovered=records.find((x:any)=>x.stage==='BOOTSTRAP_RECOVERED_CHECKPOINT')
  return {
    window:`${day} ${hm(start)}–${hm(end)}`,
    processed:hms(processed?.event_time??recovered?.event_time),
    label:processed?'processed':recovered?'recovered':null,
  }
}
"""

TABLE_RENDER_OLD = """        return <Fragment key={r.checkpoint}><tr className={`hd-row hd-${k.toLowerCase()}`}><td>{shortDateTime(r.checkpoint)}</td><td><strong>{shortRuleText(r,k,lifecycleIssue)}</strong>{lifecycleIssue&&<small className="hd-lifecycle-issue">{lifecycleIssue}</small>}</td><td className={color(niftyPoints)}>{niftyPoints===null?'—':`${niftyPoints>0?'+':''}${money(niftyPoints)} pts`}</td><td>{pathText(r,originRoute??undefined)}</td><td><span className={`hd-badge hd-${k.toLowerCase()}`}>{badge}</span></td><td><button aria-expanded={opened} aria-label={`Audit ${r.checkpoint}`} onClick={()=>void toggle(row)}>{opened?'Hide audit':'View audit ▾'}</button></td></tr>"""

TABLE_RENDER_NEW = """        const timing=candleTiming(r)
        return <Fragment key={r.checkpoint}><tr className={`hd-row hd-${k.toLowerCase()}`}><td><span>{timing.window}</span>{timing.processed&&<small>{timing.label} {timing.processed}</small>}</td><td><strong>{shortRuleText(r,k,lifecycleIssue)}</strong>{lifecycleIssue&&<small className="hd-lifecycle-issue">{lifecycleIssue}</small>}</td><td className={color(niftyPoints)}>{niftyPoints===null?'—':`${niftyPoints>0?'+':''}${money(niftyPoints)} pts`}</td><td>{pathText(r,originRoute??undefined)}</td><td><span className={`hd-badge hd-${k.toLowerCase()}`}>{badge}</span></td><td><button aria-expanded={opened} aria-label={`Audit ${r.checkpoint}`} onClick={()=>void toggle(row)}>{opened?'Hide audit':'View audit ▾'}</button></td></tr>"""

def replace_once(text, old, new, label):
    if new in text:
        return text, False
    if old not in text:
        raise RuntimeError(f"BLOCKED: expected block not found: {label}")
    return text.replace(old,new,1), True

def main():
    ap=argparse.ArgumentParser(description="Hilega active/exited trade UI + candle timing patch")
    ap.add_argument("--repo",required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=ap.parse_args()
    repo=Path(a.repo).resolve()
    bp,sp,tp=repo/BACKEND,repo/SHADOW,repo/TABLE
    for p in (bp,sp,tp):
        if not p.is_file():
            print("BLOCKED: missing",p.relative_to(repo)); raise SystemExit(2)
    try:
        b=bp.read_text(encoding="utf-8")
        s=sp.read_text(encoding="utf-8")
        t=tp.read_text(encoding="utf-8")
        b,b1=replace_once(b,BACKEND_OLD,BACKEND_NEW,"backend runtime processing evidence")
        s,s1=replace_once(s,TRADE_TYPE_OLD,TRADE_TYPE_NEW,"trade type")
        s,s2=replace_once(s,HELPERS_OLD,HELPERS_NEW,"trade timing helpers")
        s,s3=replace_once(s,MEMO_OLD,MEMO_NEW,"active/exited trade selectors")
        s,s4=replace_once(s,OLD_SECTIONS,ACTIVE_SECTION,"replace old dashboard+ledger with active trade")
        s,s5=replace_once(s,CANDLE_SECTION_END,CANDLE_SECTION_END_NEW,"append exited trade section at bottom")
        t,t1=replace_once(t,TABLE_HELPER_OLD,TABLE_HELPER_NEW,"candle timing helper")
        t,t2=replace_once(t,TABLE_RENDER_OLD,TABLE_RENDER_NEW,"candle timing render")
    except RuntimeError as e:
        print(e); print("No files changed."); raise SystemExit(2)

    changed=any((b1,s1,s2,s3,s4,s5,t1,t2))
    if not changed:
        print("ALREADY_PATCHED"); return

    print("READY")
    print("  - removes Shadow premium P&L dashboard")
    print("  - removes combined CE entry/exit ledger")
    print("  - Active CE shadow trade shows only ACTIVE trades")
    print("  - exited/pending-exact-exit trades move to bottom section")
    print("  - candle column shows 5m window plus actual processed/recovered time when recorded")
    print("  - backend report only links UNDERLYING_5M_BUILD evidence; strategy/execution unchanged")
    if a.check:
        print("CHECK PASS"); return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root=repo/".hilega-active-exit-ui-backup"/stamp
    for rel,p in ((BACKEND,bp),(SHADOW,sp),(TABLE,tp)):
        dst=root/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dst)
    bp.write_text(b,encoding="utf-8"); sp.write_text(s,encoding="utf-8"); tp.write_text(t,encoding="utf-8")
    print("APPLY PASS")
    print("Backup:",root)
    print("Backend reporting source changed: run tests/build, then restart API only. Do NOT restart live-shadow worker.")

if __name__=="__main__":
    main()
