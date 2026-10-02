from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.validate_hilega_milega_bullish_previous_dates_v1_3 import detect_sequence_confirmations

IST = ZoneInfo("Asia/Kolkata")


def _bars_simple(times):
    out = []
    for t in times:
        h, m = map(int, t.split(":"))
        s = datetime(2026, 9, 21, h, m, tzinfo=IST)
        out.append({"start": s, "end": s + timedelta(minutes=4), "close": 100.0})
    return out


def test_accepts_today_style_two_bar_sequence():
    bars = _bars_simple(["10:35", "10:40", "10:45", "10:50"])
    r = [40, 50, 52, 60]
    e = [45, 48, 50, 55]
    w = [53, 52, 51, 52]
    rows = detect_sequence_confirmations(bars, r, e, w, "2026-09-21")
    assert len(rows) == 1
    assert rows[0]["confirmation_time"].startswith("2026-09-21T10:50")
    assert rows[0]["sequence_minutes"] == 10


def test_accepts_split_wma_crosses_across_two_bars():
    bars = _bars_simple(["13:05", "13:10", "13:15", "13:20"])
    r = [40, 50, 60, 65]
    e = [45, 47, 54, 61]
    w = [56, 55, 56, 57]
    rows = detect_sequence_confirmations(bars, r, e, w, "2026-09-21")
    assert len(rows) == 1
    assert rows[0]["rsi_wma_time"].startswith("2026-09-21T13:15")
    assert rows[0]["ema_wma_time"].startswith("2026-09-21T13:20")


def test_ignores_wma_crosses_that_happened_before_rsi_ema_cross():
    bars = _bars_simple(["09:15", "09:20", "09:25", "09:30", "09:35", "09:40", "09:45"])
    r = [58, 60, 62, 63, 64, 65, 68]
    e = [55, 58, 60, 62, 64.2, 66, 67]
    w = [57, 57, 58, 59, 60, 61, 62]
    rows = detect_sequence_confirmations(bars, r, e, w, "2026-09-21")
    assert rows == []


def test_long_sequence_is_not_rejected_by_duration():
    bars = _bars_simple(["10:00", "10:05", "10:10", "10:15", "10:20", "10:25", "10:30"])
    # 10:05 RSI↑EMA, 10:25 RSI↑WMA, 10:30 EMA↑WMA => 25-minute sequence.
    r = [40, 50, 51, 52, 53, 60, 65]
    e = [45, 48, 49, 50, 51, 54, 61]
    w = [56, 55, 54.5, 54, 53.5, 55, 57]
    rows = detect_sequence_confirmations(bars, r, e, w, "2026-09-21")
    assert len(rows) == 1
    assert rows[0]["confirmation_time"].startswith("2026-09-21T10:30")
    assert rows[0]["sequence_minutes"] == 25
