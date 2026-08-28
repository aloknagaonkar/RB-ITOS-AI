from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
import os
from typing import Iterable

import pandas as pd

from red_bar_lab.strategy.models import (
    Direction,
    ReferenceLevel,
    SignalAttempt,
    SignalState,
)


IST = "Asia/Kolkata"
SAME_SESSION_INITIAL_LEVELS = {
    "FIRST_CANDLE",
    "NEXT_RED_CANDLE",
    "MID_SESSION_1245",
}


def _legacy_enabled() -> bool:
    """Check if the base (legacy) Red Bar strategy is enabled."""
    raw = os.getenv("RED_BAR_LEGACY_V1_ENABLED")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SignalScanResult:
    attempts: tuple[SignalAttempt, ...]

    @property
    def active(self) -> tuple[SignalAttempt, ...]:
        return tuple(item for item in self.attempts if item.state is SignalState.ACTIVE)

    @property
    def failed(self) -> tuple[SignalAttempt, ...]:
        return tuple(
            item
            for item in self.attempts
            if item.state in {
                SignalState.TIMEOUT,
                SignalState.CONFIRMATION_FAILED,
            }
        )

    @property
    def awaiting(self) -> tuple[SignalAttempt, ...]:
        return tuple(
            item
            for item in self.attempts
            if item.state is SignalState.AWAITING_CONFIRMATION
        )


def _to_ist(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(
            columns=("timestamp", "open", "high", "low", "close", "volume")
        )
    result = frame.copy()
    ts = pd.to_datetime(result["timestamp"], errors="coerce", utc=True)
    result = result.loc[ts.notna()].copy()
    result["timestamp"] = ts.loc[ts.notna()].dt.tz_convert(IST)
    return (
        result.sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )


def _available_from(level: ReferenceLevel) -> datetime:
    """First instant when the source level is fully known."""
    return level.source_timestamp + timedelta(minutes=level.interval_minutes)


def _is_bullish_cross(previous_close: float, current_close: float, level: float) -> bool:
    return previous_close <= level < current_close


def _is_bearish_cross(previous_close: float, current_close: float, level: float) -> bool:
    return previous_close >= level > current_close


def _is_previous_day_level(level: ReferenceLevel) -> bool:
    return level.level_type.startswith("PD") and level.level_type.endswith("_315")


def _completed_setup_bars(
    frame: pd.DataFrame,
    minutes: int = 5,
    session_end: time = time(15, 30),
) -> pd.DataFrame:
    """Build only complete N-minute candles from one-minute source data."""
    source = _to_ist(frame)
    if source.empty:
        return source

    indexed = source.set_index("timestamp")
    bars = indexed.resample(
        f"{minutes}min",
        origin="start_day",
        offset="15min",
        label="left",
        closed="left",
    ).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        source_rows=("close", "count"),
    )
    bars = bars.dropna(subset=["open", "high", "low", "close"])
    bars = bars[bars["source_rows"] >= minutes].reset_index()
    return bars[bars["timestamp"].dt.time < session_end].reset_index(drop=True)


def _confirmation_window(
    one_minute: pd.DataFrame,
    candle_a_timestamp: pd.Timestamp,
    *,
    setup_interval_minutes: int,
    confirmation_window_minutes: int,
    session_end: time,
) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    start = candle_a_timestamp + pd.Timedelta(minutes=setup_interval_minutes)
    end = start + pd.Timedelta(minutes=confirmation_window_minutes)
    window = one_minute[
        (one_minute["timestamp"] >= start)
        & (one_minute["timestamp"] < end)
        & (one_minute["timestamp"].dt.time < session_end)
    ].reset_index(drop=True)
    return window, start, end


def _attempt_from_setup(
    one_minute: pd.DataFrame,
    candle_a: pd.Series,
    *,
    level: ReferenceLevel,
    direction: Direction,
    setup_interval_minutes: int,
    confirmation_window_minutes: int,
    session_end: time,
    latest_one_minute: pd.Timestamp,
) -> SignalAttempt:
    """Apply the existing 1-minute confirmation rule to one setup candle."""
    a_timestamp = pd.Timestamp(candle_a["timestamp"])
    a_close = float(candle_a["close"])
    confirmation_rows, _confirm_start, confirm_end = _confirmation_window(
        one_minute,
        a_timestamp,
        setup_interval_minutes=setup_interval_minutes,
        confirmation_window_minutes=confirmation_window_minutes,
        session_end=session_end,
    )

    confirm_row = None
    confirm_position = None
    for position, (_, row) in enumerate(confirmation_rows.iterrows(), start=1):
        close_value = float(row["close"])
        confirmed = (
            close_value > float(candle_a["high"])
            if direction is Direction.BULLISH
            else close_value < float(candle_a["low"])
        )
        if confirmed:
            confirm_row = row
            confirm_position = position
            break

    if confirm_row is not None:
        confirm_close = float(confirm_row["close"])
        return SignalAttempt(
            state=SignalState.ACTIVE,
            direction=direction,
            level_type=level.level_type,
            level_value=level.value,
            cross_timestamp=a_timestamp.to_pydatetime(),
            confirmation_timestamp=pd.Timestamp(
                confirm_row["timestamp"]
            ).to_pydatetime(),
            underlying_entry=confirm_close,
            cross_open=float(candle_a["open"]),
            cross_high=float(candle_a["high"]),
            cross_low=float(candle_a["low"]),
            cross_close=a_close,
            confirmation_open=float(confirm_row["open"]),
            confirmation_high=float(confirm_row["high"]),
            confirmation_low=float(confirm_row["low"]),
            confirmation_close=confirm_close,
            confirmation_delay_minutes=confirm_position,
        )

    expected_last_confirmation = confirm_end - pd.Timedelta(minutes=1)
    full_window_complete = latest_one_minute >= expected_last_confirmation
    return SignalAttempt(
        state=(
            SignalState.TIMEOUT
            if full_window_complete
            else SignalState.AWAITING_CONFIRMATION
        ),
        direction=direction,
        level_type=level.level_type,
        level_value=level.value,
        cross_timestamp=a_timestamp.to_pydatetime(),
        cross_open=float(candle_a["open"]),
        cross_high=float(candle_a["high"]),
        cross_low=float(candle_a["low"]),
        cross_close=a_close,
    )


def _initial_displacement_attempt(
    one_minute: pd.DataFrame,
    setup_bars: pd.DataFrame,
    level: ReferenceLevel,
    *,
    signal_interval_minutes: int,
    confirmation_window_minutes: int,
    session_end: time,
    latest_one_minute: pd.Timestamp,
) -> SignalAttempt | None:
    """Create at most one direct setup when price is already beyond a level.

    Same-session reference levels use their own completed source candle. Previous
    day (PDx_315) levels use the first completed current-session 5-minute candle.
    The existing later midpoint re-cross logic remains unchanged as a fallback.
    """
    candle_a: pd.Series | None = None
    setup_minutes = signal_interval_minutes

    if level.level_type in SAME_SESSION_INITIAL_LEVELS:
        source_bars = _completed_setup_bars(
            one_minute,
            level.interval_minutes,
            session_end=session_end,
        )
        source_ts = pd.Timestamp(level.source_timestamp)
        if source_ts.tzinfo is None:
            source_ts = source_ts.tz_localize(IST)
        else:
            source_ts = source_ts.tz_convert(IST)
        selected = source_bars[source_bars["timestamp"] == source_ts]
        if selected.empty:
            return None
        candle_a = selected.iloc[0]
        setup_minutes = level.interval_minutes
    elif _is_previous_day_level(level):
        if setup_bars.empty:
            return None
        candle_a = setup_bars.iloc[0]
    else:
        return None

    close_value = float(candle_a["close"])
    if close_value > level.value:
        direction = Direction.BULLISH
    elif close_value < level.value:
        direction = Direction.BEARISH
    else:
        return None

    return _attempt_from_setup(
        one_minute,
        candle_a,
        level=level,
        direction=direction,
        setup_interval_minutes=setup_minutes,
        confirmation_window_minutes=confirmation_window_minutes,
        session_end=session_end,
        latest_one_minute=latest_one_minute,
    )


def scan_level_signals(
    frame: pd.DataFrame,
    level: ReferenceLevel,
    *,
    signal_interval_minutes: int = 5,
    confirmation_window_minutes: int = 5,
    session_end: time = time(15, 30),
) -> tuple[SignalAttempt, ...]:
    """Evaluate initial displacement plus the established re-cross rule.

    Initial-displacement path:
      * FIRST_CANDLE / NEXT_RED_CANDLE / MID_SESSION_1245: once the source
        candle is complete, its close above/below its midpoint establishes one
        initial bullish/bearish setup.
      * PDx_315: the first completed current-session 5-minute candle may
        establish one initial setup when already above/below the PD midpoint.

    Every setup still requires the existing confirmation rule:
      * Bullish: first of the next five 1-minute CLOSES above setup HIGH.
      * Bearish: first of the next five 1-minute CLOSES below setup LOW.

    The original later 5-minute midpoint re-cross logic remains active, so a
    genuine later cross can create a fresh setup after the initial opportunity.
    """
    if not _legacy_enabled():
        return ()
    one_minute = _to_ist(frame)
    setup_bars = _completed_setup_bars(
        one_minute, signal_interval_minutes, session_end=session_end
    )
    if one_minute.empty or setup_bars.empty:
        return ()

    latest_one_minute = pd.Timestamp(one_minute["timestamp"].max())
    attempts: list[SignalAttempt] = []

    initial = _initial_displacement_attempt(
        one_minute,
        setup_bars,
        level,
        signal_interval_minutes=signal_interval_minutes,
        confirmation_window_minutes=confirmation_window_minutes,
        session_end=session_end,
        latest_one_minute=latest_one_minute,
    )
    if initial is not None:
        attempts.append(initial)

    # Existing midpoint re-cross path is preserved exactly as the fallback.
    if len(setup_bars) < 2:
        return tuple(attempts)

    available_from = pd.Timestamp(_available_from(level))
    if available_from.tzinfo is None:
        available_from = available_from.tz_localize(IST)
    else:
        available_from = available_from.tz_convert(IST)
    eligible = setup_bars.index[
        setup_bars["timestamp"] >= available_from
    ].tolist()
    if not eligible:
        return tuple(attempts)

    index = max(1, eligible[0])
    while index < len(setup_bars):
        previous = setup_bars.iloc[index - 1]
        candle_a = setup_bars.iloc[index]

        previous_close = float(previous["close"])
        a_close = float(candle_a["close"])
        direction: Direction | None = None

        if _is_bullish_cross(previous_close, a_close, level.value):
            direction = Direction.BULLISH
        elif _is_bearish_cross(previous_close, a_close, level.value):
            direction = Direction.BEARISH

        if direction is None:
            index += 1
            continue

        attempt = _attempt_from_setup(
            one_minute,
            candle_a,
            level=level,
            direction=direction,
            setup_interval_minutes=signal_interval_minutes,
            confirmation_window_minutes=confirmation_window_minutes,
            session_end=session_end,
            latest_one_minute=latest_one_minute,
        )
        attempts.append(attempt)

        if attempt.state is SignalState.AWAITING_CONFIRMATION:
            break

        # The next 5-minute bucket was consumed as the confirmation window.
        index += 2

    return tuple(attempts)


def scan_reference_levels(
    frame: pd.DataFrame,
    levels: Iterable[ReferenceLevel],
    *,
    signal_interval_minutes: int = 5,
    confirmation_window_minutes: int = 5,
) -> SignalScanResult:
    attempts: list[SignalAttempt] = []
    for level in levels:
        attempts.extend(
            scan_level_signals(
                frame,
                level,
                signal_interval_minutes=signal_interval_minutes,
                confirmation_window_minutes=confirmation_window_minutes,
            )
        )
    attempts.sort(
        key=lambda item: (
            item.cross_timestamp or datetime.max,
            item.level_type,
        )
    )
    return SignalScanResult(tuple(attempts))
