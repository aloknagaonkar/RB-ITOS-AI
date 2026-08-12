import pandas as pd

from red_bar_lab.strategy.models import Direction, ReferenceLevel, SignalState
from red_bar_lab.strategy.signal_engine import scan_level_signals


IST = "Asia/Kolkata"


def minute_frame(rows):
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


def expand_bucket(start, minutes, o, h, l, c):
    start = pd.Timestamp(start, tz=IST)
    rows = []
    for i in range(minutes):
        value = c if i == minutes - 1 else o
        rows.append(
            (
                (start + pd.Timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M"),
                value,
                h if i == max(0, minutes // 2) else max(value, o),
                l if i == 1 else min(value, o),
                value,
            )
        )
    return rows


def ref(level_type, value, source, high, low, minutes):
    return ReferenceLevel(
        level_type=level_type,
        value=value,
        source_timestamp=pd.Timestamp(source, tz=IST).to_pydatetime(),
        source_high=high,
        source_low=low,
        interval_minutes=minutes,
    )


def test_next_red_candle_direct_bearish_displacement_can_activate():
    rows = []
    rows += expand_bucket("2026-08-12 09:30", 5, 101, 102, 98, 99)
    rows += [
        ("2026-08-12 09:35", 99, 99.2, 98.2, 98.4),
        ("2026-08-12 09:36", 98.4, 98.6, 97.5, 97.8),  # below source low 98
    ]
    level = ref("NEXT_RED_CANDLE", 100, "2026-08-12 09:30", 102, 98, 5)

    attempt = scan_level_signals(minute_frame(rows), level)[0]

    assert attempt.direction is Direction.BEARISH
    assert attempt.state is SignalState.ACTIVE
    assert attempt.cross_timestamp.minute == 30
    assert attempt.confirmation_timestamp.minute == 36


def test_first_candle_direct_bullish_displacement_can_activate():
    rows = []
    rows += expand_bucket("2026-08-12 09:15", 5, 99, 102, 98, 101)
    rows += [
        ("2026-08-12 09:20", 101, 101.8, 100.8, 101.5),
        ("2026-08-12 09:21", 101.5, 103, 101.2, 102.5),  # above source high 102
    ]
    level = ref("FIRST_CANDLE", 100, "2026-08-12 09:15", 102, 98, 5)

    attempt = scan_level_signals(minute_frame(rows), level)[0]

    assert attempt.direction is Direction.BULLISH
    assert attempt.state is SignalState.ACTIVE
    assert attempt.cross_timestamp.minute == 15
    assert attempt.confirmation_timestamp.minute == 21


def test_mid_session_uses_full_30m_source_candle_for_direct_setup():
    rows = []
    rows += expand_bucket("2026-08-12 12:45", 30, 101, 104, 96, 98)
    rows += [
        ("2026-08-12 13:15", 98, 98.5, 96.5, 97),
        ("2026-08-12 13:16", 97, 97.2, 95.5, 95.8),  # below source low 96
    ]
    level = ref("MID_SESSION_1245", 100, "2026-08-12 12:45", 104, 96, 30)

    attempt = scan_level_signals(minute_frame(rows), level)[0]

    assert attempt.direction is Direction.BEARISH
    assert attempt.state is SignalState.ACTIVE
    assert attempt.cross_timestamp.hour == 12
    assert attempt.cross_timestamp.minute == 45
    assert attempt.confirmation_timestamp.hour == 13
    assert attempt.confirmation_timestamp.minute == 16


def test_pd_level_uses_first_completed_current_session_5m_for_initial_setup():
    rows = []
    rows += expand_bucket("2026-08-12 09:15", 5, 99, 100, 95, 96)
    rows += [
        ("2026-08-12 09:20", 96, 96.5, 95.2, 95.5),
        ("2026-08-12 09:21", 95.5, 95.8, 94.5, 94.8),  # below setup low 95
    ]
    level = ref("PD1_315", 100, "2026-08-11 15:15", 102, 98, 15)

    attempt = scan_level_signals(minute_frame(rows), level)[0]

    assert attempt.direction is Direction.BEARISH
    assert attempt.state is SignalState.ACTIVE
    assert attempt.cross_timestamp.hour == 9
    assert attempt.cross_timestamp.minute == 15
    assert attempt.confirmation_timestamp.minute == 21


def test_initial_displacement_fires_only_once_but_later_recross_still_allowed():
    rows = []
    rows += expand_bucket("2026-08-12 09:15", 5, 101, 102, 98, 99)  # direct bearish
    rows += expand_bucket("2026-08-12 09:20", 99, 99, 97, 98)
    rows += expand_bucket("2026-08-12 09:25", 98, 103, 98, 101)  # later bullish recross
    rows += [
        ("2026-08-12 09:30", 101, 103.5, 101, 103),
    ]
    level = ref("FIRST_CANDLE", 100, "2026-08-12 09:15", 102, 98, 5)

    attempts = scan_level_signals(minute_frame(rows), level)

    direct = [a for a in attempts if a.cross_timestamp.minute == 15]
    recross = [a for a in attempts if a.cross_timestamp.minute == 25]
    assert len(direct) == 1
    assert len(recross) == 1
    assert direct[0].direction is Direction.BEARISH
    assert recross[0].direction is Direction.BULLISH
