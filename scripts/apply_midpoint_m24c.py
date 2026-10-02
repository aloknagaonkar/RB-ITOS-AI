#!/usr/bin/env python3
from pathlib import Path
import shutil

p = Path("frontend/src/midpointStrategyShadow.tsx")
if not p.exists():
    raise SystemExit(f"STOP: missing {p}")

backup = p.with_name(p.name + ".pre-m2-4c.bak")
if not backup.exists():
    shutil.copy2(p, backup)
    print("BACKUP:", backup)

text = p.read_text()
helper = '\nfunction eventMs(v:string|null|undefined){if(!v)return 0;const n=Date.parse(v);return Number.isFinite(n)?n:0}\n\nfunction livePresentationFromStatus(status:Status|null):ReplayPresentation|null{\n const entry=status?.latest_entry\n if(!entry)return null\n\n const entryMs=eventMs(entry.event_timestamp)\n const terminalMs=eventMs(status?.latest_terminal?.event_timestamp)\n if(terminalMs>=entryMs)return null\n\n const latest=status?.latest_event\n const latestMs=eventMs(latest?.event_timestamp)\n const current=(latest&&latestMs>=entryMs)?latest:entry\n\n const direction=String(entry.direction??\'\')\n const entryPx=entry.underlying_price\n const currentPx=current?.underlying_price??entryPx\n let move:number|null=null\n if(entryPx!=null&&currentPx!=null){\n   if(direction===\'BULLISH\')move=currentPx-entryPx\n   else if(direction===\'BEARISH\')move=entryPx-currentPx\n }\n\n const fut=current?.futures_price??null\n const vwap=current?.futures_vwap??null\n const raw=fut!=null&&vwap!=null?fut-vwap:null\n\n const plus20=eventMs(status?.latest_plus20?.event_timestamp)>=entryMs\n const classifier=eventMs(status?.latest_classifier?.event_timestamp)>=entryMs\n   ?(status?.latest_classifier?.result||status?.latest_classifier?.reason||null):null\n const degraded=eventMs(status?.latest_degraded?.event_timestamp)>=entryMs\n const recovered=eventMs(status?.latest_recovery?.event_timestamp)>=entryMs\n\n return {\n   status:\'ACTIVE\',\n   label:`CONTINUE · ${direction}_ACTIVE`,\n   family:entry.family,\n   direction,\n   entry_timestamp:entry.event_timestamp,\n   entry_underlying:entryPx,\n   current_underlying:currentPx,\n   directional_move:move,\n   plus20,\n   classifier,\n   degraded,\n   recovered,\n   option_intent:direction===\'BULLISH\'?\'BUY CE\':direction===\'BEARISH\'?\'BUY PE\':null,\n   futures_close:fut,\n   futures_vwap:vwap,\n   raw_vwap_diff:raw,\n   vwap_position:raw==null?\'NOT AVAILABLE\':raw>0?\'ABOVE VWAP\':raw<0?\'BELOW VWAP\':\'AT VWAP\'\n }\n}\n\nfunction LiveContinuationPanel({status}:{status:Status|null}){\n const p=livePresentationFromStatus(status)\n if(!p)return null\n return <section className="panel shadow-panel mp-live-continuation-panel">\n   <div className="panel-heading">\n     <div>\n       <h2>Live active continuation</h2>\n       <p>Presentation-only projection from immutable live Midpoint audit state. No synthetic audit events are written.</p>\n     </div>\n     <span className="pill teal">LIVE ACTIVE</span>\n   </div>\n   <div className="mp-live-continuation-body">\n     <ContinuationCard p={p}/>\n     <div className="mp-live-kv">\n       <span>Entry time</span><b>{tm(p.entry_timestamp)}</b>\n       <span>Entry NIFTY</span><b>{num(p.entry_underlying)}</b>\n       <span>Current NIFTY</span><b>{num(p.current_underlying)}</b>\n       <span>Directional move</span><b>{num(p.directional_move)}</b>\n       <span>Futures close</span><b>{num(p.futures_close)}</b>\n       <span>Futures VWAP</span><b>{num(p.futures_vwap)}</b>\n       <span>Raw futures − VWAP</span><b>{num(p.raw_vwap_diff)}</b>\n       <span>VWAP position</span><b>{p.vwap_position}</b>\n       <span>Option intent</span><b>{p.option_intent??\'—\'}</b>\n       <span>+20 proof</span><b>{yn(p.plus20)}</b>\n       <span>Classifier</span><b>{words(p.classifier)}</b>\n       <span>Degraded</span><b>{yn(p.degraded)}</b>\n     </div>\n   </div>\n </section>\n}\n\n'

if "function livePresentationFromStatus" not in text:
    anchor = "function ContinuationCard({p}:{p:ReplayPresentation}){"
    if anchor not in text:
        raise SystemExit("STOP: ContinuationCard anchor not found")
    text = text.replace(anchor, helper + anchor, 1)

old = " {mode==='HISTORICAL_REPLAY'?<ReplayMinuteTable minutes={minutes} onInspect={onInspect} selected={selected}/>:<LiveAuditTable timeline={timeline} onInspect={onInspect} selected={selected}/>}</>"
new = " {mode==='LIVE'&&<LiveContinuationPanel status={status}/>}\\n {mode==='HISTORICAL_REPLAY'?<ReplayMinuteTable minutes={minutes} onInspect={onInspect} selected={selected}/>:<LiveAuditTable timeline={timeline} onInspect={onInspect} selected={selected}/>}</>"
if old in text:
    text = text.replace(old, new, 1)
elif "<LiveContinuationPanel status={status}/>" not in text:
    raise SystemExit("STOP: SessionView insertion point not found")

p.write_text(text)
print("PATCHED:", p)

css = Path("frontend/src/midpointStrategyShadow.css")
if not css.exists():
    raise SystemExit(f"STOP: missing {css}")

css_backup = css.with_name(css.name + ".pre-m2-4c.bak")
if not css_backup.exists():
    shutil.copy2(css, css_backup)
    print("BACKUP:", css_backup)

ct = css.read_text()
css_add = '\n.mp-live-continuation-panel{border-color:#2f655d}.mp-live-continuation-body{padding:0 14px 14px}.mp-live-kv{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px 12px;margin-top:10px;padding:12px;border:1px solid #29414a;border-radius:7px;background:#0e1d24}.mp-live-kv span{font-size:8px;color:#7893a3;text-transform:uppercase;letter-spacing:.45px}.mp-live-kv b{font-size:10px;color:#d7e4eb;text-align:right}@media(max-width:1100px){.mp-live-kv{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){.mp-live-kv{grid-template-columns:1fr 1fr}}\n'
if ".mp-live-continuation-panel" not in ct:
    css.write_text(ct + "\n" + css_add)
    print("PATCHED:", css)
else:
    print("CSS live continuation styles already present")
