"""Provider-independent historical feature primitives."""

from datetime import date, datetime
from decimal import Decimal, ROUND_FLOOR
from typing import Iterable, Protocol

from .domain import (
    HistoricalATM,
    HistoricalCandle,
    HistoricalOptionCandleSeries,
    HistoricalOptionContract,
)


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

class HistoricalCandleLoader(Protocol):
    def historical_candles(
        self, instrument_key: str, session_date: date
    ) -> list[HistoricalCandle]: ...


def resolve_historical_option_contracts(
    contracts: Iterable[HistoricalOptionContract],
    underlying: str,
    expiry: date,
    atm: float,
    wings: int = 5,
    strike_interval: int = 50,
) -> list[HistoricalOptionContract]:
    """Select an exact ATM basket; absent CE/PE contracts remain absent."""
    if strike_interval <= 0:
        raise ValueError("strike_interval must be positive")
    if type(wings) is not int or wings < 0:
        raise ValueError("wings must be a non-negative integer")
    interval = Decimal(str(strike_interval))
    center = Decimal(str(atm))
    if center <= 0 or center % interval:
        raise ValueError("atm must be a positive listed strike")
    requested = {
        float(center + interval * offset)
        for offset in range(-wings, wings + 1)
    }
    if min(requested) <= 0:
        raise ValueError("requested strike range must be positive")
    selected = [
        contract for contract in contracts
        if contract.underlying == underlying
        and contract.expiry == expiry
        and contract.strike in requested
    ]
    identities = [(contract.strike, contract.side) for contract in selected]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate historical option contract")
    return sorted(
        selected,
        key=lambda contract: (contract.strike, 0 if contract.side == "CE" else 1),
    )


def load_historical_option_candles(
    loader: HistoricalCandleLoader,
    contracts: Iterable[HistoricalOptionContract],
    session_date: date,
) -> list[HistoricalOptionCandleSeries]:
    """Load each selected contract exactly once; empty series remain explicit."""
    ordered = sorted(
        contracts,
        key=lambda contract: (contract.strike, 0 if contract.side == "CE" else 1),
    )
    identities = [(contract.strike, contract.side) for contract in ordered]
    keys = [contract.instrument_key for contract in ordered]
    if len(identities) != len(set(identities)) or len(keys) != len(set(keys)):
        raise ValueError("Historical option contracts must be unique")
    return [
        HistoricalOptionCandleSeries(
            contract=contract,
            session_date=session_date,
            candles=loader.historical_candles(contract.instrument_key, session_date),
        )
        for contract in ordered
    ]


def index_historical_option_candles(
    series: Iterable[HistoricalOptionCandleSeries],
) -> dict[tuple[datetime, float, str], HistoricalCandle]:
    """Build the reusable timestamp/strike/side lookup for reconstruction."""
    result = {}
    for item in series:
        for candle in item.candles:
            identity = (candle.timestamp, item.contract.strike, item.contract.side)
            if identity in result:
                raise ValueError("Duplicate historical option candle identity")
            result[identity] = candle
    return result