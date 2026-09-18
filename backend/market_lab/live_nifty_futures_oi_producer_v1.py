from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MODEL = "LIVE_NIFTY_FUTURES_OI_PRODUCER_V1"

FuturesOIState = Literal[
    "LONG_BUILDUP",
    "SHORT_BUILDUP",
    "SHORT_COVERING",
    "LONG_UNWINDING",
    "FLAT_OR_UNCLASSIFIED",
]


@dataclass(frozen=True)
class CompletedFuturesCandle:
    instrument_key: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    oi: float


@dataclass(frozen=True)
class FuturesOIObservation:
    model: str
    instrument_key: str
    timestamp: datetime
    previous_timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    oi: float
    previous_close: float
    previous_oi: float
    price_change: float
    oi_change: float
    state: FuturesOIState
    health_state: str
    health_allowed: bool
    health_reason: str | None


def _validate_ohlc(c: CompletedFuturesCandle) -> None:
    if min(c.open, c.high, c.low, c.close) <= 0:
        raise ValueError("Futures OHLC must be positive")
    if c.low > min(c.open, c.close, c.high):
        raise ValueError("Invalid futures OHLC low")
    if c.high < max(c.open, c.close, c.low):
        raise ValueError("Invalid futures OHLC high")
    if c.oi < 0:
        raise ValueError("Futures OI cannot be negative")
    if c.timestamp.tzinfo is None:
        raise ValueError("Futures timestamp must be timezone-aware")


def classify_futures_oi(price_change: float, oi_change: float) -> FuturesOIState:
    if price_change > 0 and oi_change > 0:
        return "LONG_BUILDUP"
    if price_change < 0 and oi_change > 0:
        return "SHORT_BUILDUP"
    if price_change > 0 and oi_change < 0:
        return "SHORT_COVERING"
    if price_change < 0 and oi_change < 0:
        return "LONG_UNWINDING"
    return "FLAT_OR_UNCLASSIFIED"


class LiveNiftyFuturesOIProducerV1:
    """
    Exact completed-candle futures OI producer.

    V1 intentionally has no nearest-time lookup and no strategy logic.
    The caller must provide candles in strictly increasing chronological order.
    """

    def __init__(self, expected_minutes: int = 5):
        if expected_minutes != 5:
            raise ValueError("V1 is frozen to completed 5-minute candles")
        self.expected_minutes = expected_minutes
        self.previous: CompletedFuturesCandle | None = None

    def process(self, candle: CompletedFuturesCandle) -> FuturesOIObservation | None:
        _validate_ohlc(candle)

        prev = self.previous
        self.previous = candle

        if prev is None:
            return None

        if candle.instrument_key != prev.instrument_key:
            raise ValueError("Futures instrument changed inside V1 stream")

        if candle.timestamp <= prev.timestamp:
            raise ValueError("Out-of-order or duplicate futures candle")

        delta_seconds = (candle.timestamp - prev.timestamp).total_seconds()
        expected_seconds = self.expected_minutes * 60
        if delta_seconds != expected_seconds:
            return FuturesOIObservation(
                model=MODEL,
                instrument_key=candle.instrument_key,
                timestamp=candle.timestamp,
                previous_timestamp=prev.timestamp,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                oi=candle.oi,
                previous_close=prev.close,
                previous_oi=prev.oi,
                price_change=candle.close - prev.close,
                oi_change=candle.oi - prev.oi,
                state="FLAT_OR_UNCLASSIFIED",
                health_state="MISSING",
                health_allowed=False,
                health_reason="FUTURES_5M_GAP",
            )

        price_change = candle.close - prev.close
        oi_change = candle.oi - prev.oi
        state = classify_futures_oi(price_change, oi_change)

        allowed = state != "FLAT_OR_UNCLASSIFIED"
        return FuturesOIObservation(
            model=MODEL,
            instrument_key=candle.instrument_key,
            timestamp=candle.timestamp,
            previous_timestamp=prev.timestamp,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            oi=candle.oi,
            previous_close=prev.close,
            previous_oi=prev.oi,
            price_change=price_change,
            oi_change=oi_change,
            state=state,
            health_state="HEALTHY" if allowed else "DEGRADED",
            health_allowed=allowed,
            health_reason=None if allowed else "FUTURES_ZERO_DELTA",
        )
