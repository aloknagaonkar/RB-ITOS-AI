from datetime import time

import pandas as pd

from red_bar_lab.services.red_bar_v2_validation_diagnostics import (
    deterministic_research_exit_timestamps,
    diagnose_session_regime,
    evaluate_session_completeness,
)


IST = "Asia/Kolkata"


def _candles(start: float, end: float, *, periods: int = 375) -> pd.DataFrame:
    timestamps = pd.date_range("2026-08-18 09:15", periods=periods, freq="1min", tz=IST)
    closes = pd.Series(
        [start + (end - start) * index / max(periods - 1, 1) for index in range(periods)]
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": [1000.0] * periods,
        }
    )


def test_regime_diagnostics_explain_threshold_result():
    trend = diagnose_session_regime(_candles(100.0, 101.0))
    assert trend.regime == "TREND_UP"
    assert trend.reason == "POSITIVE_DISPLACEMENT_AND_EFFICIENCY"
    assert trend.net_points == 1.0
    assert trend.net_return_pct == 1.0
    assert trend.directional_efficiency == 1.0

    range_day = diagnose_session_regime(_candles(100.0, 100.1))
    assert range_day.regime == "RANGE"
    assert range_day.reason == "NET_DISPLACEMENT_BELOW_THRESHOLD"


def test_session_completeness_is_independent_from_alignment():
    complete = evaluate_session_completeness(_candles(100.0, 101.0))
    assert complete.status == "COMPLETE"
    assert complete.observed_rows == 375
    assert complete.coverage_pct == 100.0

    partial = evaluate_session_completeness(_candles(100.0, 101.0, periods=274))
    assert partial.status == "PARTIAL"
    assert partial.observed_rows == 274
    assert "ROW_COUNT_BELOW_EXPECTED" in partial.reason
    assert "EARLY_SESSION_END" in partial.reason


def test_research_exit_timestamps_are_deterministic_utc_values():
    exits = deterministic_research_exit_timestamps(
        "2026-08-18",
        local_times=(time(10, 30), time(12, 30), time(14, 30)),
    )
    assert [value.isoformat() for value in exits] == [
        "2026-08-18T05:00:00+00:00",
        "2026-08-18T07:00:00+00:00",
        "2026-08-18T09:00:00+00:00",
    ]
