from pathlib import Path
from market_lab.historical_oi_research_ui_v1 import inventory, session_rows

def test_90_session_inventory():
    value=inventory()
    assert value["session_count"]==90
    assert value["row_count"]==6660
    assert value["first_session"]=="2026-05-04"
    assert value["last_session"]=="2026-09-08"

def test_each_session_has_74_rows():
    value=inventory()
    assert all(x["rows"]==74 for x in value["sessions"])

def test_session_has_oi_fields():
    value=session_rows("2026-05-04")
    assert value["row_count"]==74
    row=value["rows"][0]
    for key in ("m_ce_oi","m_pe_oi","m_ce_delta","m_pe_delta","m_pcr","m_pcr_change","ce_state","pe_state"):
        assert key in row

def test_routes_and_frontend_wired():
    api=Path("backend/market_lab/historical_replay_operations_api_v1.py").read_text()
    assert '@router.get("/historical-oi/sessions")' in api
    assert "HistoricalOiResearch" in Path("frontend/src/historicalReplay.tsx").read_text()
