from pathlib import Path
import re

API = Path("backend/market_lab/api.py")
UI = Path("frontend/src/historicalOiResearch.tsx")

if not API.exists():
    raise SystemExit("Safe-stop: backend/market_lab/api.py not found")

api = API.read_text(encoding="utf-8")

import_line = "from .historical_oi_enrichment_api_v1 import router as historical_oi_enrichment_router\n"
if import_line not in api:
    # Insert before create_app; keeps module imports top-level without depending on exact neighboring imports.
    marker = "\ndef create_app("
    if marker not in api:
        raise SystemExit("Safe-stop: create_app marker not found in api.py")
    api = api.replace(marker, "\n" + import_line + marker, 1)

include_line = "    app.include_router(historical_oi_enrichment_router)\n"
if include_line not in api:
    # Historical replay routers are already intentionally before static mount.
    marker = '    # Development uses Vite proxy; built UI can be served by the same local backend.\n'
    if marker not in api:
        raise SystemExit("Safe-stop: static UI marker not found in api.py")
    api = api.replace(marker, include_line + "\n" + marker, 1)

API.write_text(api, encoding="utf-8")
print("Registered Historical OI enriched API router.")

if not UI.exists():
    raise SystemExit("Safe-stop: historicalOiResearch.tsx not found")

ui = UI.read_text(encoding="utf-8")

ui = ui.replace(
    "type Source='CANONICAL'|'BUILT'",
    "type Source='CANONICAL'|'BUILT'|'ENRICHED'",
    1,
)

# Rewrite URL selection to handle ENRICHED without disturbing existing canonical/built endpoints.
sessions_pattern = re.compile(r"const sessionsUrl=source==='CANONICAL'\?([^:\n]+):([^\n]+)")
m = sessions_pattern.search(ui)
if m and "ENRICHED" not in m.group(0):
    canonical_expr=m.group(1)
    built_expr=m.group(2)
    repl=f"const sessionsUrl=source==='CANONICAL'?{canonical_expr}:source==='ENRICHED'?'/api/live-shadow/replay-ops/historical-oi/enriched/sessions':{built_expr}"
    ui=ui[:m.start()]+repl+ui[m.end():]

# Rows URL commonly follows same ternary form.
rows_patterns = [
    re.compile(r"const rowsUrl=source==='CANONICAL'\?([^:\n]+):([^\n]+)"),
    re.compile(r"const sessionUrl=source==='CANONICAL'\?([^:\n]+):([^\n]+)"),
]
for pat in rows_patterns:
    m=pat.search(ui)
    if m and "ENRICHED" not in m.group(0):
        name=m.group(0).split("=")[0]
        canonical_expr=m.group(1)
        built_expr=m.group(2)
        repl=f"{name}=source==='CANONICAL'?{canonical_expr}:source==='ENRICHED'?`/api/live-shadow/replay-ops/historical-oi/enriched/rows?date=${{encodeURIComponent(selected)}}`:{built_expr}"
        ui=ui[:m.start()]+repl+ui[m.end():]
        break

# Add source selector button wherever existing BUILT button is rendered.
if ">Enriched<" not in ui and "ENRICHED" in ui:
    candidates = [
        "<button className={source==='BUILT'?'active':''} onClick={()=>setSource('BUILT')}>Newly built dates</button>",
        "<button className={source==='BUILT'?'active':''} onClick={()=>setSource('BUILT')}>Built</button>",
    ]
    inserted=False
    for c in candidates:
        if c in ui:
            ui=ui.replace(c, c + "\n        <button className={source==='ENRICHED'?'active':''} onClick={()=>setSource('ENRICHED')}>Enriched</button>", 1)
            inserted=True
            break
    if not inserted:
        print("WARNING: source button shape not recognized; API is installed but Enriched button was not auto-inserted.")

# Add provenance note.
built_note = "{source==='BUILT'&&<p className=\"hoi-note\">"
if built_note in ui and "source==='ENRICHED'" not in ui:
    pass

UI.write_text(ui, encoding="utf-8")
print("Patched Historical OI Research source union/endpoints where recognized.")
