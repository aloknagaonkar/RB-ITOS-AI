from datetime import datetime

from market_lab.midpoint_v2_new_arm_exact_option_economics_v1 import (
    exact_atm_contract,
    option_side,
)


def test_option_side_uses_v2_entry_direction():
    assert option_side("BULLISH") == "CE"
    assert option_side("BEARISH") == "PE"


def test_exact_atm_contract_uses_confirmation_timestamp_and_side():
    ts = datetime.fromisoformat("2026-06-17T10:10:00+05:30")
    positioning = {
        ("2026-06-17", ts.isoformat()): {
            "timestamp": ts.isoformat(),
            "moving_atm": 24100.0,
            "ce_instrument_key": "CE-KEY",
            "pe_instrument_key": "PE-KEY",
        }
    }
    bull = exact_atm_contract(positioning, "2026-06-17", ts, "CE")
    bear = exact_atm_contract(positioning, "2026-06-17", ts, "PE")
    assert bull["strike"] == 24100.0
    assert bull["instrument_key"] == "CE-KEY"
    assert bear["instrument_key"] == "PE-KEY"


def test_no_nearest_timestamp_fallback():
    wanted = datetime.fromisoformat("2026-06-17T10:10:00+05:30")
    other = datetime.fromisoformat("2026-06-17T10:09:00+05:30")
    positioning = {
        ("2026-06-17", other.isoformat()): {
            "timestamp": other.isoformat(),
            "moving_atm": 24100.0,
            "ce_instrument_key": "CE-KEY",
            "pe_instrument_key": "PE-KEY",
        }
    }
    assert exact_atm_contract(positioning, "2026-06-17", wanted, "CE") is None
