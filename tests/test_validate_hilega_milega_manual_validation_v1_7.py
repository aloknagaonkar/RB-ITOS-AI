from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.validate_hilega_milega_manual_validation_v1_7 import build_manual_timeline

IST = ZoneInfo("Asia/Kolkata")


def bar(h, m, close=100):
    return {"start": datetime(2026, 9, 21, h, m, tzinfo=IST), "close": close}


def test_bullish_start_and_immediate_strong():
    bars = [bar(10,40), bar(10,45), bar(10,50)]
    rsi = [45,48,60]
    ema = [46,47,55]
    wma = [52,51,53]
    rows = build_manual_timeline(bars, rsi, ema, wma, "2026-09-21")
    assert any("BULLISH_START" in r["events"] for r in rows)
    assert any("STRONG_BULLISH" in r["events"] for r in rows)


def test_rsi_down_wma_ends_bullish_state():
    bars = [bar(10,40), bar(10,45), bar(10,50), bar(10,55)]
    rsi = [45,48,60,49]
    ema = [46,47,55,53]
    wma = [52,51,53,51]
    rows = build_manual_timeline(bars, rsi, ema, wma, "2026-09-21")
    assert any("BULLISH_END" in r["events"] for r in rows)


def test_existing_bullish_rsi_ema_cross_is_continuation_not_new_start():
    bars = [bar(10,40), bar(10,45), bar(10,50), bar(10,55), bar(11,0)]
    rsi = [45,48,60,52,58]
    ema = [46,47,55,54,55]
    wma = [52,51,53,50,49]
    rows = build_manual_timeline(bars, rsi, ema, wma, "2026-09-21")
    cont = [r for r in rows if "CONTINUATION" in r["events"]]
    assert cont
    assert sum("BULLISH_START" in r["events"] for r in rows) == 1


def test_below_50_rsi_wma_cross_does_not_start_bullish():
    bars = [bar(11,0), bar(11,5), bar(11,10)]
    rsi = [35,38,40]
    ema = [36,37,37.5]
    wma = [42,41,39]
    rows = build_manual_timeline(bars, rsi, ema, wma, "2026-09-21")
    assert not any("BULLISH_START" in r["events"] for r in rows)
    assert any("BELOW_50" in r["events"] for r in rows)
