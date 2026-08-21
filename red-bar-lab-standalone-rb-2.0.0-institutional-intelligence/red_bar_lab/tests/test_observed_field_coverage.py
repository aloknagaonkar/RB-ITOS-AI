import pytest

from red_bar_lab.services.observed_field_coverage import (
    assess_observed_field_coverage,
)


def _market_row():
    return {
        "signal_id": "RBV2-1",
        "instrument_key": "NSE_INDEX|Nifty 50",
        "trading_date": "2026-08-21",
        "entry_timestamp": "2026-08-21T10:20:00+05:30",
        "session_open": 25000.0,
        "minutes_from_open": 65.0,
        "price_from_open_points": 20.0,
        "session_high_so_far": 25040.0,
        "session_low_so_far": 24980.0,
        "session_range_so_far": 60.0,
        "session_range_position": 0.66,
        "trend_5m": "UPTREND",
    }


def test_complete_mandatory_fields_are_ready():
    result = assess_observed_field_coverage("MARKET", _market_row())
    assert result.status == "READY"
    assert result.mandatory_present == result.mandatory_expected
    assert result.mandatory_coverage_pct == 100.0
    assert result.reason_code is None


def test_missing_mandatory_field_blocks_stage():
    row = _market_row()
    row["trend_5m"] = None
    result = assess_observed_field_coverage("MARKET", row)
    assert result.status == "MISSING"
    assert result.reason_code == "MARKET_MANDATORY_FIELDS_MISSING"
    assert result.missing_mandatory_fields == ("trend_5m",)


def test_zero_and_false_values_count_as_observed():
    row = _market_row()
    row["minutes_from_open"] = 0.0
    row["session_range_position"] = 0.0
    result = assess_observed_field_coverage("MARKET", row)
    assert result.status == "READY"


def test_optional_fields_do_not_block_stage():
    result = assess_observed_field_coverage("VOLUME", {
        "signal_id": "RBV2-1",
        "instrument_key": "NSE_INDEX|Nifty 50",
        "trading_date": "2026-08-21",
        "entry_timestamp": "2026-08-21T10:20:00+05:30",
        "volume_current_1m": 1000.0,
        "volume_avg_20m": 800.0,
        "volume_trend_5m": "RISING",
        "price_volume_state": "BULLISH_ACCUMULATION",
        "structure_state": "EXPANSION",
    })
    assert result.status == "READY"
    assert result.optional_coverage_pct == 0.0
    assert result.missing_optional_fields


def test_option_alignment_false_is_observed_but_not_decided_by_coverage():
    result = assess_observed_field_coverage("OPTIONS", {
        "signal_id": "RBV2-1",
        "instrument_key": "NSE_INDEX|Nifty 50",
        "trading_date": "2026-08-21",
        "entry_timestamp": "2026-08-21T10:20:00+05:30",
        "option_expiry": "2026-08-27",
        "option_snapshot_timestamp": "2026-08-21T10:25:00+05:30",
        "option_snapshot_delay_seconds": 300.0,
        "entry_aligned": 0,
        "option_spot_price": 25020.0,
        "atm_strike": 25000.0,
        "total_call_oi": 100000.0,
        "total_put_oi": 110000.0,
        "pcr_oi": 1.1,
    })
    assert result.status == "READY"
    assert "entry_aligned" not in result.missing_mandatory_fields


def test_unknown_stage_is_rejected():
    with pytest.raises(ValueError, match="unsupported field coverage stage"):
        assess_observed_field_coverage("UNKNOWN", {})
