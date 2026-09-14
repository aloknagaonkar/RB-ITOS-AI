from market_lab.midpoint_v2_break_and_go_rebreak_exact_option_replay_v1 import (
    nearest_50, select_exact_atm_pe
)

def test_nearest_50():
    assert nearest_50(23838.0) == 23850

def test_exact_atm_pe_selection():
    rows = [{
        "timestamp":"2026-09-07T09:39:00+05:30",
        "instrument_key":"X",
        "strike":23850.0,
        "option_type":"PE",
        "spot":23838.0,
    }]
    r = select_exact_atm_pe(rows, "2026-09-07T09:39:00+05:30", 23838.0)
    assert r["available"] is True
    assert r["atm_strike"] == 23850

def test_no_nearest_fallback():
    rows = [{
        "timestamp":"2026-09-07T09:39:00+05:30",
        "instrument_key":"X",
        "strike":23900.0,
        "option_type":"PE",
        "spot":23838.0,
    }]
    r = select_exact_atm_pe(rows, "2026-09-07T09:39:00+05:30", 23838.0)
    assert r["available"] is False
    assert r["issue"] == "EXACT_ATM_PE_NOT_FOUND"
