from datetime import date, datetime, timedelta

from market_lab.domain import IST
from market_lab.hilega_milega_strategy_v1 import IndicatorSnapshot
from market_lab.hilega_mtf_alignment_research_v1 import (
    TFBar,
    TFSnapshot,
    classify_alignment,
    latest_completed_snapshot,
    _passes,
)


def test_alignment_classification():
    assert classify_alignment(IndicatorSnapshot(60.0, 55.0, 52.0)) == "BULLISH"
    assert classify_alignment(IndicatorSnapshot(40.0, 45.0, 48.0)) == "BEARISH"
    assert classify_alignment(IndicatorSnapshot(55.0, 58.0, 52.0)) == "NEUTRAL"
    assert classify_alignment(IndicatorSnapshot(None, None, None)) == "UNREADY"


def test_latest_completed_snapshot_is_causal():
    d = date(2026, 9, 23)
    b1 = TFBar(datetime(2026, 9, 23, 9, 15, tzinfo=IST), 10, 1, 2, 0, 1)
    b2 = TFBar(datetime(2026, 9, 23, 9, 25, tzinfo=IST), 10, 1, 2, 0, 1)
    s1 = TFSnapshot(b1, IndicatorSnapshot(60, 55, 52), "BULLISH")
    s2 = TFSnapshot(b2, IndicatorSnapshot(61, 56, 53), "BULLISH")

    assert latest_completed_snapshot([s1, s2], datetime(2026, 9, 23, 9, 24, 59, tzinfo=IST)) is None
    assert latest_completed_snapshot([s1, s2], datetime(2026, 9, 23, 9, 25, tzinfo=IST)) == s1
    assert latest_completed_snapshot([s1, s2], datetime(2026, 9, 23, 9, 35, tzinfo=IST)) == s2


def test_version_rules():
    d = date(2026, 9, 23)
    b10 = TFBar(datetime(2026, 9, 23, 10, 5, tzinfo=IST), 10, 1, 2, 0, 1)
    b15 = TFBar(datetime(2026, 9, 23, 10, 0, tzinfo=IST), 15, 1, 2, 0, 1)
    bull10 = TFSnapshot(b10, IndicatorSnapshot(60, 55, 52), "BULLISH")
    neutral15 = TFSnapshot(b15, IndicatorSnapshot(55, 58, 52), "NEUTRAL")
    bear15 = TFSnapshot(b15, IndicatorSnapshot(40, 45, 48), "BEARISH")

    assert _passes("V2_5M_10M", "BULLISH", bull10, neutral15)
    assert not _passes("V4_5M_10M_15M", "BULLISH", bull10, neutral15)
    assert _passes("V5_5M_HTF_NON_OPPOSITION", "BULLISH", bull10, neutral15)
    assert not _passes("V5_5M_HTF_NON_OPPOSITION", "BULLISH", bull10, bear15)

def test_parse_time_only_with_session_date():
    from market_lab.hilega_mtf_alignment_research_v1 import _parse_dt
    d = date(2026, 9, 23)

    x = _parse_dt("09:40", d)

    assert x.year == 2026
    assert x.month == 9
    assert x.day == 23
    assert x.hour == 9
    assert x.minute == 40
    assert x.tzinfo is not None
