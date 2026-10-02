from pathlib import Path
OPS=Path("backend/market_lab/historical_replay_operations_api_v1.py")
UI=Path("frontend/src/historicalOiResearch.tsx")
if not OPS.exists(): raise SystemExit("Safe-stop: historical_replay_operations_api_v1.py not found.")
if not UI.exists(): raise SystemExit("Safe-stop: historicalOiResearch.tsx not found. Apply Historical OI Research UI V1 first.")
ops=OPS.read_text(encoding="utf-8")
ui=UI.read_text(encoding="utf-8")
routes = '\n\n@router.post("/historical-oi/build")\ndef historical_oi_build(body: dict):\n    from .historical_oi_build_api_v1 import HistoricalOiBuildRequestV1, start_build\n    return start_build(HistoricalOiBuildRequestV1.model_validate(body))\n\n@router.get("/historical-oi/build-status")\ndef historical_oi_build_status(session_date: str):\n    from .historical_oi_build_api_v1 import build_status\n    return build_status(session_date)\n\n@router.get("/historical-oi/built-dates")\ndef historical_oi_built_dates():\n    from .historical_oi_build_api_v1 import built_dates\n    return built_dates()\n'
if '@router.post("/historical-oi/build")' not in ops: ops=ops.rstrip()+routes+"\n"
anchor="import './historicalOiResearch.css'\n"
newimp="import HistoricalOiBuildPanel from './historicalOiBuildPanel'\n"
if newimp not in ui:
    if anchor not in ui: raise SystemExit("Safe-stop: historicalOiResearch CSS import not found.")
    ui=ui.replace(anchor,anchor+newimp,1)
marker='<div className="hoi-head">'
render='<HistoricalOiBuildPanel />\n\n    '
if '<HistoricalOiBuildPanel' not in ui:
    if marker not in ui: raise SystemExit("Safe-stop: historical OI header marker not found.")
    ui=ui.replace(marker,render+marker,1)
OPS.write_text(ops,encoding="utf-8")
UI.write_text(ui,encoding="utf-8")
print("Applied Historical OI Download / Build V1.")
