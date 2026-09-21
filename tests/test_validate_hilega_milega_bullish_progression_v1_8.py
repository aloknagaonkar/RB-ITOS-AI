from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.validate_hilega_milega_bullish_progression_v1_8 import build_progression_timeline

IST = ZoneInfo("Asia/Kolkata")


def bar(h, m, close=100):
    return {"start": datetime(2026, 9, 21, h, m, tzinfo=IST), "close": close}


def test_active_setup_can_form_below_50():
    bars = [bar(11,20), bar(11,25), bar(11,30)]
    rsi = [40,44,48]
    ema = [41,42,45]
    wma = [50,49,47]
    rows = build_progression_timeline(bars, rsi, ema, wma, "2026-09-21")
    assert any("ACTIVE_SETUP" in r["events"] for r in rows)
    assert not any("BULLISH" == e.strip() for r in rows for e in r["events"].split("|"))


def test_bullish_can_arrive_later_when_rsi_crosses_50():
    bars = [bar(11,20), bar(11,25), bar(11,30), bar(11,35)]
    rsi = [40,44,48,54]
    ema = [41,42,45,48]
    wma = [50,49,47,46]
    rows = build_progression_timeline(bars, rsi, ema, wma, "2026-09-21")
    assert any("RSI↑50" in r["events"] and "BULLISH" in r["events"] for r in rows)


def test_strong_when_ema_is_above_wma():
    bars = [bar(11,20), bar(11,25), bar(11,30), bar(11,35)]
    rsi = [40,44,48,55]
    ema = [41,42,46,52]
    wma = [50,49,45,47]
    rows = build_progression_timeline(bars, rsi, ema, wma, "2026-09-21")
    assert any("STRONG_BULLISH" in r["events"] for r in rows)


def test_full_alignment_requires_all_three_above_50_and_ordered():
    bars = [bar(11,20), bar(11,25), bar(11,30), bar(11,35), bar(11,40)]
    rsi = [40,44,48,55,65]
    ema = [41,42,46,52,58]
    wma = [50,49,45,47,54]
    rows = build_progression_timeline(bars, rsi, ema, wma, "2026-09-21")
    assert any("FULL_BULLISH_ALIGNMENT" in r["events"] for r in rows)


def test_rsi_down_wma_invalidates_progression():
    bars = [bar(10,40), bar(10,45), bar(10,50), bar(10,55)]
    rsi = [45,48,60,49]
    ema = [46,47,55,53]
    wma = [52,51,53,51]
    rows = build_progression_timeline(bars, rsi, ema, wma, "2026-09-21")
    assert any("INVALIDATION" in r["events"] for r in rows)
