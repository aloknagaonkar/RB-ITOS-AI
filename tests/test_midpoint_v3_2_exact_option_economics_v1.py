from datetime import datetime, timezone, timedelta

from market_lab.midpoint_v3_2_exact_option_economics_v1 import (
    exact_atm_contract,
    pct_return,
    first_touch,
    outcome_family,
)

IST = timezone(timedelta(hours=5, minutes=30))

def test_exact_atm_only_no_nearest_fallback():
    idx = {}
    t3 = datetime(2026, 1, 1, 10, 0, tzinfo=IST)
    assert exact_atm_contract(idx, "2026-01-01", t3, "PE") is None

def test_exact_atm_contract_uses_requested_side():
    t3 = datetime(2026, 1, 1, 10, 0, tzinfo=IST)
    idx = {
        ("2026-01-01", t3.isoformat()): {
            "moving_atm": "25000",
            "ce_instrument_key": "CE_KEY",
            "pe_instrument_key": "PE_KEY",
        }
    }
    pe = exact_atm_contract(idx, "2026-01-01", t3, "PE")
    ce = exact_atm_contract(idx, "2026-01-01", t3, "CE")
    assert pe["instrument_key"] == "PE_KEY"
    assert ce["instrument_key"] == "CE_KEY"
    assert pe["strike"] == 25000.0

def test_pct_return():
    assert round(pct_return(100.0, 105.0), 8) == 5.0

def test_target_first():
    candles = [
        {"high": 103.0, "low": 99.0},
        {"high": 106.0, "low": 98.0},
    ]
    assert first_touch(100.0, candles, 5, 10) == "TARGET_FIRST"

def test_stop_first():
    candles = [
        {"high": 103.0, "low": 96.0},
        {"high": 104.0, "low": 89.0},
    ]
    assert first_touch(100.0, candles, 5, 10) == "STOP_FIRST"

def test_ambiguous_same_bar():
    assert first_touch(
        100.0, [{"high": 106.0, "low": 89.0}], 5, 10
    ) == "AMBIGUOUS_SAME_BAR"

def test_outcome_family():
    assert outcome_family("RED_BEARISH_BREAK_AND_GO") == "BREAK_AND_GO"
    assert outcome_family("GREEN_BULLISH_BASE_THEN_GO") == "BASE_THEN_GO"
