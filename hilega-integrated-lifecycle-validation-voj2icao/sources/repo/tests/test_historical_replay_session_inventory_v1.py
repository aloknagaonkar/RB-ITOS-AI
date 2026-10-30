from datetime import date
from pathlib import Path
from market_lab.historical_replay_session_inventory_v1 import expected_checkpoints

def test_expected_74_checkpoints():
    rows=expected_checkpoints(date(2026,9,18))
    assert len(rows)==74
    assert rows[0].strftime("%H:%M")=="09:20"
    assert rows[-1].strftime("%H:%M")=="15:25"

def test_route_and_frontend_wired():
    assert '@router.get("/inventory")' in Path("backend/market_lab/historical_replay_operations_api_v1.py").read_text()
    assert "HistoricalReplayInventory" in Path("frontend/src/historicalReplay.tsx").read_text()
    c=Path("frontend/src/historicalReplayInventory.tsx").read_text()
    assert "STRICT READY" in c and "LEGACY COMPATIBLE" in c and "Use date" in c
