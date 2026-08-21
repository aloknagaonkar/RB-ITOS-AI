from datetime import datetime, timezone

import pandas as pd

from red_bar_lab.services.intraday_acceptance_engine import (
    build_futures_vwap_acceptance,
    build_one_minute_early_evidence,
    build_spot_vwap_acceptance,
)


def _frame(*, volume: float = 1000.0) -> pd.DataFrame:
    timestamps = pd.date_range("2026-08-21 03:45:00+00:00", periods=25, freq="1min")
    closes = [100.0 + index * 0.02 for index in range(24)] + [102.0]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [value - 0.15 for value in closes],
            "high": [value + 0.20 for value in closes],
            "low": [value - 0.20 for value in closes],
            "close": closes,
            "volume": [volume] * len(closes),
        }
    )


def test_spot_vwap_acceptance_uses_real_volume():
    frame = _frame()
    result = build_spot_vwap_acceptance(
        frame,
        as_of_timestamp=datetime(2026, 8, 21, 4, 11, tzinfo=timezone.utc),
    )
    assert result["state"] in {"BULLISH_ACCEPTANCE", "VWAP_TRANSITION", "VWAP_BALANCED"}
    assert result["vwap"] is not None


def test_spot_vwap_does_not_invent_volume_for_index():
    result = build_spot_vwap_acceptance(
        _frame(volume=0.0),
        as_of_timestamp=datetime(2026, 8, 21, 4, 11, tzinfo=timezone.utc),
    )
    assert result["state"] == "VWAP_UNAVAILABLE_ZERO_VOLUME"
    assert result["vwap"] is None


def test_completed_one_minute_break_can_create_early_state():
    frame = _frame()
    vwap = {"direction": "BULLISH"}
    result = build_one_minute_early_evidence(
        frame,
        as_of_timestamp=datetime(2026, 8, 21, 4, 11, tzinfo=timezone.utc),
        vwap_acceptance=vwap,
    )
    assert result["state"] == "BREAK_DETECTED_UP"
    assert result["direction"] == "BULLISH"


def test_futures_vwap_acceptance_is_optional_when_not_persisted():
    assert build_futures_vwap_acceptance({})["state"] == "UNAVAILABLE"
    result = build_futures_vwap_acceptance(
        {"latest_close": 101.0, "vwap": 100.0, "vwap_slope": 0.2}
    )
    assert result["state"] == "BULLISH_ACCEPTANCE"
