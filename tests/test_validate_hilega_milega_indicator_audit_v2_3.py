from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.validate_hilega_milega_indicator_audit_v2_3 import build_rows

IST = ZoneInfo("Asia/Kolkata")


def bar(h, m, close):
    return {
        "start": datetime(2026, 5, 29, h, m, tzinfo=IST),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
    }


def test_build_rows_inclusive_range():
    bars = [
        bar(9, 30, 100),
        bar(9, 35, 101),
        bar(9, 40, 102),
        bar(9, 45, 103),
        bar(9, 50, 104),
    ]

    rsi = [45, 55, 58, 49, 47]
    ema = [46, 52, 55, 52, 49]
    wma = [47, 50, 51, 51, 50]

    rows = build_rows(
        bars, rsi, ema, wma,
        "2026-05-29", "09:35", "09:45"
    )

    assert [r["time"] for r in rows] == ["09:35", "09:40", "09:45"]
    assert rows[0]["rsi_gt_50"] is True
    assert rows[0]["ema3_gt_wma21"] is True
    assert rows[-1]["rsi_gt_wma21"] is False


def test_deltas():
    bars = [bar(9, 35, 100)]
    rows = build_rows(
        bars,
        [60.0],
        [55.0],
        [50.0],
        "2026-05-29",
        "09:35",
        "09:35",
    )
    assert rows[0]["rsi_minus_ema3"] == 5.0
    assert rows[0]["rsi_minus_wma21"] == 10.0
    assert rows[0]["ema3_minus_wma21"] == 5.0
