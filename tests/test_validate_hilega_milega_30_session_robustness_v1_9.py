from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.validate_hilega_milega_30_session_robustness_v1_9 import build_session_timeline

IST = ZoneInfo("Asia/Kolkata")


def bar(day, h, m, close=100):
    return {"start": datetime(2026, 9, day, h, m, tzinfo=IST), "close": close}


def test_opening_alignment_requires_next_bar_persistence():
    bars = [bar(18,9,15), bar(18,9,20)]
    rsi = [65,62]
    ema = [55,56]
    wma = [51,53]
    rows = build_session_timeline(bars, rsi, ema, wma, "2026-09-18")
    assert rows[0]["events"] == "OPENING_ALIGNMENT"
    assert any("OPENING_BULLISH_CONFIRMED" in r["events"] for r in rows)


def test_opening_alignment_can_fail_on_next_bar():
    bars = [bar(18,9,15), bar(18,9,20)]
    rsi = [65,50]
    ema = [55,54]
    wma = [51,52]
    rows = build_session_timeline(bars, rsi, ema, wma, "2026-09-18")
    assert any("OPENING_ALIGNMENT_FAILED" in r["events"] for r in rows)


def test_first_rsi_down_wma_marks_weakening_not_end():
    bars = [bar(21,10,40), bar(21,10,45), bar(21,10,50), bar(21,10,55)]
    rsi = [45,48,60,49]
    ema = [46,47,55,53]
    wma = [52,51,53,51]
    rows = build_session_timeline(bars, rsi, ema, wma, "2026-09-21")
    assert any("WEAKENING" in r["events"] for r in rows)
    assert not any("BULLISH_END_CONFIRMED" in r["events"] for r in rows)


def test_recovery_next_bar_keeps_continuation():
    bars = [bar(21,10,40), bar(21,10,45), bar(21,10,50), bar(21,10,55), bar(21,11,0)]
    rsi = [45,48,60,49,58]
    ema = [46,47,55,53,54]
    wma = [52,51,53,51,52]
    rows = build_session_timeline(bars, rsi, ema, wma, "2026-09-21")
    assert any("WEAKENING_RECOVERY" in r["events"] for r in rows)
    assert not any("BULLISH_END_CONFIRMED" in r["events"] for r in rows)


def test_second_bar_below_wma_confirms_end():
    bars = [bar(21,10,40), bar(21,10,45), bar(21,10,50), bar(21,10,55), bar(21,11,0)]
    rsi = [45,48,60,49,48]
    ema = [46,47,55,53,52]
    wma = [52,51,53,51,50]
    rows = build_session_timeline(bars, rsi, ema, wma, "2026-09-21")
    assert any("BULLISH_END_CONFIRMED" in r["events"] for r in rows)
