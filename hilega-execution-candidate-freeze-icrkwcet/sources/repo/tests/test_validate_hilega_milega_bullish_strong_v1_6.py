from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.validate_hilega_milega_bullish_strong_v1_6 import detect_states

IST = ZoneInfo("Asia/Kolkata")


def bar(h, m, close=100):
    return {"start": datetime(2026, 9, 21, h, m, tzinfo=IST), "close": close}


def test_bullish_when_rsi_crosses_ema_then_wma_above_50():
    bars = [bar(10, 40), bar(10, 45), bar(10, 50)]
    rsi = [45, 48, 55]
    ema = [46, 47, 54]
    wma = [52, 51, 53]
    rows = detect_states(bars, rsi, ema, wma, "2026-09-21")
    assert len(rows) == 1
    assert rows[0]["bullish_time"].endswith("10:50:00+05:30")


def test_strong_same_candle_when_ema_also_above_wma():
    bars = [bar(10, 40), bar(10, 45), bar(10, 50)]
    rsi = [45, 48, 60]
    ema = [46, 47, 55]
    wma = [52, 51, 53]
    rows = detect_states(bars, rsi, ema, wma, "2026-09-21")
    assert rows[0]["strong_delay_minutes"] == 0
    assert rows[0]["strong_same_candle"] is True


def test_strong_can_upgrade_later():
    bars = [bar(13, 10), bar(13, 15), bar(13, 20)]
    rsi = [45, 58, 62]
    ema = [46, 50, 57]
    wma = [55, 54, 56]
    rows = detect_states(bars, rsi, ema, wma, "2026-09-21")
    assert len(rows) == 1
    assert rows[0]["strong_delay_minutes"] == 5


def test_no_bullish_if_rsi_cross_wma_below_50():
    bars = [bar(11, 0), bar(11, 5), bar(11, 10)]
    rsi = [35, 38, 40]
    ema = [36, 37, 37.5]
    wma = [42, 41, 39]
    rows = detect_states(bars, rsi, ema, wma, "2026-09-21")
    assert rows == []
