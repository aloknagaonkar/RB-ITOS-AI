#!/usr/bin/env python3
from pathlib import Path
import shutil

tsx=Path("frontend/src/midpointStrategyShadow.tsx")
css=Path("frontend/src/midpointStrategyShadow.css")

for p in (tsx,css):
    if not p.exists():
        raise SystemExit(f"STOP: missing {p}")
    b=p.with_name(p.name+".pre-m2-5-layout.bak")
    if not b.exists():
        shutil.copy2(p,b)
        print("BACKUP:",b)

text=tsx.read_text()
helpers='\nfunction ActiveTradeSection({status}:{status:Status|null}){\n const entry=status?.latest_entry\n if(!entry)return <section className="mp-trade-strip mp-trade-strip-empty"><div><span>ACTIVE TRADE</span><b>NO ACTIVE TRADE</b></div><small>Waiting for a valid B/E entry.</small></section>\n\n const entryMs=eventMs(entry.event_timestamp)\n const terminal=status?.latest_terminal\n const terminalMs=eventMs(terminal?.event_timestamp)\n if(terminalMs>=entryMs)return <section className="mp-trade-strip mp-trade-strip-empty"><div><span>ACTIVE TRADE</span><b>NO ACTIVE TRADE</b></div><small>Latest trade lifecycle is closed.</small></section>\n\n const latest=status?.latest_event\n const currentPx=latest?.underlying_price??entry.underlying_price\n const direction=String(entry.direction??\'\')\n const move=entry.underlying_price!=null&&currentPx!=null\n   ?(direction===\'BULLISH\'?currentPx-entry.underlying_price:\n     direction===\'BEARISH\'?entry.underlying_price-currentPx:null)\n   :null\n const fut=latest?.futures_price??entry.futures_price\n const vwap=latest?.futures_vwap??entry.futures_vwap\n const raw=fut!=null&&vwap!=null?fut-vwap:null\n const optionIntent=direction===\'BULLISH\'?\'BUY CE\':direction===\'BEARISH\'?\'BUY PE\':\'—\'\n\n return <section className="mp-trade-strip active">\n   <div className="mp-trade-strip-title"><span>ACTIVE TRADE</span><b>{words(entry.family)} · {words(direction)} · {optionIntent}</b></div>\n   <div className="mp-trade-strip-grid">\n     <article><span>Entry time</span><b>{tm(entry.event_timestamp)}</b></article>\n     <article><span>Entry NIFTY</span><b>{num(entry.underlying_price)}</b></article>\n     <article><span>Current NIFTY</span><b>{num(currentPx)}</b></article>\n     <article><span>Directional move</span><b>{num(move)}</b></article>\n     <article><span>Fut / VWAP</span><b>{num(fut)} / {num(vwap)}</b><small>{raw==null?\'—\':raw>0?\'ABOVE VWAP\':raw<0?\'BELOW VWAP\':\'AT VWAP\'}</small></article>\n     <article><span>+20</span><b>{eventMs(status?.latest_plus20?.event_timestamp)>=entryMs?\'YES\':\'NO\'}</b></article>\n     <article><span>Classifier</span><b>{eventMs(status?.latest_classifier?.event_timestamp)>=entryMs?words(status?.latest_classifier?.result||status?.latest_classifier?.reason):\'WAITING\'}</b></article>\n     <article><span>Degraded</span><b>{eventMs(status?.latest_degraded?.event_timestamp)>=entryMs?\'YES\':\'NO\'}</b></article>\n   </div>\n </section>\n}\n\nfunction ExitDetailsSection({status}:{status:Status|null}){\n const terminal=status?.latest_terminal\n const rescue=status?.latest_rescue\n const exit=(terminal&&eventMs(terminal.event_timestamp)>=eventMs(rescue?.event_timestamp))?terminal:rescue\n if(!exit)return <section className="mp-exit-strip mp-exit-strip-empty"><div><span>EXIT DETAILS</span><b>NO EXIT YET</b></div><small>No completed Midpoint exit is available for this view.</small></section>\n\n return <section className="mp-exit-strip">\n   <div className="mp-trade-strip-title"><span>EXIT DETAILS</span><b>{words(exit.event_type)}</b></div>\n   <div className="mp-trade-strip-grid">\n     <article><span>Exit time</span><b>{tm(exit.event_timestamp)}</b></article>\n     <article><span>Owner / family</span><b>{semanticOwner(exit)}</b></article>\n     <article><span>Direction</span><b>{words(exit.direction)}</b></article>\n     <article><span>NIFTY at exit</span><b>{num(exit.underlying_price)}</b></article>\n     <article><span>Directional points</span><b>{num(exit.directional_points)}</b></article>\n     <article><span>Futures close</span><b>{num(exit.futures_price)}</b></article>\n     <article><span>Futures VWAP</span><b>{num(exit.futures_vwap)}</b></article>\n     <article><span>Reason</span><b>{words(exit.reason||exit.result)}</b></article>\n   </div>\n </section>\n}\n'

if "function ActiveTradeSection" not in text:
    anchor="function SessionView({mode,status,timeline,minutes,selected,onInspect}"
    idx=text.find(anchor)
    if idx<0:
        raise SystemExit("STOP: SessionView anchor not found")
    text=text[:idx]+helpers+text[idx:]

text=text.replace(
    '<div className="shadow-metrics mp-summary">',
    '<div className="shadow-metrics mp-summary mp-summary-compact">',
    1,
)

old_layout=' <div className="mp-lifecycle-grid"><EventCard label="Entry" event={status?.latest_entry}/><EventCard label="+20 proof" event={status?.latest_plus20}/><EventCard label="Runner classification" event={status?.latest_classifier}/><EventCard label="Degraded" event={status?.latest_degraded}/><EventCard label="CAP20 rescue" event={status?.latest_rescue}/><EventCard label="Structural terminal" event={status?.latest_terminal}/></div>\n {mode===\'LIVE\'&&<LiveContinuationPanel status={status}/>}\n {mode===\'HISTORICAL_REPLAY\'?<ReplayMinuteTable minutes={minutes} onInspect={onInspect} selected={selected}/>:<LiveAuditTable timeline={timeline} onInspect={onInspect} selected={selected}/>}</>'
new_layout=' <div className="mp-lifecycle-grid mp-lifecycle-compact"><EventCard label="Entry" event={status?.latest_entry}/><EventCard label="+20 proof" event={status?.latest_plus20}/><EventCard label="Runner classification" event={status?.latest_classifier}/><EventCard label="Degraded" event={status?.latest_degraded}/><EventCard label="CAP20 rescue" event={status?.latest_rescue}/><EventCard label="Structural terminal" event={status?.latest_terminal}/></div>\n <ActiveTradeSection status={status}/>\n {mode===\'LIVE\'&&<LiveContinuationPanel status={status}/>}\n {mode===\'HISTORICAL_REPLAY\'?<ReplayMinuteTable minutes={minutes} onInspect={onInspect} selected={selected}/>:<LiveAuditTable timeline={timeline} onInspect={onInspect} selected={selected}/>}\n <ExitDetailsSection status={status}/></>'
if old_layout in text:
    text=text.replace(old_layout,new_layout,1)
elif "<ActiveTradeSection status={status}/>" not in text:
    raise SystemExit("STOP: SessionView layout block not found")

tsx.write_text(text)
print("PATCHED:",tsx)

ct=css.read_text()
css_add='\n/* M2.5 compact layout polish */\n.mp-summary-compact{grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}\n.mp-summary-compact article{min-height:0!important;padding:9px 11px!important;border-radius:6px!important}\n.mp-summary-compact article span{font-size:8px!important}\n.mp-summary-compact article b{font-size:12px!important;margin:4px 0!important;line-height:1.2}\n.mp-summary-compact article small{font-size:8px!important;line-height:1.25}\n\n.mp-lifecycle-compact{grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}\n.mp-lifecycle-compact .mp-card{padding:9px 11px;min-height:0}\n.mp-lifecycle-compact .mp-card span{font-size:8px}\n.mp-lifecycle-compact .mp-card b{font-size:11px;margin:4px 0}\n.mp-lifecycle-compact .mp-card small{font-size:8px;line-height:1.25}\n\n.mp-trade-strip,.mp-exit-strip{border:1px solid #315461;border-radius:7px;background:#10242d;padding:10px 12px}\n.mp-trade-strip.active{border-color:#2f6a5d;background:#102a29}\n.mp-exit-strip{border-color:#67404a;background:#281c22}\n.mp-trade-strip-empty,.mp-exit-strip-empty{display:flex;justify-content:space-between;align-items:center;gap:12px;background:#101f27}\n.mp-trade-strip-empty>div,.mp-exit-strip-empty>div{display:flex;gap:10px;align-items:center}\n.mp-trade-strip-empty span,.mp-exit-strip-empty span,.mp-trade-strip-title span{font-size:8px;letter-spacing:.8px;color:#78a6b7}\n.mp-trade-strip-empty b,.mp-exit-strip-empty b,.mp-trade-strip-title b{font-size:11px;color:#d8e6ec}\n.mp-trade-strip-empty small,.mp-exit-strip-empty small{font-size:8px;color:#78909d}\n.mp-trade-strip-title{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:8px}\n.mp-trade-strip-grid{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:7px}\n.mp-trade-strip-grid article{border:1px solid #29414a;background:#11252e;border-radius:5px;padding:7px 8px;min-width:0}\n.mp-exit-strip .mp-trade-strip-grid article{background:#231b20;border-color:#56343d}\n.mp-trade-strip-grid span{display:block;font-size:7px;text-transform:uppercase;color:#728c9a;letter-spacing:.4px}\n.mp-trade-strip-grid b{display:block;margin-top:3px;font-size:9px;color:#d9e6eb;white-space:normal;word-break:break-word}\n.mp-trade-strip-grid small{display:block;margin-top:2px;font-size:7px;color:#8097a2}\n\n@media(max-width:1250px){\n .mp-summary-compact,.mp-lifecycle-compact{grid-template-columns:repeat(3,minmax(0,1fr))}\n .mp-trade-strip-grid{grid-template-columns:repeat(4,minmax(0,1fr))}\n}\n@media(max-width:760px){\n .mp-summary-compact,.mp-lifecycle-compact{grid-template-columns:repeat(2,minmax(0,1fr))}\n .mp-trade-strip-grid{grid-template-columns:repeat(2,minmax(0,1fr))}\n .mp-trade-strip-empty,.mp-exit-strip-empty,.mp-trade-strip-title{align-items:flex-start;flex-direction:column}\n}\n'
if ".mp-summary-compact" not in ct:
    css.write_text(ct+"\n"+css_add)
    print("PATCHED:",css)
else:
    print("compact layout CSS already present")
