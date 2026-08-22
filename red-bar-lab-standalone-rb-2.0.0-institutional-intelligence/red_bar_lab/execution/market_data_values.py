from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any


class MarketDataQuality(str, Enum):
    """Truthful availability state for one numeric market-data field."""

    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    INVALID = "INVALID"


@dataclass(frozen=True)
class MarketDataValue:
    """A numeric value that preserves whether the source was actually present.

    ``value`` is intentionally ``None`` for missing or invalid source data.  A
    genuine numeric zero remains available and must not be conflated with an
    unavailable observation.
    """

    value: float | None
    quality: MarketDataQuality
    raw_value: Any = None

    @property
    def available(self) -> bool:
        return self.quality is MarketDataQuality.AVAILABLE

    def score_input(self, *, unavailable: float = 0.0) -> float:
        """Return a compatibility scoring value without mutating truthfulness.

        Existing score formulas may continue to use a conservative zero for an
        unavailable input, while persistence and diagnostics retain ``None`` and
        the explicit quality state.
        """

        return float(self.value) if self.value is not None else float(unavailable)


def normalize_market_number(value: Any) -> MarketDataValue:
    """Normalize a numeric observation without silently inventing zero."""

    if value is None:
        return MarketDataValue(None, MarketDataQuality.MISSING, value)

    try:
        number = float(value)
    except (TypeError, ValueError):
        return MarketDataValue(None, MarketDataQuality.INVALID, value)

    if math.isnan(number) or math.isinf(number):
        return MarketDataValue(None, MarketDataQuality.INVALID, value)

    return MarketDataValue(number, MarketDataQuality.AVAILABLE, value)


__all__ = [
    "MarketDataQuality",
    "MarketDataValue",
    "normalize_market_number",
]
