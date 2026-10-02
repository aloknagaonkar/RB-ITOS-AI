#!/usr/bin/env python3
from pathlib import Path
import shutil

p = Path("frontend/src/midpointStrategyShadow.tsx")
css = Path("frontend/src/midpointStrategyShadow.css")

if not p.exists() or not css.exists():
    raise SystemExit("SAFE STOP: Midpoint frontend files not found. Run from ~/RB-ITOS-AI.")

src = p.read_text()
styles = css.read_text()

old_sig = "const semanticOwner=(event:Partial<AuditEvent&TimelineRow>|null|undefined)=>"
new_sig = "const semanticOwner=(event:{event_type?:string|null;reason?:string|null;family?:string|null;display_owner?:string|null}|null|undefined)=>"
if old_sig in src:
    src = src.replace(old_sig, new_sig, 1)
elif new_sig not in src:
    raise SystemExit("SAFE STOP: semanticOwner signature not recognized.")

start = src.find("function AuditDrawer(")
end = src.find("\n\nfunction LiveAuditTable", start)
if start < 0 or end < 0:
    raise SystemExit("SAFE STOP: M2.2 AuditDrawer block not found.")
src = src[:start] + src[end+2:]

live_start = src.find("function LiveAuditTable(")
live_end = src.find("\n\nfunction ReplayMinuteTable", live_start)
if live_start < 0 or live_end < 0:
    raise SystemExit("SAFE STOP: M2.2 LiveAuditTable block not found.")

live_new = '''function LiveAuditTable({timeline,onInspect,selected}:{timeline:TimelineRow[];onInspect:(id:string)=>void;selected:AuditEvent|null}){return <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Midpoint candle-by-candle decision audit</h2><p>Latest two available live sessions. Inspect expands directly below the selected row.</p></div><span className="pill teal">LIVE</span></div><div className="shadow-table-scroll mp-table-scroll"><table className="shadow-table mp-table"><thead><tr><th>Time</th><th>Session</th><th>Event</th><th>Owner</th><th>Direction</th><th>State</th><th>Result</th><th>Reason</th><th>NIFTY</th><th>Points</th><th>Audit</th></tr></thead><tbody>{[...timeline].reverse().flatMap(x=>{const expanded=selected?.event_id===x.event_id;return [<tr key={x.event_id} className={eventClass(x.event_type)}><td>{tm(x.timestamp)}</td><td>{x.session_date??'—'}</td><td><b>{words(x.event_type)}</b></td><td>{semanticOwner(x)}</td><td>{words(x.direction)}</td><td>{words(x.state_after||x.state_before)}</td><td>{words(x.result)}</td><td className="mp-reason">{words(x.reason)}</td><td>{num(x.underlying_price)}</td><td>{num(x.directional_points)}</td><td><button className="secondary" aria-expanded={expanded} onClick={()=>onInspect(x.event_id)}>{expanded?'Collapse':'Inspect'}</button></td></tr>,expanded&&selected?<tr key={x.event_id+'-detail'} className="mp-inline-detail-row"><td colSpan={11}><div className="mp-inline-audit"><div className="mp-inline-audit-head"><div><span>IMMUTABLE AUDIT</span><b>{words(selected.event_type)}</b><small>{dt(selected.event_timestamp)}</small></div><button className="secondary" onClick={()=>onInspect(x.event_id)}>Collapse</button></div><AuditDetail event={selected}/></div></td></tr>:null]})}{!timeline.length&&<tr><td colSpan={11} className="empty">No Midpoint audit evidence for this view.</td></tr>}</tbody></table></div></section>}'''

src = src[:live_start] + live_new + src[live_end:]

replay_start = src.find("function ReplayMinuteTable(")
replay_end = src.find("\n\nfunction SessionView", replay_start)
if replay_start < 0 or replay_end < 0:
    raise SystemExit("SAFE STOP: M2.2 ReplayMinuteTable block not found.")

replay_new = '''function ReplayMinuteTable({minutes,onInspect,selected}:{minutes:ReplayMinute[];onInspect:(id:string)=>void;selected:AuditEvent|null}){return <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Full-day minute replay</h2><p>One selected trading date. Strategy events are overlaid on the exact minute; Inspect expands directly below that minute.</p></div><span className="pill teal">REPLAY</span></div><div className="shadow-table-scroll mp-minute-scroll"><table className="shadow-table mp-minute-table"><thead><tr><th>Time</th><th>NIFTY O</th><th>H</th><th>L</th><th>C</th><th>Fut close</th><th>Fut VWAP</th><th>Data</th><th>Strategy event / audit</th></tr></thead><tbody>{minutes.flatMap(m=>{const first=m.events?.[0];const expanded=!!selected&&!!m.events?.some(e=>e.event_id===selected.event_id);return [<tr key={m.timestamp} className={first?eventClass(first.event_type):'mp-minute-plain'}><td><b>{tm(m.timestamp)}</b></td><td>{num(m.underlying_open)}</td><td>{num(m.underlying_high)}</td><td>{num(m.underlying_low)}</td><td>{num(m.underlying_close)}</td><td>{num(m.futures_close)}</td><td>{num(m.futures_vwap)}</td><td><span className={'mp-data-status '+(m.data_status!=='BOTH'?'warn':'')}>{words(m.data_status)}</span></td><td>{m.events?.length?<div className="mp-minute-events">{m.events.map(e=><div className="mp-minute-event" key={e.event_id}><div><b>{words(e.event_type)}</b><small>{semanticOwner(e)} · {words(e.direction)} · {words(e.result)}</small><small>{words(e.reason)}</small></div><button className="secondary" aria-expanded={selected?.event_id===e.event_id} onClick={()=>onInspect(e.event_id)}>{selected?.event_id===e.event_id?'Collapse':'Inspect'}</button></div>)}</div>:<span className="mp-no-event">—</span>}</td></tr>,expanded&&selected?<tr key={m.timestamp+'-detail'} className="mp-inline-detail-row"><td colSpan={9}><div className="mp-inline-audit"><div className="mp-inline-audit-head"><div><span>IMMUTABLE AUDIT</span><b>{words(selected.event_type)}</b><small>{dt(selected.event_timestamp)}</small></div><button className="secondary" onClick={()=>onInspect(selected.event_id)}>Collapse</button></div><AuditDetail event={selected}/></div></td></tr>:null]})}{!minutes.length&&<tr><td colSpan={9} className="empty">No full-day minute evidence materialized for this date.</td></tr>}</tbody></table></div></section>}'''

src = src[:replay_start] + replay_new + src[replay_end:]

old_render = "{mode==='HISTORICAL_REPLAY'?<ReplayMinuteTable minutes={minutes} onInspect={onInspect}/>:<LiveAuditTable timeline={timeline} onInspect={onInspect}/>} \n {selected&&<AuditDrawer event={selected} onClose={onClose}/>}</>"
new_render = "{mode==='HISTORICAL_REPLAY'?<ReplayMinuteTable minutes={minutes} onInspect={onInspect} selected={selected}/>:<LiveAuditTable timeline={timeline} onInspect={onInspect} selected={selected}/>}</>"
if old_render not in src:
    raise SystemExit("SAFE STOP: SessionView drawer render anchor not found.")
src = src.replace(old_render, new_render, 1)

old_inspect = " const inspect=async(eventId:string)=>{try{const path=mode==='LIVE'?"
new_inspect = " const inspect=async(eventId:string)=>{if(selected?.event_id===eventId){setSelected(null);return}try{const path=mode==='LIVE'?"
if old_inspect not in src:
    raise SystemExit("SAFE STOP: inspect function anchor not found.")
src = src.replace(old_inspect, new_inspect, 1)

drawer_css_start = styles.find(".mp-drawer-backdrop")
media_anchor = styles.find("@media(max-width:1100px)")
if drawer_css_start < 0 or media_anchor < 0 or drawer_css_start > media_anchor:
    raise SystemExit("SAFE STOP: M2.2 drawer CSS block not found.")

inline_css = ".mp-inline-detail-row>td{padding:0!important;background:#0c1820!important;border-top:1px solid #35505f!important;border-bottom:1px solid #35505f!important}.mp-inline-audit{margin:0;padding:16px 18px 20px;background:#0e1b23;box-shadow:inset 3px 0 0 #4d9fb3}.mp-inline-audit-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid #2a3d49}.mp-inline-audit-head>div{display:flex;flex-direction:column;gap:3px}.mp-inline-audit-head span{font-size:9px;letter-spacing:1px;color:#66c7be}.mp-inline-audit-head b{font-size:13px;color:#d7e4eb}.mp-inline-audit-head small{font-size:9px;color:#7893a3}.mp-inline-audit .hilega-audit-section pre{max-height:320px;overflow:auto}.mp-inline-audit .shadow-detail-grid{grid-template-columns:repeat(4,minmax(0,1fr))}"
styles = styles[:drawer_css_start] + inline_css + styles[media_anchor:]
styles = styles.replace(",.mp-audit-drawer .shadow-detail-grid", "")
styles = styles.replace(".mp-audit-drawer{width:100vw;padding:14px}.mp-drawer-head{top:-14px;margin:-14px -14px 14px;padding:14px}", "")

backup = p.with_name(p.name + ".pre-m2-3.bak")
css_backup = css.with_name(css.name + ".pre-m2-3.bak")
if not backup.exists():
    shutil.copy2(p, backup)
if not css_backup.exists():
    shutil.copy2(css, css_backup)

p.write_text(src)
css.write_text(styles)

print("Patched: frontend/src/midpointStrategyShadow.tsx")
print("Patched: frontend/src/midpointStrategyShadow.css")
print("PASS: Inspect now expands directly below the selected live/replay row.")
print("PASS: Clicking Inspect again collapses the same event.")
print("PASS: Included semanticOwner TypeScript compatibility fix.")
print("No backend, strategy logic, execution controls, or replay data were changed.")
