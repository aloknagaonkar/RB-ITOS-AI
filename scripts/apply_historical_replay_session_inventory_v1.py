from pathlib import Path
ops=Path("backend/market_lab/historical_replay_operations_api_v1.py")
hr=Path("frontend/src/historicalReplay.tsx")
a=ops.read_text(encoding="utf-8")
b=hr.read_text(encoding="utf-8")

if '@router.get("/inventory")' not in a:
    a += '\n\n@router.get("/inventory")\ndef replay_inventory():\n    from .historical_replay_session_inventory_v1 import build_inventory\n    return build_inventory()\n'

ops_import="import HistoricalReplayOperations from './historicalReplayOperations'\n"
inventory_import="import HistoricalReplayInventory from './historicalReplayInventory'\n"
if inventory_import not in b:
    if ops_import not in b: raise SystemExit("Safe-stop: operations import not found")
    b=b.replace(ops_import,ops_import+inventory_import,1)

anchor="    <HistoricalReplayOperations\n      sessionDate={selected}\n      onReplayComplete={()=>setRefreshKey(v=>v+1)}\n    />\n"
render="    <HistoricalReplayInventory\n      selectedDate={selected}\n      onSelectDate={setSelected}\n    />\n\n"
if "<HistoricalReplayInventory" not in b:
    if anchor not in b: raise SystemExit("Safe-stop: operations render block not found")
    b=b.replace(anchor,render+anchor,1)

ops.write_text(a,encoding="utf-8")
hr.write_text(b,encoding="utf-8")
print("Applied historical replay session inventory V1.")
