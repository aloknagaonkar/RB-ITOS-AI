from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterable

import pandas as pd

from red_bar_lab.strategy.models import (
    Direction,
    ReferenceLevel,
    SignalAttempt,
    SignalState,
)


IST = "Asia/Kolkata"


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


def _completed_setup_bars(
    frame: pd.DataFrame,
    minutes: int = 5,
    session_end: time = time(15, 30),
) -> pd.DataFrame:
    """Build only complete N-minute setup candles from one-minute source data."""
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


def scan_level_signals(
    frame: pd.DataFrame,
    level: ReferenceLevel,
    *,
    signal_interval_minutes: int = 5,
    confirmation_window_minutes: int = 5,
    session_end: time = time(15, 30),
) -> tuple[SignalAttempt, ...]:
    """Evaluate the mixed-timeframe Red Bar confirmation rule.

    Candle A is a completed 5-minute candle. It must cross and CLOSE beyond the
    reference midpoint.

    After Candle A closes, inspect up to the next five completed 1-minute
    candles:
      * Bullish: first 1-minute CLOSE above Candle A HIGH -> ACTIVE.
      * Bearish: first 1-minute CLOSE below Candle A LOW -> ACTIVE.

    ACTIVE is assigned immediately at that confirming 1-minute close and the
    entry reference is that close.

    If all five one-minute candles complete without confirmation, the attempt is
    TIMEOUT. During a live/incomplete window the state remains
    AWAITING_CONFIRMATION.
    """
    one_minute = _to_ist(frame)
    setup_bars = _completed_setup_bars(
        one_minute, signal_interval_minutes, session_end=session_end
    )
    if one_minute.empty or len(setup_bars) < 2:
        return ()

    available_from = pd.Timestamp(_available_from(level))
    eligible = setup_bars.index[
        setup_bars["timestamp"] >= available_from
    ].tolist()
    if not eligible:
        return ()

    latest_one_minute = pd.Timestamp(one_minute["timestamp"].max())
    attempts: list[SignalAttempt] = []
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

        a_timestamp = pd.Timestamp(candle_a["timestamp"])
        cross_timestamp = a_timestamp.to_pydatetime()
        confirmation_rows, confirm_start, confirm_end = _confirmation_window(
            one_minute,
            a_timestamp,
            setup_interval_minutes=signal_interval_minutes,
            confirmation_window_minutes=confirmation_window_minutes,
            session_end=session_end,
        )

        confirm_row = None
        confirm_position = None
        for position, (_, row) in enumerate(
            confirmation_rows.iterrows(), start=1
        ):
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
            attempts.append(
                SignalAttempt(
                    state=SignalState.ACTIVE,
                    direction=direction,
                    level_type=level.level_type,
                    level_value=level.value,
                    cross_timestamp=cross_timestamp,
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
            )
            # The next 5-minute bucket was consumed as the confirmation window.
            index += 2
            continue

        # The full five-minute confirmation window is complete only once the
        # final 1-minute candle (start + 4 minutes) is present.
        expected_last_confirmation = confirm_end - pd.Timedelta(minutes=1)
        full_window_complete = latest_one_minute >= expected_last_confirmation

        attempts.append(
            SignalAttempt(
                state=(
                    SignalState.TIMEOUT
                    if full_window_complete
                    else SignalState.AWAITING_CONFIRMATION
                ),
                direction=direction,
                level_type=level.level_type,
                level_value=level.value,
                cross_timestamp=cross_timestamp,
                cross_open=float(candle_a["open"]),
                cross_high=float(candle_a["high"]),
                cross_low=float(candle_a["low"]),
                cross_close=a_close,
            )
        )

        if not full_window_complete:
            break

        # Skip the 5-minute bucket used for confirmation and wait for a fresh
        # setup crossing after the timeout.
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
