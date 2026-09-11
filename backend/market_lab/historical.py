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
    HistoricalPCRObservation,
    HistoricalPCRPanelResult,
    HistoricalPCRStrikeResult,
    HistoricalReconstructedSnapshot,
    HistoricalStrikeObservation,
    calculate_oi_change,
    calculate_pcr_value,
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

class HistoricalOptionCandleLoader(Protocol):
    def historical_option_candles(
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
    loader: HistoricalOptionCandleLoader,
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
            candles=loader.historical_option_candles(contract.instrument_key, session_date),
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

def reconstruct_historical_pcr(
    snapshots: Iterable[HistoricalReconstructedSnapshot],
    timeline_interval_seconds: int = 60,
) -> list[HistoricalPCRObservation]:
    """Calculate historical PCR from exact reconstructed observations only."""
    if timeline_interval_seconds <= 0:
        raise ValueError("timeline_interval_seconds must be positive")
    timeline = sorted(snapshots, key=lambda snapshot: snapshot.timestamp)
    timestamps = [snapshot.timestamp for snapshot in timeline]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError("Historical PCR snapshot timestamps are duplicated")

    observations = []
    previous_snapshot = None
    for snapshot in timeline:
        previous_rows = {}
        previous_is_consecutive = (
            previous_snapshot is not None
            and (snapshot.timestamp - previous_snapshot.timestamp).total_seconds()
            == timeline_interval_seconds
        )
        if previous_is_consecutive:
            previous_rows = {row.strike: row for row in previous_snapshot.strikes}

        strike_results = []
        for row in snapshot.strikes:
            previous_row = previous_rows.get(row.strike)

            def previous_oi(side_name):
                if previous_row is None:
                    return None
                current_side = getattr(row, side_name)
                prior_side = getattr(previous_row, side_name)
                if (
                    current_side.instrument_key is None
                    or current_side.instrument_key != prior_side.instrument_key
                ):
                    return None
                return prior_side.open_interest

            call_oi = row.ce.open_interest
            put_oi = row.pe.open_interest
            previous_call_oi = previous_oi("ce")
            previous_put_oi = previous_oi("pe")
            call_change, call_change_pct = calculate_oi_change(call_oi, previous_call_oi)
            put_change, put_change_pct = calculate_oi_change(put_oi, previous_put_oi)
            issues = []
            if row.ce.status != "AVAILABLE":
                issues.append(f"call_{row.ce.status.lower()}")
            if row.pe.status != "AVAILABLE":
                issues.append(f"put_{row.pe.status.lower()}")
            if call_oi == 0:
                issues.append("zero_call_oi")
            pcr = calculate_pcr_value(put_oi, call_oi)
            strike_results.append(HistoricalPCRStrikeResult(
                strike=row.strike,
                call_oi=call_oi,
                put_oi=put_oi,
                previous_call_oi=previous_call_oi,
                previous_put_oi=previous_put_oi,
                call_oi_change=call_change,
                put_oi_change=put_change,
                call_oi_change_pct=call_change_pct,
                put_oi_change_pct=put_change_pct,
                pcr=pcr,
                status="AVAILABLE" if pcr is not None else "UNAVAILABLE",
                issues=issues,
            ))

        def panel(mode):
            current_complete = all(
                result.call_oi is not None and result.put_oi is not None
                for result in strike_results
            )
            previous_complete = all(
                result.previous_call_oi is not None
                and result.previous_put_oi is not None
                for result in strike_results
            )
            call_oi = sum(result.call_oi for result in strike_results) if current_complete else None
            put_oi = sum(result.put_oi for result in strike_results) if current_complete else None
            previous_call_oi = (
                sum(result.previous_call_oi for result in strike_results)
                if previous_complete else None
            )
            previous_put_oi = (
                sum(result.previous_put_oi for result in strike_results)
                if previous_complete else None
            )
            call_change, call_change_pct = calculate_oi_change(call_oi, previous_call_oi)
            put_change, put_change_pct = calculate_oi_change(put_oi, previous_put_oi)
            issues = []
            if not current_complete:
                issues.append("missing_or_invalid_oi")
            if call_oi == 0:
                issues.append("zero_call_oi")
            pcr = calculate_pcr_value(put_oi, call_oi)
            return HistoricalPCRPanelResult(
                mode=mode,
                atm=snapshot.moving_atm if mode == "moving" else None,
                strikes=[result.strike for result in strike_results],
                expected_contracts=len(strike_results) * 2,
                received_oi_contracts=sum(
                    value is not None
                    for result in strike_results
                    for value in (result.call_oi, result.put_oi)
                ),
                call_oi=call_oi,
                put_oi=put_oi,
                previous_call_oi=previous_call_oi,
                previous_put_oi=previous_put_oi,
                call_oi_change=call_change,
                put_oi_change=put_change,
                call_oi_change_pct=call_change_pct,
                put_oi_change_pct=put_change_pct,
                pcr=pcr,
                status="AVAILABLE" if pcr is not None else "UNAVAILABLE",
                issues=issues,
            )

        observations.append(HistoricalPCRObservation(
            timestamp=snapshot.timestamp,
            session_date=snapshot.session_date,
            underlying=snapshot.underlying,
            expiry=snapshot.expiry,
            spot=snapshot.spot,
            moving_atm=snapshot.moving_atm,
            strike_results=strike_results,
            moving_panel=panel("moving"),
            full_reconstructed_panel=panel("full_reconstructed"),
            fixed_panel=HistoricalPCRPanelResult(
                mode="fixed",
                status="UNAVAILABLE",
                issues=["fixed_basket_not_reconstructed"],
            ),
        ))
        previous_snapshot = snapshot
    return observations