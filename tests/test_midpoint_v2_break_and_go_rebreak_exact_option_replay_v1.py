import csv
from pathlib import Path

from market_lab.midpoint_v2_break_and_go_rebreak_exact_option_replay_v1 import (
    nearest_50,
    select_exact_atm_pe,
    load_positioning,
)

def test_nearest_50():
    assert nearest_50(23838.0) == 23850

def test_exact_atm_pe_selection():
    rows = [{
        "timestamp":"2026-09-07T09:39:00+05:30",
        "instrument_key":"X",
        "strike":23850.0,
        "option_type":"PE",
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
    }]
    r = select_exact_atm_pe(rows, "2026-09-07T09:39:00+05:30", 23838.0)
    assert r["available"] is False
    assert r["issue"] == "EXACT_ATM_PE_NOT_FOUND"

def test_wide_positioning_schema(tmp_path: Path):
    p = tmp_path / "positioning.csv"
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "session_date","timestamp","moving_atm","strike",
            "ce_instrument_key","pe_instrument_key"
        ])
        w.writeheader()
        w.writerow({
            "session_date":"2026-09-07",
            "timestamp":"2026-09-07T09:39:00+05:30",
            "moving_atm":"23850",
            "strike":"23850",
            "ce_instrument_key":"CEKEY",
            "pe_instrument_key":"PEKEY",
        })
    rows = load_positioning(p)
    assert rows == [{
        "timestamp":"2026-09-07T09:39:00+05:30",
        "instrument_key":"PEKEY",
        "strike":23850.0,
        "option_type":"PE",
    }]
