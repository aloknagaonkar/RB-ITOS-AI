from datetime import date

import pandas as pd

from red_bar_lab.strategy.level_engine import (
    aggregate_candles,
    build_daily_levels,
    build_first_candle_level,
    build_mid_session_level,
    build_next_red_candle_level,
    build_previous_315_level,
)


def frame(day: str, closes=None):
    ts = pd.date_range(f"{day} 09:15", f"{day} 15:29", freq="1min", tz="Asia/Kolkata")
    data = []
    for i, stamp in enumerate(ts):
        open_ = 100 + i * 0.1
        close = open_ + 0.2
        data.append({"timestamp": stamp.tz_convert("UTC"), "open": open_, "high": close + 1, "low": open_ - 1, "close": close, "volume": 1})
    result = pd.DataFrame(data)
    if closes:
        for index, values in closes.items():
            mask = result["timestamp"].dt.tz_convert("Asia/Kolkata").dt.strftime("%H:%M") == index
            for key, value in values.items():
                result.loc[mask, key] = value
    return result


def test_previous_day_level_uses_1515_to_1530_fifteen_minute_bar():
    source = frame("2026-08-05")
    level = build_previous_315_level(source, 1)
    assert level is not None
    assert level.interval_minutes == 15
    assert level.source_timestamp.hour == 15 and level.source_timestamp.minute == 15


def test_first_candle_uses_0915_five_minute_bar():
    level = build_first_candle_level(frame("2026-08-05"))
    assert level is not None
    assert level.interval_minutes == 5
    assert level.source_timestamp.hour == 9 and level.source_timestamp.minute == 15


def test_next_red_search_starts_from_0920_not_first_candle():
    source = frame("2026-08-05")
    # Make 09:15-09:19 red, but first eligible red bar is 09:25-09:29.
    ist = source["timestamp"].dt.tz_convert("Asia/Kolkata")
    source.loc[(ist.dt.time >= pd.Timestamp("09:15").time()) & (ist.dt.time < pd.Timestamp("09:20").time()), "close"] = 90
    source.loc[(ist.dt.time >= pd.Timestamp("09:25").time()) & (ist.dt.time < pd.Timestamp("09:30").time()), "close"] = 80
    level = build_next_red_candle_level(source)
    assert level is not None
    assert level.source_timestamp.hour == 9 and level.source_timestamp.minute == 25


def test_mid_session_uses_1245_to_1315_thirty_minute_bar():
    level = build_mid_session_level(frame("2026-08-05"))
    assert level is not None
    assert level.interval_minutes == 30
    assert level.source_timestamp.hour == 12 and level.source_timestamp.minute == 45


def test_daily_levels_keep_latest_ten_completed_trading_days():
    current = frame("2026-08-05")
    previous = []
    for day in pd.bdate_range("2026-07-20", "2026-08-04"):
        previous.append((day.date(), frame(day.date().isoformat())))
    result = build_daily_levels(date(2026, 8, 5), current, previous, previous_days=10)
    assert len(result.previous_day_levels) == 10
    assert result.previous_day_levels[0].level_type == "PD1_315"
    assert result.previous_day_levels[-1].level_type == "PD10_315"
