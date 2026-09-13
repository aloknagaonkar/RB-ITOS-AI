from datetime import datetime, timedelta, timezone

from market_lab.opening_red_midpoint_evidence_v1 import (
    aggregate_5m,
    classify_outcome,
    count_midpoint_crosses,
    select_reference_red_bar,
)

IST = timezone(timedelta(hours=5, minutes=30))


def minute(h, m, o, hi, lo, c):
    return {
        "session_date": "2026-08-12",
        "timestamp": datetime(2026, 8, 12, h, m, tzinfo=IST),
        "open": float(o),
        "high": float(hi),
        "low": float(lo),
        "close": float(c),
        "volume": 100.0,
    }


def five_minutes(start_h, start_m, opens_closes):
    rows = []
    for i, (o, c) in enumerate(opens_closes):
        m = start_m + i
        rows.append(
            minute(
                start_h,
                m,
                o,
                max(o, c) + 1,
                min(o, c) - 1,
                c,
            )
        )
    return rows


def test_first_5m_is_ignored_and_next_red_is_reference():
    rows = []
    rows += five_minutes(
        9,
        15,
        [(100, 102), (102, 103), (103, 104), (104, 105), (105, 106)],
    )
    rows += five_minutes(
        9,
        20,
        [(106, 107), (107, 106), (106, 105), (105, 104), (104, 103)],
    )
    bars = aggregate_5m(rows)
    ref = select_reference_red_bar(bars)
    assert ref is not None
    assert ref["start"].hour == 9
    assert ref["start"].minute == 20
    assert ref["close"] < ref["open"]


def test_midpoint_is_full_range_midpoint():
    rows = five_minutes(
        9,
        20,
        [(100, 101), (101, 100), (100, 99), (99, 98), (98, 97)],
    )
    ref = select_reference_red_bar(aggregate_5m(rows))
    assert ref is not None
    midpoint = (ref["high"] + ref["low"]) / 2
    assert midpoint == (102.0 + 96.0) / 2


def test_break_and_go_before_reclaim():
    low_break = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    rows = [
        minute(10, 0, 95, 96, 94, 95),
        minute(10, 1, 94, 95, 92, 93),
        minute(10, 2, 93, 94, 88, 89),
    ]
    out = classify_outcome(
        rows,
        low_break,
        midpoint=100,
        reference_low=96,
        reference_range=10,
    )
    # continuation level = 96 - max(10, 5) = 86; not yet reached
    assert out["outcome_label"] == "SIDEWAYS_NO_CONTINUATION"


def test_break_and_go_when_threshold_reached():
    low_break = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    rows = [
        minute(10, 0, 95, 96, 94, 95),
        minute(10, 1, 94, 95, 84, 85),
    ]
    out = classify_outcome(
        rows,
        low_break,
        midpoint=100,
        reference_low=96,
        reference_range=10,
    )
    assert out["outcome_label"] == "BREAK_AND_GO"
    assert out["minutes_to_continuation"] == 1


def test_false_break_reclaim():
    low_break = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    rows = [
        minute(10, 0, 95, 96, 94, 95),
        minute(10, 1, 96, 101, 95, 101),
    ]
    out = classify_outcome(
        rows,
        low_break,
        midpoint=100,
        reference_low=96,
        reference_range=10,
    )
    assert out["outcome_label"] == "FALSE_BREAK_RECLAIM"
    assert out["midpoint_reclaim_timestamp"] is not None


def test_midpoint_cross_count_tracks_repeated_reclaims():
    start = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    rows = [
        minute(10, 0, 99, 100, 98, 99),   # below
        minute(10, 1, 99, 102, 99, 101),  # above => cross 1
        minute(10, 2, 101, 102, 98, 99),  # below => cross 2
        minute(10, 3, 99, 102, 99, 101),  # above => cross 3
    ]
    assert count_midpoint_crosses(
        rows,
        start,
        start + timedelta(minutes=3),
        100,
    ) == 3
