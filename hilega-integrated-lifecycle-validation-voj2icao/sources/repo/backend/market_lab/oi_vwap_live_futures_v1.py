
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Iterable

from .domain import IST
from .oi_vwap_live_feature_engine_v1 import FuturesVWAPFeature

SESSION_START = time(9, 15)


@dataclass(frozen=True)
class FuturesCandle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


def completed_futures_vwap(
    candles: Iterable[FuturesCandle],
    *,
    available_at: datetime,
) -> FuturesVWAPFeature:
    """
    Build prospective cumulative session VWAP using typical-price proxy:
      (H + L + C) / 3 * volume

    Only candles whose 5m interval has fully completed by available_at are eligible.
    Candle timestamps are assumed to be interval START timestamps.
    """
    local_available = available_at.astimezone(IST)
    eligible = []
    for candle in candles:
        ts = candle.timestamp.astimezone(IST)
        if ts.date() != local_available.date():
            continue
        if ts.time() < SESSION_START:
            continue
        if ts + __import__("datetime").timedelta(minutes=5) <= local_available:
            eligible.append(candle)

    if not eligible:
        raise ValueError("no completed futures 5m candle available")

    eligible.sort(key=lambda c: c.timestamp)
    cumulative_pv = 0.0
    cumulative_volume = 0
    for c in eligible:
        if c.volume < 0:
            raise ValueError("futures volume must be non-negative")
        typical = (c.high + c.low + c.close) / 3.0
        cumulative_pv += typical * c.volume
        cumulative_volume += c.volume

    if cumulative_volume <= 0:
        raise ValueError("cumulative futures volume unavailable")

    last = eligible[-1]
    vwap = cumulative_pv / cumulative_volume
    distance = last.close - vwap
    side = "ABOVE" if distance > 0 else "BELOW" if distance < 0 else "AT"

    return FuturesVWAPFeature(
        candle_time=last.timestamp.astimezone(IST).isoformat(),
        available_at=local_available.isoformat(),
        open=last.open,
        high=last.high,
        low=last.low,
        close=last.close,
        volume=last.volume,
        cumulative_vwap=vwap,
        distance=distance,
        side=side,
    )
