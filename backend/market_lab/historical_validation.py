"""One-shot historical session validation without persistence or strategy behavior."""

from datetime import date, datetime, time
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

from .domain import HistoricalCandle, HistoricalOptionContract, IST
from .historical import (
    load_historical_option_candles,
    reconstruct_historical_pcr,
    reconstruct_historical_snapshots,
    resolve_historical_atm,
    resolve_historical_option_contracts,
)

PROVENANCE = "HISTORICAL_CANDLE_RECONSTRUCTION"


class HistoricalSessionGateway(Protocol):
    def historical_candles(
        self, instrument_key: str, session_date: date
    ) -> list[HistoricalCandle]: ...

    def historical_option_contracts(
        self, underlying: str, expiry: date
    ) -> list[HistoricalOptionContract]: ...

    def historical_option_candles(
        self, instrument_key: str, session_date: date
    ) -> list[HistoricalCandle]: ...


class ReportModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HistoricalValidationGap(ReportModel):
    previous_timestamp: AwareDatetime
    next_timestamp: AwareDatetime
    elapsed_seconds: float


class HistoricalValidationPCRPoint(ReportModel):
    timestamp: AwareDatetime
    pcr: float


class HistoricalSessionValidationReport(ReportModel):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    underlying: str
    session_date: date
    expiry: date
    wings: int
    underlying_candle_count: int
    reconstructed_snapshot_count: int
    first_timestamp: AwareDatetime | None = None
    last_timestamp: AwareDatetime | None = None
    minimum_atm: float | None = None
    maximum_atm: float | None = None
    atm_change_count: int
    selected_contract_count: int
    empty_candle_series_count: int
    missing_contract_side_count: int
    missing_candle_side_count: int
    missing_oi_side_count: int
    moving_pcr_available_count: int
    moving_pcr_unavailable_count: int
    full_reconstructed_pcr_available_count: int
    full_reconstructed_pcr_unavailable_count: int
    fixed_anchor_time: str = "09:20:00"
    fixed_anchor_status: Literal["CAPTURED", "UNAVAILABLE"] = "UNAVAILABLE"
    fixed_anchor_spot: float | None = None
    fixed_anchor_atm: float | None = None
    fixed_pcr_available_count: int
    fixed_pcr_unavailable_count: int
    first_valid_moving_pcr: HistoricalValidationPCRPoint | None = None
    last_valid_moving_pcr: HistoricalValidationPCRPoint | None = None
    first_valid_fixed_pcr: HistoricalValidationPCRPoint | None = None
    last_valid_fixed_pcr: HistoricalValidationPCRPoint | None = None
    timestamp_gaps: list[HistoricalValidationGap]
    duplicate_timestamp_count: int
    provenance: Literal["HISTORICAL_CANDLE_RECONSTRUCTION"] = PROVENANCE
    issues: list[str]


def _empty_report(
    underlying: str,
    session_date: date,
    expiry: date,
    wings: int,
    candle_count: int = 0,
    first_timestamp: datetime | None = None,
    last_timestamp: datetime | None = None,
    duplicate_timestamp_count: int = 0,
    issues: list[str] | None = None,
) -> HistoricalSessionValidationReport:
    return HistoricalSessionValidationReport(
        status="UNAVAILABLE",
        underlying=underlying,
        session_date=session_date,
        expiry=expiry,
        wings=wings,
        underlying_candle_count=candle_count,
        reconstructed_snapshot_count=0,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        atm_change_count=0,
        selected_contract_count=0,
        empty_candle_series_count=0,
        missing_contract_side_count=0,
        missing_candle_side_count=0,
        missing_oi_side_count=0,
        moving_pcr_available_count=0,
        moving_pcr_unavailable_count=0,
        full_reconstructed_pcr_available_count=0,
        full_reconstructed_pcr_unavailable_count=0,
        fixed_pcr_available_count=0,
        fixed_pcr_unavailable_count=0,
        timestamp_gaps=[],
        duplicate_timestamp_count=duplicate_timestamp_count,
        issues=issues or ["underlying_candles_unavailable"],
    )


def validate_historical_session(
    gateway: HistoricalSessionGateway,
    underlying: str,
    session_date: date,
    expiry: date,
    wings: int,
    strike_interval: int = 50,
) -> HistoricalSessionValidationReport:
    """Retrieve once, reconstruct purely, and return only validation metadata."""
    if type(wings) is not int or wings < 0:
        raise ValueError("wings must be a non-negative integer")
    underlying_candles = sorted(
        gateway.historical_candles(underlying, session_date),
        key=lambda candle: candle.timestamp,
    )
    if not underlying_candles:
        return _empty_report(underlying, session_date, expiry, wings)

    timestamps = [candle.timestamp for candle in underlying_candles]
    duplicate_count = len(timestamps) - len(set(timestamps))
    if duplicate_count:
        return _empty_report(
            underlying,
            session_date,
            expiry,
            wings,
            candle_count=len(underlying_candles),
            first_timestamp=timestamps[0],
            last_timestamp=timestamps[-1],
            duplicate_timestamp_count=duplicate_count,
            issues=["duplicate_underlying_timestamps"],
        )

    gaps = [
        HistoricalValidationGap(
            previous_timestamp=previous,
            next_timestamp=current,
            elapsed_seconds=(current - previous).total_seconds(),
        )
        for previous, current in zip(timestamps, timestamps[1:])
        if (current - previous).total_seconds() > 60
    ]
    atms = resolve_historical_atm(underlying_candles, strike_interval)
    fixed_anchor_clock = time(9, 20)
    fixed_anchor_candle = next(
        (
            candle for candle in underlying_candles
            if candle.timestamp.astimezone(IST).time().replace(tzinfo=None) == fixed_anchor_clock
        ),
        None,
    )
    fixed_anchor_atm = (
        resolve_historical_atm([fixed_anchor_candle], strike_interval)[0].atm
        if fixed_anchor_candle is not None
        else None
    )
    catalog = gateway.historical_option_contracts(underlying, expiry)
    selected_by_identity = {}
    for atm in sorted({value.atm for value in atms}):
        for contract in resolve_historical_option_contracts(
            catalog, underlying, expiry, atm, wings, strike_interval
        ):
            identity = (contract.strike, contract.side)
            existing = selected_by_identity.get(identity)
            if existing is not None and existing != contract:
                raise ValueError("Conflicting historical option contract identity")
            selected_by_identity[identity] = contract
    if fixed_anchor_atm is not None:
        for contract in resolve_historical_option_contracts(
            catalog, underlying, expiry, fixed_anchor_atm, wings, strike_interval
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
    series = load_historical_option_candles(gateway, selected_contracts, session_date)
    snapshots = reconstruct_historical_snapshots(
        underlying_candles,
        selected_contracts,
        series,
        underlying,
        expiry,
        session_date,
        wings,
        strike_interval,
    )
    pcr_observations = reconstruct_historical_pcr(snapshots)

    side_statuses = [
        side.status
        for snapshot in snapshots
        for row in snapshot.strikes
        for side in (row.ce, row.pe)
    ]
    moving_available = [
        observation for observation in pcr_observations
        if observation.moving_panel.status == "AVAILABLE"
    ]
    full_available = [
        observation for observation in pcr_observations
        if observation.full_reconstructed_panel.status == "AVAILABLE"
    ]
    fixed_available = [
        observation for observation in pcr_observations
        if observation.fixed_panel.status == "AVAILABLE"
    ]

    def moving_point(observation):
        return HistoricalValidationPCRPoint(
            timestamp=observation.timestamp,
            pcr=observation.moving_panel.pcr,
        )

    def fixed_point(observation):
        return HistoricalValidationPCRPoint(
            timestamp=observation.timestamp,
            pcr=observation.fixed_panel.pcr,
        )

    return HistoricalSessionValidationReport(
        status="AVAILABLE",
        underlying=underlying,
        session_date=session_date,
        expiry=expiry,
        wings=wings,
        underlying_candle_count=len(underlying_candles),
        reconstructed_snapshot_count=len(snapshots),
        first_timestamp=timestamps[0],
        last_timestamp=timestamps[-1],
        minimum_atm=min(value.atm for value in atms),
        maximum_atm=max(value.atm for value in atms),
        atm_change_count=sum(
            current.atm != previous.atm
            for previous, current in zip(atms, atms[1:])
        ),
        selected_contract_count=len(selected_contracts),
        empty_candle_series_count=sum(not item.candles for item in series),
        missing_contract_side_count=side_statuses.count("CONTRACT_UNAVAILABLE"),
        missing_candle_side_count=side_statuses.count("CANDLE_UNAVAILABLE"),
        missing_oi_side_count=side_statuses.count("OI_UNAVAILABLE"),
        moving_pcr_available_count=len(moving_available),
        moving_pcr_unavailable_count=len(pcr_observations) - len(moving_available),
        full_reconstructed_pcr_available_count=len(full_available),
        full_reconstructed_pcr_unavailable_count=len(pcr_observations) - len(full_available),
        fixed_anchor_time=fixed_anchor_clock.isoformat(),
        fixed_anchor_status="CAPTURED" if fixed_anchor_candle is not None else "UNAVAILABLE",
        fixed_anchor_spot=fixed_anchor_candle.close if fixed_anchor_candle is not None else None,
        fixed_anchor_atm=fixed_anchor_atm,
        fixed_pcr_available_count=len(fixed_available),
        fixed_pcr_unavailable_count=len(pcr_observations) - len(fixed_available),
        first_valid_moving_pcr=moving_point(moving_available[0]) if moving_available else None,
        last_valid_moving_pcr=moving_point(moving_available[-1]) if moving_available else None,
        first_valid_fixed_pcr=fixed_point(fixed_available[0]) if fixed_available else None,
        last_valid_fixed_pcr=fixed_point(fixed_available[-1]) if fixed_available else None,
        timestamp_gaps=gaps,
        duplicate_timestamp_count=0,
        issues=[],
    )