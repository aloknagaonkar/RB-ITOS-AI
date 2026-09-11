"""Provider-independent historical feature primitives."""

from decimal import Decimal, ROUND_FLOOR
from typing import Iterable

from .domain import HistoricalATM, HistoricalCandle


def resolve_historical_atm(
    candles: Iterable[HistoricalCandle], strike_interval: int = 50
) -> list[HistoricalATM]:
    """Resolve nearest listed strike using deterministic ROUND HALF UP."""
    if strike_interval <= 0:
        raise ValueError("strike_interval must be positive")
    interval = Decimal(str(strike_interval))
    results = []
    for candle in sorted(candles, key=lambda value: value.timestamp):
        spot = Decimal(str(candle.close))
        lower = (spot / interval).to_integral_value(rounding=ROUND_FLOOR) * interval
        atm = lower + interval if spot - lower >= interval / 2 else lower
        results.append(HistoricalATM(timestamp=candle.timestamp, spot=float(spot), atm=float(atm)))
    return results