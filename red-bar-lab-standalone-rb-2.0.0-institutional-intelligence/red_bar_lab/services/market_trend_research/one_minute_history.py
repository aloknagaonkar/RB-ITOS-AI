from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.intelligence.market_context import wilder_rsi

from .five_minute_history import (
    OneMinutePcrObservation,
    build_one_minute_pcr_observation,
    completed_one_minute_close,
)


IST = ZoneInfo("Asia/Kolkata")


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if isfinite(parsed) else None


def completed_one_minute_rsi(
    candles: object,
    *,
    candle_close: datetime,
    period: int = 14,
) -> float | None:
    """Calculate RSI using only one-minute candles completed by the boundary."""
    if not isinstance(candles, pd.DataFrame) or candles.empty:
        return None
    if "timestamp" not in candles.columns or "close" not in candles.columns:
        return None
    frame = candles.loc[:, ["timestamp", "close"]].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna().sort_values("timestamp")
    if frame.empty:
        return None
    boundary = pd.Timestamp(candle_close)
    timestamps = frame["timestamp"]
    if timestamps.dt.tz is None:
        boundary = boundary.tz_localize(None)
    else:
        boundary = boundary.tz_convert(timestamps.dt.tz)
    completed = frame.loc[timestamps + pd.Timedelta(minutes=1) <= boundary]
    if len(completed) <= period:
        return None
    series = wilder_rsi(completed["close"], period=period).dropna()
    return None if series.empty else round(float(series.iloc[-1]), 2)


def aligned_one_minute_futures_vwap(
    snapshots: list[Mapping[str, object]],
    *,
    candle_close: datetime,
    maximum_lag_seconds: float = 60.0,
) -> float | None:
    """Select a futures VWAP timestamped at or immediately before the 1m boundary."""
    close_utc = candle_close.astimezone(timezone.utc)
    for row in snapshots:
        raw_timestamp = row.get("futures_vwap_timestamp")
        value = _number(row.get("futures_vwap") or row.get("vwap"))
        if not isinstance(raw_timestamp, str) or value is None:
            continue
        try:
            timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            continue
        lag = (close_utc - timestamp.astimezone(timezone.utc)).total_seconds()
        if 0 <= lag <= maximum_lag_seconds:
            return value
    return None


__all__ = [
    "OneMinutePcrObservation",
    "build_one_minute_pcr_observation",
    "completed_one_minute_close",
    "completed_one_minute_rsi",
    "aligned_one_minute_futures_vwap",
]
