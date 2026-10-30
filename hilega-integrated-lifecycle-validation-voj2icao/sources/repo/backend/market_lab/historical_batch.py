"""Deterministic multi-session historical validation batch support.

The batch layer intentionally does not infer expiries.  Every session must provide
an explicit expiry so research runs remain reproducible across weekly expiries.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .historical_validation import HistoricalSessionValidationReport

PROVENANCE = "HISTORICAL_CANDLE_RECONSTRUCTION"


class HistoricalBatchModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HistoricalBatchSessionSpec(HistoricalBatchModel):
    session_date: date
    expiry: date

    @model_validator(mode="after")
    def validate_dates(self):
        if self.expiry < self.session_date:
            raise ValueError("expiry must be on or after session_date")
        return self


class HistoricalBatchManifest(HistoricalBatchModel):
    sessions: list[HistoricalBatchSessionSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_sessions(self):
        session_dates = [item.session_date for item in self.sessions]
        if len(session_dates) != len(set(session_dates)):
            raise ValueError("manifest contains duplicate session_date values")
        return self


class HistoricalBatchSessionResult(HistoricalBatchModel):
    session_date: date
    expiry: date
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    report: HistoricalSessionValidationReport | None = None
    issues: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report_consistency(self):
        if self.report is not None:
            if self.report.session_date != self.session_date or self.report.expiry != self.expiry:
                raise ValueError("session result does not match report dates")
            if self.report.status != self.status:
                raise ValueError("session result status does not match report status")
        return self


class HistoricalBatchReport(HistoricalBatchModel):
    status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    underlying: str
    wings: int
    requested_session_count: int
    available_session_count: int
    unavailable_session_count: int
    first_session_date: date
    last_session_date: date
    total_underlying_candles: int
    total_reconstructed_snapshots: int
    total_atm_changes: int
    total_selected_contracts: int
    total_empty_candle_series: int
    total_missing_contract_sides: int
    total_missing_candle_sides: int
    total_missing_oi_sides: int
    moving_pcr_available_count: int
    moving_pcr_unavailable_count: int
    fixed_pcr_available_count: int
    fixed_pcr_unavailable_count: int
    full_reconstructed_pcr_available_count: int
    full_reconstructed_pcr_unavailable_count: int
    sessions_with_timestamp_gaps: int
    duplicate_timestamp_count: int
    provenance: Literal["HISTORICAL_CANDLE_RECONSTRUCTION"] = PROVENANCE
    sessions: list[HistoricalBatchSessionResult]


def load_historical_batch_manifest(path: str | Path) -> HistoricalBatchManifest:
    """Load an explicit session/expiry manifest from JSON."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        payload = {"sessions": payload}
    return HistoricalBatchManifest.model_validate(payload)


def build_historical_batch_report(
    underlying: str,
    wings: int,
    results: Iterable[HistoricalBatchSessionResult],
) -> HistoricalBatchReport:
    """Aggregate already-executed session reports without changing session semantics."""
    ordered = sorted(results, key=lambda item: item.session_date)
    if not ordered:
        raise ValueError("at least one historical batch session result is required")
    if type(wings) is not int or wings < 0:
        raise ValueError("wings must be a non-negative integer")

    available = [item for item in ordered if item.status == "AVAILABLE" and item.report is not None]
    reports = [item.report for item in available if item.report is not None]
    unavailable_count = len(ordered) - len(available)
    if len(available) == len(ordered):
        status = "AVAILABLE"
    elif available:
        status = "PARTIAL"
    else:
        status = "UNAVAILABLE"

    return HistoricalBatchReport(
        status=status,
        underlying=underlying,
        wings=wings,
        requested_session_count=len(ordered),
        available_session_count=len(available),
        unavailable_session_count=unavailable_count,
        first_session_date=ordered[0].session_date,
        last_session_date=ordered[-1].session_date,
        total_underlying_candles=sum(report.underlying_candle_count for report in reports),
        total_reconstructed_snapshots=sum(report.reconstructed_snapshot_count for report in reports),
        total_atm_changes=sum(report.atm_change_count for report in reports),
        total_selected_contracts=sum(report.selected_contract_count for report in reports),
        total_empty_candle_series=sum(report.empty_candle_series_count for report in reports),
        total_missing_contract_sides=sum(report.missing_contract_side_count for report in reports),
        total_missing_candle_sides=sum(report.missing_candle_side_count for report in reports),
        total_missing_oi_sides=sum(report.missing_oi_side_count for report in reports),
        moving_pcr_available_count=sum(report.moving_pcr_available_count for report in reports),
        moving_pcr_unavailable_count=sum(report.moving_pcr_unavailable_count for report in reports),
        fixed_pcr_available_count=sum(report.fixed_pcr_available_count for report in reports),
        fixed_pcr_unavailable_count=sum(report.fixed_pcr_unavailable_count for report in reports),
        full_reconstructed_pcr_available_count=sum(
            report.full_reconstructed_pcr_available_count for report in reports
        ),
        full_reconstructed_pcr_unavailable_count=sum(
            report.full_reconstructed_pcr_unavailable_count for report in reports
        ),
        sessions_with_timestamp_gaps=sum(bool(report.timestamp_gaps) for report in reports),
        duplicate_timestamp_count=sum(report.duplicate_timestamp_count for report in reports),
        sessions=ordered,
    )
