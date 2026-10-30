import csv
from pathlib import Path

from market_lab.midpoint_v2_break_and_go_rebreak_exact_option_replay_v1 import (
    load_positioning,
    nearest_50,
    select_exact_atm_pe,
)

def test_nearest_50():
    assert nearest_50(23838.0) == 23850

def test_wide_loader_preserves_actual_strikes(tmp_path: Path):
    p = tmp_path / "positioning.csv"
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "timestamp","expiry","moving_atm","strike","strike_offset","pe_instrument_key"
        ])
        w.writeheader()
        w.writerow({
            "timestamp":"2026-09-07T09:39:00+05:30",
            "expiry":"2026-09-08",
            "moving_atm":"23850",
            "strike":"23800",
            "strike_offset":"-1",
            "pe_instrument_key":"PE1",
        })
        w.writerow({
            "timestamp":"2026-09-07T09:39:00+05:30",
            "expiry":"2026-09-08",
            "moving_atm":"23850",
            "strike":"23850",
            "strike_offset":"0",
            "pe_instrument_key":"PE0",
        })
    rows = load_positioning(p)
    assert rows[0]["strike"] == 23800.0
    assert rows[1]["strike"] == 23850.0
    assert rows[1]["strike_offset"] == 0

def test_exact_atm_prefers_offset_zero():
    rows = [
        {
            "timestamp":"2026-09-07T09:39:00+05:30",
            "instrument_key":"PE_MINUS1",
            "strike":23800.0,
            "moving_atm":23850.0,
            "strike_offset":-1,
            "expiry":"2026-09-08",
            "option_type":"PE",
        },
        {
            "timestamp":"2026-09-07T09:39:00+05:30",
            "instrument_key":"PE_ATM",
            "strike":23850.0,
            "moving_atm":23850.0,
            "strike_offset":0,
            "expiry":"2026-09-08",
            "option_type":"PE",
        },
        {
            "timestamp":"2026-09-07T09:39:00+05:30",
            "instrument_key":"PE_PLUS1",
            "strike":23900.0,
            "moving_atm":23850.0,
            "strike_offset":1,
            "expiry":"2026-09-08",
            "option_type":"PE",
        },
    ]
    r = select_exact_atm_pe(rows, "2026-09-07T09:39:00+05:30", 23838.0)
    assert r["available"] is True
    assert r["instrument_key"] == "PE_ATM"
    assert r["atm_strike"] == 23850
    assert r["selection_method"] == "EXACT_TIMESTAMP_ACTUAL_STRIKE_OFFSET_ZERO"

def test_no_nearest_fallback():
    rows = [{
        "timestamp":"2026-09-07T09:39:00+05:30",
        "instrument_key":"X",
        "strike":23900.0,
        "moving_atm":23850.0,
        "strike_offset":1,
        "expiry":"2026-09-08",
        "option_type":"PE",
    }]
    r = select_exact_atm_pe(rows, "2026-09-07T09:39:00+05:30", 23838.0)
    assert r["available"] is False
    assert r["issue"] == "EXACT_ATM_PE_NOT_FOUND"
