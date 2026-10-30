from datetime import datetime, timedelta, timezone

from market_lab.midpoint_bullish_reclaim_research_v1 import classify_bullish

IST = timezone(timedelta(hours=5, minutes=30))


def row(minute, close):
    ts = datetime(2026, 8, 12, 10, minute, tzinfo=IST)
    return {
        "timestamp": ts,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 100,
    }


def test_bullish_break_and_go():
    reclaim = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    rows = [row(0, 101), row(1, 106), row(2, 116)]
    out = classify_bullish(
        rows,
        reclaim,
        midpoint=100,
        reference_high=105,
        reference_range=10,
    )
    assert out["bullish_outcome"] == "BULLISH_BREAK_AND_GO"


def test_failed_bullish_reclaim():
    reclaim = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    rows = [row(0, 101), row(1, 99)]
    out = classify_bullish(
        rows,
        reclaim,
        midpoint=100,
        reference_high=105,
        reference_range=10,
    )
    assert out["bullish_outcome"] == "FAILED_BULLISH_RECLAIM"
