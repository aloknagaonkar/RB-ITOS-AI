import pandas as pd

from red_bar_lab.strategy.models import Direction, ReferenceLevel, SignalState
from red_bar_lab.strategy.signal_engine import scan_level_signals, scan_reference_levels


IST = "Asia/Kolkata"


def minute_frame(rows):
    """rows: (timestamp, open, high, low, close)"""
    return pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp(ts, tz=IST),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 0,
            }
            for ts, o, h, l, c in rows
        ]
    )


def expand_five(start, o, h, l, c):
    """Create five deterministic 1m rows whose aggregate matches the intent."""
    start = pd.Timestamp(start, tz=IST)
    values = [o, o, o, o, c]
    rows = []
    for i in range(5):
        rows.append(
            (
                (start + pd.Timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M"),
                values[i],
                h if i == 2 else max(values[i], values[max(0, i - 1)]),
                l if i == 1 else min(values[i], values[max(0, i - 1)]),
                values[i],
            )
        )
    return rows


def level(value=100.0, source="2026-08-05 09:15"):
    return ReferenceLevel(
        level_type="FIRST_CANDLE",
        value=value,
        source_timestamp=pd.Timestamp(source, tz=IST).to_pydatetime(),
        source_high=102,
        source_low=98,
        interval_minutes=5,
    )


def base_bullish_setup():
    rows = []
    rows += expand_five("2026-08-05 09:15", 99, 100, 98, 99)
    rows += expand_five("2026-08-05 09:20", 99, 102, 99, 101)  # Candle A
    return rows


def test_first_one_minute_close_above_setup_high_makes_active():
    rows = base_bullish_setup()
    rows += [
        ("2026-08-05 09:25", 101, 102, 100, 101.5),
        ("2026-08-05 09:26", 101.5, 103.2, 101, 102.5),  # confirms
        ("2026-08-05 09:27", 102.5, 103, 102, 102.7),
    ]
    attempt = scan_level_signals(minute_frame(rows), level())[0]
    assert attempt.state is SignalState.ACTIVE
    assert attempt.direction is Direction.BULLISH
    assert attempt.confirmation_timestamp.minute == 26
    assert attempt.confirmation_delay_minutes == 2
    assert attempt.underlying_entry == 102.5


def test_bearish_one_minute_close_below_setup_low_makes_active():
    rows = []
    rows += expand_five("2026-08-05 09:15", 101, 102, 100, 101)
    rows += expand_five("2026-08-05 09:20", 101, 101, 98, 99)  # A bearish cross
    rows += [
        ("2026-08-05 09:25", 99, 99.5, 98.2, 98.5),
        ("2026-08-05 09:26", 98.5, 98.8, 97.2, 97.5),  # < A low 98
    ]
    attempt = scan_level_signals(minute_frame(rows), level())[0]
    assert attempt.state is SignalState.ACTIVE
    assert attempt.direction is Direction.BEARISH
    assert attempt.confirmation_timestamp.minute == 26
    assert attempt.confirmation_delay_minutes == 2
    assert attempt.underlying_entry == 97.5


def test_wick_above_setup_high_without_close_does_not_confirm():
    rows = base_bullish_setup()
    rows += [
        ("2026-08-05 09:25", 101, 103, 100, 101.5),
        ("2026-08-05 09:26", 101.5, 102.8, 101, 101.8),
        ("2026-08-05 09:27", 101.8, 102.9, 101, 101.9),
        ("2026-08-05 09:28", 101.9, 103.5, 101, 101.7),
        ("2026-08-05 09:29", 101.7, 102.5, 101, 101.6),
    ]
    attempt = scan_level_signals(minute_frame(rows), level())[0]
    assert attempt.state is SignalState.TIMEOUT
    assert attempt.confirmation_timestamp is None
    assert attempt.underlying_entry is None


def test_incomplete_confirmation_window_remains_awaiting():
    rows = base_bullish_setup()
    rows += [
        ("2026-08-05 09:25", 101, 101.8, 100, 101.2),
        ("2026-08-05 09:26", 101.2, 101.9, 100.5, 101.4),
    ]
    attempt = scan_level_signals(minute_frame(rows), level())[0]
    assert attempt.state is SignalState.AWAITING_CONFIRMATION


def test_partial_current_five_minute_bucket_is_not_setup_candle():
    rows = []
    rows += expand_five("2026-08-05 09:15", 99, 100, 98, 99)
    # only 3 rows in 09:20 setup bucket -> must not be treated as completed A
    rows += [
        ("2026-08-05 09:20", 99, 101, 99, 100.5),
        ("2026-08-05 09:21", 100.5, 102, 100, 101),
        ("2026-08-05 09:22", 101, 103, 100, 102),
    ]
    assert scan_level_signals(minute_frame(rows), level()) == ()


def test_wick_cross_of_midpoint_without_five_minute_close_is_ignored():
    rows = []
    rows += expand_five("2026-08-05 09:15", 99, 100, 98, 99)
    rows += expand_five("2026-08-05 09:20", 99, 102, 98, 99.5)
    rows += expand_five("2026-08-05 09:25", 99.5, 101, 98, 99.8)
    assert scan_level_signals(minute_frame(rows), level()) == ()


def test_level_not_used_before_source_candle_complete():
    late = ReferenceLevel(
        level_type="MID_SESSION_1245",
        value=100,
        source_timestamp=pd.Timestamp("2026-08-05 12:45", tz=IST).to_pydatetime(),
        source_high=102,
        source_low=98,
        interval_minutes=30,
    )
    rows = []
    rows += expand_five("2026-08-05 13:10", 99, 100, 98, 99)
    rows += expand_five("2026-08-05 13:15", 99, 102, 99, 101)
    rows += [
        ("2026-08-05 13:20", 101, 103, 101, 102.5),
    ]
    attempts = scan_level_signals(minute_frame(rows), late)
    assert len(attempts) == 1
    assert attempts[0].cross_timestamp.minute == 15


def test_scan_multiple_levels_orders_attempts():
    rows = base_bullish_setup()
    rows += [
        ("2026-08-05 09:25", 101, 103, 101, 102.5),
    ]
    result = scan_reference_levels(
        minute_frame(rows),
        (level(100), level(100.5)),
    )
    assert len(result.active) == 2
