from datetime import datetime

import pandas as pd

from red_bar_lab.services.red_bar_diagnostics import build_red_bar_cross_trace


IST = "Asia/Kolkata"


def _minute_frame(closes: list[float]) -> pd.DataFrame:
    timestamps = pd.date_range(
        "2026-08-12 09:25:00",
        periods=len(closes),
        freq="1min",
        tz=IST,
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [100] * len(closes),
        }
    )


def _lifecycle(midpoint: float = 100.0) -> dict[str, object]:
    return {
        "reference_persisted": True,
        "source_timestamp": "2026-08-12T09:30:00+05:30",
        "interval_minutes": 5,
        "midpoint": midpoint,
    }


def test_cross_trace_reports_bullish_midpoint_cross():
    # 09:30 bucket closes below midpoint; 09:35 bucket closes above it.
    frame = _minute_frame(
        [98, 98, 98, 98, 98, 99, 99, 99, 99, 99, 101, 101, 101, 101, 101]
    )
    rows = build_red_bar_cross_trace(frame, _lifecycle())

    assert rows
    assert rows[0]["timestamp"].strftime("%H:%M") == "09:35"
    assert rows[0]["evaluation"] == "BULLISH_CROSS"
    assert rows[0]["bullish_condition"] is True
    assert rows[0]["bearish_condition"] is False


def test_cross_trace_reports_no_cross_when_both_closes_below_midpoint():
    frame = _minute_frame(
        [98, 98, 98, 98, 98, 99, 99, 99, 99, 99, 99.5, 99.5, 99.5, 99.5, 99.5]
    )
    rows = build_red_bar_cross_trace(frame, _lifecycle())

    assert rows
    assert rows[0]["evaluation"] == "NO_CROSS"
    assert "below the midpoint" in rows[0]["reason"]


def test_cross_trace_ignores_incomplete_five_minute_bucket():
    # Only four rows exist in the post-reference 09:35 bucket.
    frame = _minute_frame(
        [98, 98, 98, 98, 98, 99, 99, 99, 99, 99, 101, 101, 101, 101]
    )
    rows = build_red_bar_cross_trace(frame, _lifecycle())

    assert rows == []


def test_cross_trace_requires_persisted_reference():
    frame = _minute_frame([98] * 15)
    rows = build_red_bar_cross_trace(
        frame,
        {
            "reference_persisted": False,
            "source_timestamp": None,
            "interval_minutes": None,
            "midpoint": None,
        },
    )
    assert rows == []
