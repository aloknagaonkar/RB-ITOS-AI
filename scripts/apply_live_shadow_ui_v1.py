from pathlib import Path

app = Path("frontend/src/App.tsx")
api = Path("backend/market_lab/api.py")
styles = Path("frontend/src/styles.css")

app_text = app.read_text()
api_text = api.read_text()
style_text = styles.read_text()

IMPORT = "import LiveShadowMonitor from './liveShadow'\n"
if IMPORT not in app_text:
    anchor = "import HistoricalResearch from './historicalResearch'\n"
    if anchor not in app_text:
        raise SystemExit("App import anchor not found")
    app_text = app_text.replace(anchor, anchor + IMPORT, 1)

old_nav = "['PCR workspace','Historical research','Data health','Configuration']"
new_nav = "['PCR workspace','Live shadow','Historical research','Data health','Configuration']"
if old_nav in app_text:
    app_text = app_text.replace(old_nav, new_nav, 1)
elif new_nav not in app_text:
    raise SystemExit("App navigation anchor not found")

old_icon = "label==='PCR workspace'?'◈':label==='Historical research'?'◫':label==='Data health'?'◉':'⚙'"
new_icon = "label==='PCR workspace'?'◈':label==='Live shadow'?'◎':label==='Historical research'?'◫':label==='Data health'?'◉':'⚙'"
if old_icon in app_text:
    app_text = app_text.replace(old_icon, new_icon, 1)
elif new_icon not in app_text:
    raise SystemExit("App icon anchor not found")

old_desc = "tab==='PCR workspace'?'One option chain. Two ATM perspectives. Every calculation traceable.':tab==='Historical research'?'Reconstruct Fixed, Moving, and Full PCR from expired option candles.':tab==='Data health'?'Connection health and data quality, with their limits visible.':'Versioned parameters for repeatable research.'"
new_desc = "tab==='PCR workspace'?'One option chain. Two ATM perspectives. Every calculation traceable.':tab==='Live shadow'?'Observation-only strategy lifecycle, data health, entries, exits and P&L.':tab==='Historical research'?'Reconstruct Fixed, Moving, and Full PCR from expired option candles.':tab==='Data health'?'Connection health and data quality, with their limits visible.':'Versioned parameters for repeatable research.'"
if old_desc in app_text:
    app_text = app_text.replace(old_desc, new_desc, 1)
elif new_desc not in app_text:
    raise SystemExit("App page description anchor not found")

# Collection start/pause is unrelated to the shadow page.
old_button = "{tab!=='Historical research' && <button disabled={busy}"
new_button = "{tab!=='Historical research' && tab!=='Live shadow' && <button disabled={busy}"
if old_button in app_text:
    app_text = app_text.replace(old_button, new_button, 1)
elif new_button not in app_text:
    raise SystemExit("App collection button anchor not found")

insert_anchor = "      {tab==='Historical research' && <HistoricalResearch"
shadow_render = "      {tab==='Live shadow' && <LiveShadowMonitor/>}\n"
if shadow_render not in app_text:
    if insert_anchor not in app_text:
        raise SystemExit("App render anchor not found")
    app_text = app_text.replace(insert_anchor, shadow_render + insert_anchor, 1)

API_IMPORT = "from .live_shadow_ui_v1 import router as live_shadow_router\n"
if API_IMPORT not in api_text:
    anchor = "from .recorded_session_inventory import recorded_session_inventory\n"
    if anchor not in api_text:
        raise SystemExit("API import anchor not found")
    api_text = api_text.replace(anchor, anchor + API_IMPORT, 1)

INCLUDE = "    app.include_router(live_shadow_router)\n"
if INCLUDE not in api_text:
    anchor = '    app = FastAPI(title="Market Strategy Lab", version="0.1.0", lifespan=lifespan)\n'
    if anchor not in api_text:
        raise SystemExit("API FastAPI anchor not found")
    api_text = api_text.replace(anchor, anchor + INCLUDE, 1)

css_marker = "/* LIVE_SHADOW_UI_V1 */"
css_source = Path("frontend/src/liveShadow.css")
if css_marker not in style_text:
    style_text = style_text.rstrip() + "\n\n" + css_source.read_text().strip() + "\n"

app.write_text(app_text)
api.write_text(api_text)
styles.write_text(style_text)
print("Patched frontend/src/App.tsx")
print("Patched backend/market_lab/api.py")
print("Patched frontend/src/styles.css")
