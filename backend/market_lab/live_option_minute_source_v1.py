from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

MODEL = "LIVE_OPTION_MINUTE_SOURCE_V1"


@dataclass(frozen=True)
class CompletedOptionMinute:
    instrument_key: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True)
class OptionMinuteHealth:
    state: str
    allowed: bool
    reason: str | None


def validate_option_minute(
    bar: CompletedOptionMinute,
    *,
    expected_instrument_key: str,
    previous_timestamp: datetime | None,
) -> OptionMinuteHealth:
    if bar.timestamp.tzinfo is None:
        return OptionMinuteHealth("UNHEALTHY", False, "OPTION_TIMESTAMP_NAIVE")
    if bar.instrument_key != expected_instrument_key:
        return OptionMinuteHealth("UNHEALTHY", False, "OPTION_INSTRUMENT_MISMATCH")
    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
        return OptionMinuteHealth("UNHEALTHY", False, "OPTION_NONPOSITIVE_OHLC")
    if bar.low > min(bar.open, bar.close, bar.high):
        return OptionMinuteHealth("UNHEALTHY", False, "OPTION_INVALID_LOW")
    if bar.high < max(bar.open, bar.close, bar.low):
        return OptionMinuteHealth("UNHEALTHY", False, "OPTION_INVALID_HIGH")
    if previous_timestamp is not None:
        if bar.timestamp <= previous_timestamp:
            return OptionMinuteHealth("OUT_OF_ORDER", False, "OPTION_OUT_OF_ORDER")
        if (bar.timestamp - previous_timestamp).total_seconds() != 60:
            return OptionMinuteHealth("MISSING", False, "OPTION_1M_GAP")
    return OptionMinuteHealth("HEALTHY", True, None)


class LiveOptionMinuteSourceV1:
    """
    Exact selected-option minute stream validator.

    This class does not fetch candles itself. It validates the exact 1-minute bars
    supplied by the provider adapter and enforces strict continuity.
    """

    def __init__(self, instrument_key: str):
        if not instrument_key:
            raise ValueError("instrument_key required")
        self.instrument_key = instrument_key
        self.previous_timestamp: datetime | None = None

    def process(self, bar: CompletedOptionMinute) -> OptionMinuteHealth:
        result = validate_option_minute(
            bar,
            expected_instrument_key=self.instrument_key,
            previous_timestamp=self.previous_timestamp,
        )
        if result.allowed:
            self.previous_timestamp = bar.timestamp
        return result
