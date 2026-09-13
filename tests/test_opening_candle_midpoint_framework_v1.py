from datetime import datetime, timedelta

from market_lab.opening_candle_midpoint_framework_v1 import (
    IST,
    classify_primary_path,
    classify_reclaim_path,
    directional_snapshot_features,
    select_reference_bar,
)


def bar(hour, minute, o, h, l, c):
    start = datetime(2026, 8, 12, hour, minute, tzinfo=IST)
    return {
        "start": start,
        "end": start + timedelta(minutes=4),
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
    }


def row(hour, minute, close):
    ts = datetime(2026, 8, 12, hour, minute, tzinfo=IST)
    return {
        "timestamp": ts,
        "open": float(close),
        "high": float(close + 1),
        "low": float(close - 1),
        "close": float(close),
        "volume": 100.0,
    }


def test_red_and_green_reference_are_independent_and_ignore_opening_bar():
    bars = [
        bar(9, 15, 100, 110, 90, 95),   # opening RED ignored
        bar(9, 20, 95, 106, 94, 104),    # first GREEN
        bar(9, 25, 104, 105, 96, 98),    # first RED
    ]
    green = select_reference_bar(bars, "GREEN")
    red = select_reference_bar(bars, "RED")
    assert green["start"].minute == 20
    assert red["start"].minute == 25


def test_red_break_can_classify_bearish_continuation():
    start = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    rows = [row(10, 0, 94), row(10, 1, 91), row(10, 2, 84)]
    out = classify_primary_path(
        rows,
        break_ts=start,
        midpoint=100,
        boundary=95,
        reference_range=10,
        direction="DOWN",
    )
    assert out["primary_outcome"] == "RED_BEARISH_BREAK_AND_GO"


def test_green_break_can_classify_bullish_continuation():
    start = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    rows = [row(10, 0, 106), row(10, 1, 110), row(10, 2, 116)]
    out = classify_primary_path(
        rows,
        break_ts=start,
        midpoint=100,
        boundary=105,
        reference_range=10,
        direction="UP",
    )
    assert out["primary_outcome"] == "GREEN_BULLISH_BREAK_AND_GO"


def test_red_break_bullish_reclaim_path():
    reclaim = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    rows = [row(10, 0, 101), row(10, 1, 108), row(10, 2, 116)]
    out = classify_reclaim_path(
        rows,
        reclaim_ts=reclaim,
        midpoint=100,
        opposite_boundary=105,
        reference_range=10,
        reclaim_direction="UP",
    )
    assert out["reclaim_outcome"] == "BULLISH_RECLAIM_BREAK_AND_GO"


def test_green_break_bearish_reclaim_path():
    reclaim = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    rows = [row(10, 0, 99), row(10, 1, 92), row(10, 2, 84)]
    out = classify_reclaim_path(
        rows,
        reclaim_ts=reclaim,
        midpoint=100,
        opposite_boundary=95,
        reference_range=10,
        reclaim_direction="DOWN",
    )
    assert out["reclaim_outcome"] == "BEARISH_RECLAIM_BREAK_AND_GO"


def test_directional_features_have_same_positive_semantics_for_both_sides():
    down_rows = [row(10, 0, 100), row(10, 1, 98), row(10, 2, 96), row(10, 3, 94), row(10, 4, 92), row(10, 5, 90)]
    down_idx = {r["timestamp"]: i for i, r in enumerate(down_rows)}
    d = directional_snapshot_features(
        down_rows,
        down_idx,
        ts=down_rows[-1]["timestamp"],
        break_ts=down_rows[2]["timestamp"],
        midpoint=100,
        boundary=97,
        direction="DOWN",
    )

    up_rows = [row(10, 0, 100), row(10, 1, 102), row(10, 2, 104), row(10, 3, 106), row(10, 4, 108), row(10, 5, 110)]
    up_idx = {r["timestamp"]: i for i, r in enumerate(up_rows)}
    u = directional_snapshot_features(
        up_rows,
        up_idx,
        ts=up_rows[-1]["timestamp"],
        break_ts=up_rows[2]["timestamp"],
        midpoint=100,
        boundary=103,
        direction="UP",
    )

    assert d["directional_momentum_5m"] > 0
    assert u["directional_momentum_5m"] > 0
    assert d["directional_distance_beyond_boundary_points"] > 0
    assert u["directional_distance_beyond_boundary_points"] > 0


def test_primary_path_records_later_reclaim_but_continuation_wins_race():
    start = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    rows = [
        row(10, 0, 94),   # boundary break
        row(10, 1, 84),   # continuation target first
        row(10, 2, 101),  # midpoint reclaim later
    ]
    out = classify_primary_path(
        rows,
        break_ts=start,
        midpoint=100,
        boundary=95,
        reference_range=10,
        direction="DOWN",
    )
    assert out["primary_outcome"] == "RED_BEARISH_BREAK_AND_GO"
    assert out["reclaim_timestamp"] is not None
