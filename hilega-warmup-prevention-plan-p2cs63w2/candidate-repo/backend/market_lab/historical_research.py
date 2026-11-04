"""Historical PCR research session orchestration for API/UI consumers."""

from datetime import date, time
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .domain import (
    HistoricalCandle,
    HistoricalOptionContract,
    HistoricalPCRObservation,
    IST,
)
from .historical import (
    load_historical_option_candles,
    reconstruct_historical_pcr,
    reconstruct_historical_snapshots,
    resolve_historical_atm,
    resolve_historical_option_contracts,
)

PROVENANCE = "HISTORICAL_CANDLE_RECONSTRUCTION"


class HistoricalResearchGateway(Protocol):
    def historical_candles(
        self, instrument_key: str, session_date: date
    ) -> list[HistoricalCandle]: ...

    def historical_option_contracts(
        self, underlying: str, expiry: date
    ) -> list[HistoricalOptionContract]: ...

    def historical_option_candles(
        self, instrument_key: str, session_date: date
    ) -> list[HistoricalCandle]: ...


class ResearchModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HistoricalResearchSession(ResearchModel):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    underlying: str
    session_date: date
    expiry: date
    wings: int
    strike_interval: int
    provenance: Literal["HISTORICAL_CANDLE_RECONSTRUCTION"] = PROVENANCE
    observations: list[HistoricalPCRObservation]
    issues: list[str]


def build_historical_research_session(
    gateway: HistoricalResearchGateway,
    underlying: str,
    session_date: date,
    expiry: date,
    wings: int,
    strike_interval: int = 50,
    fixed_anchor_time: time = time(9, 20),
) -> HistoricalResearchSession:
    """Build one deterministic historical PCR session without persistence."""
    if type(wings) is not int or wings < 0:
        raise ValueError("wings must be a non-negative integer")
    if strike_interval <= 0:
        raise ValueError("strike_interval must be positive")

    underlying_candles = sorted(
        gateway.historical_candles(underlying, session_date),
        key=lambda candle: candle.timestamp,
    )
    if not underlying_candles:
        return HistoricalResearchSession(
            status="UNAVAILABLE",
            underlying=underlying,
            session_date=session_date,
            expiry=expiry,
            wings=wings,
            strike_interval=strike_interval,
            observations=[],
            issues=["underlying_candles_unavailable"],
        )

    timestamps = [candle.timestamp for candle in underlying_candles]
    if len(timestamps) != len(set(timestamps)):
        return HistoricalResearchSession(
            status="UNAVAILABLE",
            underlying=underlying,
            session_date=session_date,
            expiry=expiry,
            wings=wings,
            strike_interval=strike_interval,
            observations=[],
            issues=["duplicate_underlying_timestamps"],
        )

    atms = resolve_historical_atm(underlying_candles, strike_interval)
    fixed_anchor_candle = next(
        (
            candle
            for candle in underlying_candles
            if candle.timestamp.astimezone(IST).time().replace(tzinfo=None)
            == fixed_anchor_time
        ),
        None,
    )
    fixed_anchor_atm = (
        resolve_historical_atm([fixed_anchor_candle], strike_interval)[0].atm
        if fixed_anchor_candle is not None
        else None
    )

    catalog = gateway.historical_option_contracts(underlying, expiry)
    selected_by_identity: dict[tuple[float, str], HistoricalOptionContract] = {}
    required_atms = {value.atm for value in atms}
    if fixed_anchor_atm is not None:
        required_atms.add(fixed_anchor_atm)

    for atm in sorted(required_atms):
        for contract in resolve_historical_option_contracts(
            catalog, underlying, expiry, atm, wings, strike_interval
        ):
            identity = (contract.strike, contract.side)
            existing = selected_by_identity.get(identity)
            if existing is not None and existing != contract:
                raise ValueError("Conflicting historical option contract identity")
            selected_by_identity[identity] = contract

    selected_contracts = sorted(
        selected_by_identity.values(),
        key=lambda contract: (contract.strike, 0 if contract.side == "CE" else 1),
    )
    option_series = load_historical_option_candles(
        gateway, selected_contracts, session_date
    )
    snapshots = reconstruct_historical_snapshots(
        underlying_candles,
        selected_contracts,
        option_series,
        underlying,
        expiry,
        session_date,
        wings,
        strike_interval,
        fixed_anchor_time=fixed_anchor_time,
    )
    observations = reconstruct_historical_pcr(snapshots)

    return HistoricalResearchSession(
        status="AVAILABLE",
        underlying=underlying,
        session_date=session_date,
        expiry=expiry,
        wings=wings,
        strike_interval=strike_interval,
        observations=observations,
        issues=[],
    )
