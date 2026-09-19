from pathlib import Path

P = Path("frontend/src/historicalOiResearch.tsx")
if not P.exists():
    raise SystemExit("Safe-stop: frontend/src/historicalOiResearch.tsx not found")

text = P.read_text(encoding="utf-8")

old_detail = "const detailUrl=source==='CANONICAL'?'/api/live-shadow/replay-ops/historical-oi/session':'/api/live-shadow/replay-ops/historical-oi/built/session'"
new_detail = "const detailUrl=source==='CANONICAL'?'/api/live-shadow/replay-ops/historical-oi/session':source==='ENRICHED'?'/api/live-shadow/replay-ops/historical-oi/enriched/rows':'/api/live-shadow/replay-ops/historical-oi/built/session'"
if old_detail in text:
    text = text.replace(old_detail, new_detail, 1)
elif new_detail not in text:
    raise SystemExit("Safe-stop: detailUrl shape not recognized")

old_fetch = "fetch(`${detailUrl}?session_date=${encodeURIComponent(selected)}`)"
new_fetch = "fetch(source==='ENRICHED'?`${detailUrl}?date=${encodeURIComponent(selected)}`:`${detailUrl}?session_date=${encodeURIComponent(selected)}`)"
if old_fetch in text:
    text = text.replace(old_fetch, new_fetch, 1)
elif new_fetch not in text:
    raise SystemExit("Safe-stop: detail fetch shape not recognized")

old_select = '<label>Source<select value={source} onChange={e=>{setSource(e.target.value as Source);setSelected(\'\')}}><option value="CANONICAL">Canonical 90-session</option><option value="BUILT">Newly built dates</option></select></label>'
new_select = '<label>Source<select value={source} onChange={e=>{setSource(e.target.value as Source);setSelected(\'\')}}><option value="CANONICAL">Canonical 90-session</option><option value="BUILT">Newly built dates</option><option value="ENRICHED">Enriched</option></select></label>'
if old_select in text:
    text = text.replace(old_select, new_select, 1)
elif '<option value="ENRICHED">Enriched</option>' not in text:
    raise SystemExit("Safe-stop: source select shape not recognized")

old_card = '<div className="hoi-cards"><div><span>Source</span><b>{source===\'CANONICAL\'?\'90-session canonical\':\'Newly built\'}</b></div>'
new_card = '<div className="hoi-cards"><div><span>Source</span><b>{source===\'CANONICAL\'?\'90-session canonical\':source===\'ENRICHED\'?\'Enriched\':\'Newly built\'}</b></div>'
if old_card in text:
    text = text.replace(old_card, new_card, 1)

old_note = "{source==='BUILT'&&<p className=\"hoi-note\">Built dates are converted from isolated per-strike sidecar data and do not modify the frozen canonical 90-session dataset. CE/PE positioning state is the exact ATM strike's 5-minute state.</p>}"
new_note = "{source==='BUILT'&&<p className=\"hoi-note\">Built dates are converted from isolated per-strike sidecar data and do not modify the frozen canonical 90-session dataset. CE/PE positioning state is the exact ATM strike's 5-minute state.</p>}\n  {source==='ENRICHED'&&<p className=\"hoi-note\">Enriched dates combine exact downloaded historical positioning with fixed 09:20 ATM ±5 and moving same-strike calculations. The frozen canonical dataset is not modified.</p>}"
if old_note in text:
    text = text.replace(old_note, new_note, 1)

required = [
    '<option value="ENRICHED">Enriched</option>',
    "/api/live-shadow/replay-ops/historical-oi/enriched/sessions",
    "/api/live-shadow/replay-ops/historical-oi/enriched/rows",
    "source==='ENRICHED'?`${detailUrl}?date=",
]
missing = [x for x in required if x not in text]
if missing:
    raise SystemExit("Safe-stop: post-check failed: " + ", ".join(missing))

P.write_text(text, encoding="utf-8")
print("Patched Historical OI ENRICHED selector + detail route.")
