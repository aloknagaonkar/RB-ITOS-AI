from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SignalState(str, Enum):
    WAITING_FOR_LEVEL = "WAITING_FOR_LEVEL"
    CROSS_DETECTED = "CROSS_DETECTED"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    ACTIVE = "ACTIVE"
    CONFIRMATION_FAILED = "CONFIRMATION_FAILED"  # retained for old DB compatibility
    TIMEOUT = "TIMEOUT"
    CLOSED = "CLOSED"


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


@dataclass(frozen=True)
class ReferenceLevel:
    level_type: str
    value: float
    source_timestamp: datetime
    source_high: float
    source_low: float
    interval_minutes: int


@dataclass(frozen=True)
class SignalAttempt:
    state: SignalState
    direction: Direction | None
    level_type: str
    level_value: float
    cross_timestamp: datetime | None = None
    confirmation_timestamp: datetime | None = None
    underlying_entry: float | None = None

    # Candle A: completed 5-minute setup candle.
    cross_open: float | None = None
    cross_high: float | None = None
    cross_low: float | None = None
    cross_close: float | None = None

    # Confirmation candle: completed 1-minute candle.
    confirmation_open: float | None = None
    confirmation_high: float | None = None
    confirmation_low: float | None = None
    confirmation_close: float | None = None

    # 1 means the first 1-minute candle after Candle A, 5 means the fifth.
    confirmation_delay_minutes: int | None = None
