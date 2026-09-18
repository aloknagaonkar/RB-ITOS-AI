from pathlib import Path

p = Path("frontend/src/App.tsx")
text = p.read_text(encoding="utf-8")
original = text

# 1) Import component.
import_line = "import HistoricalReplay from './historicalReplay'\n"
if import_line not in text:
    lines = text.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("import "):
            insert_at = i + 1
    if insert_at == 0:
        raise SystemExit("SAFE STOP: no import block found in frontend/src/App.tsx")
    lines.insert(insert_at, import_line)
    text = "".join(lines)

# 2) Add navigation item.
old_nav = "['PCR workspace','Live shadow','Historical research','Data health','Configuration']"
new_nav = "['PCR workspace','Live shadow','Historical replay','Historical research','Data health','Configuration']"
if old_nav in text:
    text = text.replace(old_nav, new_nav, 1)
elif new_nav not in text:
    raise SystemExit("SAFE STOP: workspace nav anchor not found")

# 3) Add nav icon for Historical replay.
old_icon = "label==='PCR workspace'?'◈':label==='Live shadow'?'◎':label==='Historical research'?'◫':label==='Data health'?'◉':'⚙'"
new_icon = "label==='PCR workspace'?'◈':label==='Live shadow'?'◎':label==='Historical replay'?'↺':label==='Historical research'?'◫':label==='Data health'?'◉':'⚙'"
if old_icon in text:
    text = text.replace(old_icon, new_icon, 1)
elif "label==='Historical replay'?'↺'" not in text:
    raise SystemExit("SAFE STOP: navigation icon anchor not found")

# 4) Add page-heading description.
old_desc = "tab==='Live shadow'?'Observation-only strategy lifecycle, data health, entries, exits and P&L.':tab==='Historical research'?"
new_desc = "tab==='Live shadow'?'Observation-only strategy lifecycle, data health, entries, exits and P&L.':tab==='Historical replay'?'Replay the current Live Shadow strategy candle-by-candle with full causal audit.':tab==='Historical research'?"
if old_desc in text:
    text = text.replace(old_desc, new_desc, 1)
elif "tab==='Historical replay'?'Replay the current Live Shadow strategy" not in text:
    raise SystemExit("SAFE STOP: page description anchor not found")

# 5) Historical Replay must not show the collection-control action button.
old_button = "tab!=='Historical research' && tab!=='Live shadow'"
new_button = "tab!=='Historical research' && tab!=='Live shadow' && tab!=='Historical replay'"
if old_button in text:
    text = text.replace(old_button, new_button, 1)
elif new_button not in text:
    raise SystemExit("SAFE STOP: page action-button anchor not found")

# 6) Render the replay component next to Live Shadow.
old_render = "{tab==='Live shadow' && <LiveShadowMonitor/>}"
new_render = (
    "{tab==='Live shadow' && <LiveShadowMonitor/>}\n"
    "      {tab==='Historical replay' && <HistoricalReplay/>}"
)
if old_render in text:
    text = text.replace(old_render, new_render, 1)
elif "{tab==='Historical replay' && <HistoricalReplay/>}" not in text:
    raise SystemExit("SAFE STOP: Live Shadow render anchor not found")

if text == original:
    print("No changes needed; Historical Replay is already integrated.")
else:
    p.write_text(text, encoding="utf-8")
    print("Integrated Historical Replay into frontend/src/App.tsx")
