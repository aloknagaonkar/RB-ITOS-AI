import pandas as pd

from red_bar_lab.intelligence.stateful_multitimeframe_regime import (
    StatefulMultiTimeframeRegimeEngine,
)


def trending_candles(count=120, step=1.0):
    price = 100.0
    rows = []
    for index, ts in enumerate(
        pd.date_range("2026-08-13 09:15", periods=count, freq="1min")
    ):
        wave = 2.0 if index % 8 < 4 else -1.0
        close = price + step + wave * 0.2
        rows.append({
            "timestamp": ts,
            "open": price,
            "high": max(price, close) + 0.6,
            "low": min(price, close) - 0.6,
            "close": close,
            "volume": 0,
        })
        price = close
    return pd.DataFrame(rows)


def flat_candles(count=120):
    rows = []
    for ts in pd.date_range("2026-08-13 09:15", periods=count, freq="1min"):
        rows.append({
            "timestamp": ts,
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 0,
        })
    return pd.DataFrame(rows)


def test_confirmed_swings_are_distinct_when_structure_valid():
    snapshot = StatefulMultiTimeframeRegimeEngine().evaluate(
        trending_candles(),
        trending_candles(step=1.5),
    )
    if snapshot.structure_status == "CONFIRMED":
        assert snapshot.last_swing_high != snapshot.last_swing_low
        assert snapshot.break_level != snapshot.invalidation_level
        assert snapshot.swing_high_timestamp
        assert snapshot.swing_low_timestamp


def test_invalid_structure_does_not_publish_break_levels():
    snapshot = StatefulMultiTimeframeRegimeEngine().evaluate(
        flat_candles(),
        flat_candles(),
    )
    assert snapshot.structure_status in {
        "STRUCTURE_UNAVAILABLE",
        "STRUCTURE_DISTANCE_TOO_SMALL",
    }
    assert snapshot.break_level is None
    assert snapshot.invalidation_level is None
    assert snapshot.execution_allowed is False


def test_structure_diagnostics_include_pivot_type():
    snapshot = StatefulMultiTimeframeRegimeEngine().evaluate(
        trending_candles(),
        trending_candles(step=1.5),
    )
    assert all("type" in item for item in snapshot.structure_diagnostics)
