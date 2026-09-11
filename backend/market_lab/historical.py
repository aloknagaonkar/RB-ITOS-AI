"""Provider-independent historical feature primitives."""

from datetime import date, datetime
from decimal import Decimal, ROUND_FLOOR
from typing import Iterable, Protocol

from .domain import (
    HistoricalATM,
    HistoricalCandle,
    HistoricalOptionCandleSeries,
    HistoricalOptionContract,
    HistoricalOptionSideObservation,
    HistoricalReconstructedSnapshot,
    HistoricalStrikeObservation,
)


def _nearest_strike(spot: float, strike_interval: int) -> float:
    if strike_interval <= 0:
        raise ValueError("strike_interval must be positive")
    interval = Decimal(str(strike_interval))
    value = Decimal(str(spot))
    lower = (value / interval).to_integral_value(rounding=ROUND_FLOOR) * interval
    return float(lower + interval if value - lower >= interval / 2 else lower)


def resolve_historical_atm(
    candles: Iterable[HistoricalCandle], strike_interval: int = 50
) -> list[HistoricalATM]:
    """Resolve nearest listed strike using deterministic ROUND HALF UP."""
    return [
        HistoricalATM(
            timestamp=candle.timestamp,
            spot=candle.close,
            atm=_nearest_strike(candle.close, strike_interval),
        )
        for candle in sorted(candles, key=lambda value: value.timestamp)
    ]

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

def reconstruct_historical_snapshots(
    underlying_candles: Iterable[HistoricalCandle],
    contracts: Iterable[HistoricalOptionContract],
    option_series: Iterable[HistoricalOptionCandleSeries],
    underlying: str,
    expiry: date,
    session_date: date,
    wings: int = 5,
    strike_interval: int = 50,
) -> list[HistoricalReconstructedSnapshot]:
    """Reconstruct exact-timestamp historical baskets without filling missing data."""
    if type(wings) is not int or wings < 0:
        raise ValueError("wings must be a non-negative integer")
    if strike_interval <= 0:
        raise ValueError("strike_interval must be positive")

    timeline = sorted(underlying_candles, key=lambda candle: candle.timestamp)
    timestamps = [candle.timestamp for candle in timeline]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError("Historical underlying candle timestamps are duplicated")
    if any(
        candle.instrument_key != underlying or candle.session_date != session_date
        for candle in timeline
    ):
        raise ValueError("Historical underlying candle identity or session mismatch")

    contract_index = {}
    for contract in contracts:
        if contract.underlying != underlying or contract.expiry != expiry:
            continue
        identity = (contract.strike, contract.side)
        if identity in contract_index:
            raise ValueError("Duplicate historical option contract")
        contract_index[identity] = contract

    relevant_series = []
    for item in option_series:
        if item.contract.underlying != underlying or item.contract.expiry != expiry:
            continue
        if item.session_date != session_date:
            raise ValueError("Historical option series session mismatch")
        relevant_series.append(item)
    candle_index = index_historical_option_candles(relevant_series)

    def side_observation(timestamp, strike, side):
        contract = contract_index.get((strike, side))
        if contract is None:
            return HistoricalOptionSideObservation(
                side=side, status="CONTRACT_UNAVAILABLE"
            )
        candle = candle_index.get((timestamp, strike, side))
        if candle is None:
            return HistoricalOptionSideObservation(
                side=side,
                instrument_key=contract.instrument_key,
                status="CANDLE_UNAVAILABLE",
            )
        if candle.instrument_key != contract.instrument_key:
            raise ValueError("Historical option candle contract identity mismatch")
        status = "AVAILABLE" if candle.open_interest is not None else "OI_UNAVAILABLE"
        return HistoricalOptionSideObservation(
            side=side,
            instrument_key=contract.instrument_key,
            close=candle.close,
            open_interest=candle.open_interest,
            volume=candle.volume,
            status=status,
        )

    snapshots = []
    interval = Decimal(str(strike_interval))
    for candle in timeline:
        atm = _nearest_strike(candle.close, strike_interval)
        center = Decimal(str(atm))
        required_strikes = [
            float(center + interval * offset)
            for offset in range(-wings, wings + 1)
        ]
        if min(required_strikes) <= 0:
            raise ValueError("requested strike range must be positive")
        snapshots.append(HistoricalReconstructedSnapshot(
            source_provider=candle.provider,
            underlying=underlying,
            expiry=expiry,
            session_date=session_date,
            timestamp=candle.timestamp,
            spot=candle.close,
            moving_atm=atm,
            wings=wings,
            strike_interval=strike_interval,
            strikes=[
                HistoricalStrikeObservation(
                    strike=strike,
                    ce=side_observation(candle.timestamp, strike, "CE"),
                    pe=side_observation(candle.timestamp, strike, "PE"),
                )
                for strike in required_strikes
            ],
        ))
    return snapshots