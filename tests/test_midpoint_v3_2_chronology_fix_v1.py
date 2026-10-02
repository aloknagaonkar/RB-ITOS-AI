import pytest

from market_lab.midpoint_v3_2_chronology_fix_v1 import (
    chronology_key,
    validate_chronology_rows,
)

def test_exact_timestamp_orders_same_day_correctly():
    rows = [
        {
            "session_date": "2026-09-08",
            "direction": "BULLISH",
            "entry_timestamp": "2026-09-08T11:15:00+05:30",
        },
        {
            "session_date": "2026-09-08",
            "direction": "BEARISH",
            "entry_timestamp": "2026-09-08T10:05:00+05:30",
        },
    ]
    ordered = sorted(rows, key=chronology_key)
    assert ordered[0]["direction"] == "BEARISH"
    assert ordered[1]["direction"] == "BULLISH"

def test_missing_timestamp_is_rejected():
    with pytest.raises(ValueError):
        chronology_key({
            "session_date": "2026-09-08",
            "direction": "BULLISH",
        })

def test_validate_rows_accepts_iso_timestamp():
    validate_chronology_rows([{
        "session_date": "2026-09-08",
        "direction": "BULLISH",
        "entry_timestamp": "2026-09-08T11:15:00+05:30",
    }])
