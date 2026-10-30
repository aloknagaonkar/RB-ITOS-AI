from pathlib import Path
from market_lab.historical_oi_built_source_adapter_v1 import built_inventory, build_checkpoint_rows

def test_inventory_contract():
    inv=built_inventory()
    assert inv["source"]=="BUILT"
    assert "sessions" in inv

def test_sep9_if_present():
    try: result=build_checkpoint_rows("2026-09-09")
    except KeyError: return
    assert result["source"]=="BUILT"
    assert result["row_count"]==74
    assert all(k in result["rows"][1] for k in ("m_ce_oi","m_pe_oi","m_ce_delta","m_pe_delta","m_ce_pct","m_pe_pct","m_pcr","m_pcr_change"))

def test_frontend_selector():
    t=Path("frontend/src/historicalOiResearch.tsx").read_text()
    assert "Canonical 90-session" in t
    assert "Newly built dates" in t
    assert "/historical-oi/built/session" in t
