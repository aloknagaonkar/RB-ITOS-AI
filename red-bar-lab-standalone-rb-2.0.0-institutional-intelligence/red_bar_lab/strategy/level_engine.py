from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Iterable

import pandas as pd

from red_bar_lab.strategy.models import ReferenceLevel

IST = "Asia/Kolkata"


@dataclass(frozen=True)
class DailyReferenceLevels:
    trading_date: date
    previous_day_levels: tuple[ReferenceLevel, ...]
    first_candle: ReferenceLevel | None
    next_red_candle: ReferenceLevel | None
    mid_session_candle: ReferenceLevel | None


def _to_ist(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=("timestamp", "open", "high", "low", "close", "volume"))
    result = frame.copy()
    ts = pd.to_datetime(result["timestamp"], errors="coerce", utc=True)
    result = result.loc[ts.notna()].copy()
    result["timestamp"] = ts.loc[ts.notna()].dt.tz_convert(IST)
    return result.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)


def aggregate_candles(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    source = _to_ist(frame)
    if source.empty:
        return source
    indexed = source.set_index("timestamp")
    result = indexed.resample(
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
    return result.dropna(subset=["open", "high", "low", "close"]).reset_index()


def _level(level_type: str, row: pd.Series, interval_minutes: int) -> ReferenceLevel:
    return ReferenceLevel(
        level_type=level_type,
        value=(float(row["high"]) + float(row["low"])) / 2.0,
        source_timestamp=pd.Timestamp(row["timestamp"]).to_pydatetime(),
        source_high=float(row["high"]),
        source_low=float(row["low"]),
        interval_minutes=interval_minutes,
    )


def build_previous_315_level(frame: pd.DataFrame, rank: int) -> ReferenceLevel | None:
    bars = aggregate_candles(frame, 15)
    selected = bars[(bars["timestamp"].dt.time == time(15, 15)) & (bars["source_rows"] >= 15)]
    if selected.empty:
        return None
    return _level(f"PD{rank}_315", selected.iloc[-1], 15)


def build_first_candle_level(frame: pd.DataFrame) -> ReferenceLevel | None:
    bars = aggregate_candles(frame, 5)
    selected = bars[(bars["timestamp"].dt.time == time(9, 15)) & (bars["source_rows"] >= 5)]
    if selected.empty:
        return None
    return _level("FIRST_CANDLE", selected.iloc[0], 5)


def build_next_red_candle_level(frame: pd.DataFrame) -> ReferenceLevel | None:
    bars = aggregate_candles(frame, 5)
    selected = bars[
        (bars["timestamp"].dt.time >= time(9, 20))
        & (bars["source_rows"] >= 5)
        & (bars["close"] < bars["open"])
    ]
    if selected.empty:
        return None
    return _level("NEXT_RED_CANDLE", selected.iloc[0], 5)


def build_mid_session_level(frame: pd.DataFrame) -> ReferenceLevel | None:
    """Return the completed 12:45-13:15 reference candle only.

    A partial bar is intentionally unavailable. Because this function is
    stateless, every subsequent scan retries automatically until all 30 one-
    minute rows are present; delayed provider data cannot permanently drop it.
    """
    bars = aggregate_candles(frame, 30)
    selected = bars[
        (bars["timestamp"].dt.time == time(12, 45))
        & (bars["source_rows"] >= 30)
    ]
    if selected.empty:
        return None
    return _level("MID_SESSION_1245", selected.iloc[0], 30)


def build_daily_levels(
    trading_date: date,
    current_frame: pd.DataFrame,
    previous_frames: Iterable[tuple[date, pd.DataFrame]],
    previous_days: int = 10,
) -> DailyReferenceLevels:
    completed = sorted(
        ((day, frame) for day, frame in previous_frames if day < trading_date and frame is not None and not frame.empty),
        key=lambda item: item[0],
        reverse=True,
    )[:previous_days]
    previous = []
    for rank, (_day, frame) in enumerate(completed, start=1):
        level = build_previous_315_level(frame, rank)
        if level is not None:
            previous.append(level)
    return DailyReferenceLevels(
        trading_date=trading_date,
        previous_day_levels=tuple(previous),
        first_candle=build_first_candle_level(current_frame),
        next_red_candle=build_next_red_candle_level(current_frame),
        mid_session_candle=build_mid_session_level(current_frame),
    )
