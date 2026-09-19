from pathlib import Path
OPS=Path("backend/market_lab/historical_replay_operations_api_v1.py")
HR=Path("frontend/src/historicalReplay.tsx")
ops=OPS.read_text(encoding="utf-8")
hr=HR.read_text(encoding="utf-8")
routes="""

@router.get("/historical-oi/sessions")
def historical_oi_sessions():
    from .historical_oi_research_ui_v1 import inventory
    return inventory()


@router.get("/historical-oi/session")
def historical_oi_session(session_date: str):
    from fastapi import HTTPException
    from .historical_oi_research_ui_v1 import session_rows
    try:
        return session_rows(session_date)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
"""
if '@router.get("/historical-oi/sessions")' not in ops:
    ops=ops.rstrip()+routes+"\n"
anchor="import HistoricalReplayOperations from './historicalReplayOperations'\n"
newimp="import HistoricalOiResearch from './historicalOiResearch'\n"
if newimp not in hr:
    if anchor not in hr: raise SystemExit("Safe-stop: operations import not found")
    hr=hr.replace(anchor,anchor+newimp,1)
render_anchor="    <HistoricalReplayOperations\n      sessionDate={selected}\n      onReplayComplete={()=>setRefreshKey(v=>v+1)}\n    />\n"
render="    <HistoricalOiResearch />\n\n"
if "<HistoricalOiResearch" not in hr:
    if render_anchor not in hr: raise SystemExit("Safe-stop: operations render block not found")
    hr=hr.replace(render_anchor,render_anchor+"\n"+render,1)
OPS.write_text(ops,encoding="utf-8")
HR.write_text(hr,encoding="utf-8")
print("Applied Historical OI Research UI V1.")
