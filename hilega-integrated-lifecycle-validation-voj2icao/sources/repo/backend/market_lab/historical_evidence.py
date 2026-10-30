"""Cross-session fact-only evidence rows from reconstructed historical PCR sessions.

This module intentionally derives measurements only. It does not classify trades,
place orders, or infer missing timestamps. All horizon lookups require exact
same-session minute timestamps.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from .domain import HistoricalPCRObservation
from .historical_research import HistoricalResearchSession

PROVENANCE = "HISTORICAL_CANDLE_RECONSTRUCTION"


class HistoricalEvidenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HistoricalEvidenceRow(HistoricalEvidenceModel):
    session_date: date
    expiry: date
    timestamp: datetime
    underlying: str
    provenance: Literal["HISTORICAL_CANDLE_RECONSTRUCTION"] = PROVENANCE

    spot: float
    fixed_atm: float | None = None
    moving_atm: float
    atm_divergence_points: float | None = None

    fixed_pcr: float | None = None
    moving_pcr: float | None = None
    full_pcr: float | None = None
    fixed_moving_pcr_spread: float | None = None

    fixed_pcr_change_1m: float | None = None
    fixed_pcr_change_5m: float | None = None
    fixed_pcr_change_15m: float | None = None
    fixed_pcr_change_30m: float | None = None
    moving_pcr_change_1m: float | None = None
    moving_pcr_change_5m: float | None = None
    moving_pcr_change_15m: float | None = None
    moving_pcr_change_30m: float | None = None
    full_pcr_change_1m: float | None = None
    full_pcr_change_5m: float | None = None
    full_pcr_change_15m: float | None = None
    full_pcr_change_30m: float | None = None

    fixed_call_oi_change_pct: float | None = None
    fixed_put_oi_change_pct: float | None = None
    moving_call_oi_change_pct: float | None = None
    moving_put_oi_change_pct: float | None = None
    full_call_oi_change_pct: float | None = None
    full_put_oi_change_pct: float | None = None

    forward_change_5m: float | None = None
    forward_change_10m: float | None = None
    forward_change_15m: float | None = None
    forward_change_30m: float | None = None


class HistoricalEvidenceSessionSummary(HistoricalEvidenceModel):
    session_date: date
    expiry: date
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    row_count: int = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    fixed_rows_available: int = 0
    moving_rows_available: int = 0
    full_rows_available: int = 0
    issues: list[str] = Field(default_factory=list)


class HistoricalEvidenceDataset(HistoricalEvidenceModel):
    status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    underlying: str
    requested_session_count: int
    available_session_count: int
    unavailable_session_count: int
    row_count: int
    provenance: Literal["HISTORICAL_CANDLE_RECONSTRUCTION"] = PROVENANCE
    sessions: list[HistoricalEvidenceSessionSummary]
    rows: list[HistoricalEvidenceRow]


def _panel_pcr(observation: HistoricalPCRObservation, mode: str) -> float | None:
    panel = {
        "fixed": observation.fixed_panel,
        "moving": observation.moving_panel,
        "full": observation.full_reconstructed_panel,
    }[mode]
    return panel.pcr if panel.status == "AVAILABLE" else None


def _exact_observation(
    by_timestamp: dict[datetime, HistoricalPCRObservation],
    timestamp: datetime,
    minutes: int,
) -> HistoricalPCRObservation | None:
    return by_timestamp.get(timestamp + timedelta(minutes=minutes))


def _pcr_change(
    current: HistoricalPCRObservation,
    previous: HistoricalPCRObservation | None,
    mode: str,
) -> float | None:
    if previous is None:
        return None
    current_value = _panel_pcr(current, mode)
    previous_value = _panel_pcr(previous, mode)
    if current_value is None or previous_value is None:
        return None
    return current_value - previous_value


def build_historical_evidence_rows(
    session: HistoricalResearchSession,
) -> list[HistoricalEvidenceRow]:
    """Flatten one reconstructed session into deterministic research rows."""
    if session.status != "AVAILABLE" or not session.observations:
        return []

    ordered = sorted(session.observations, key=lambda item: item.timestamp)
    by_timestamp = {item.timestamp: item for item in ordered}
    if len(by_timestamp) != len(ordered):
        raise ValueError("duplicate historical evidence timestamps")

    output: list[HistoricalEvidenceRow] = []
    for observation in ordered:
        fixed_pcr = _panel_pcr(observation, "fixed")
        moving_pcr = _panel_pcr(observation, "moving")
        full_pcr = _panel_pcr(observation, "full")
        fixed_atm = observation.fixed_panel.atm if observation.fixed_panel.status == "AVAILABLE" else None

        previous = {
            horizon: _exact_observation(by_timestamp, observation.timestamp, -horizon)
            for horizon in (1, 5, 15, 30)
        }
        future = {
            horizon: _exact_observation(by_timestamp, observation.timestamp, horizon)
            for horizon in (5, 10, 15, 30)
        }

        output.append(HistoricalEvidenceRow(
            session_date=observation.session_date,
            expiry=observation.expiry,
            timestamp=observation.timestamp,
            underlying=observation.underlying,
            spot=observation.spot,
            fixed_atm=fixed_atm,
            moving_atm=observation.moving_atm,
            atm_divergence_points=(
                observation.moving_atm - fixed_atm if fixed_atm is not None else None
            ),
            fixed_pcr=fixed_pcr,
            moving_pcr=moving_pcr,
            full_pcr=full_pcr,
            fixed_moving_pcr_spread=(
                moving_pcr - fixed_pcr
                if moving_pcr is not None and fixed_pcr is not None else None
            ),
            fixed_pcr_change_1m=_pcr_change(observation, previous[1], "fixed"),
            fixed_pcr_change_5m=_pcr_change(observation, previous[5], "fixed"),
            fixed_pcr_change_15m=_pcr_change(observation, previous[15], "fixed"),
            fixed_pcr_change_30m=_pcr_change(observation, previous[30], "fixed"),
            moving_pcr_change_1m=_pcr_change(observation, previous[1], "moving"),
            moving_pcr_change_5m=_pcr_change(observation, previous[5], "moving"),
            moving_pcr_change_15m=_pcr_change(observation, previous[15], "moving"),
            moving_pcr_change_30m=_pcr_change(observation, previous[30], "moving"),
            full_pcr_change_1m=_pcr_change(observation, previous[1], "full"),
            full_pcr_change_5m=_pcr_change(observation, previous[5], "full"),
            full_pcr_change_15m=_pcr_change(observation, previous[15], "full"),
            full_pcr_change_30m=_pcr_change(observation, previous[30], "full"),
            fixed_call_oi_change_pct=observation.fixed_panel.call_oi_change_pct,
            fixed_put_oi_change_pct=observation.fixed_panel.put_oi_change_pct,
            moving_call_oi_change_pct=observation.moving_panel.call_oi_change_pct,
            moving_put_oi_change_pct=observation.moving_panel.put_oi_change_pct,
            full_call_oi_change_pct=observation.full_reconstructed_panel.call_oi_change_pct,
            full_put_oi_change_pct=observation.full_reconstructed_panel.put_oi_change_pct,
            forward_change_5m=(future[5].spot - observation.spot if future[5] else None),
            forward_change_10m=(future[10].spot - observation.spot if future[10] else None),
            forward_change_15m=(future[15].spot - observation.spot if future[15] else None),
            forward_change_30m=(future[30].spot - observation.spot if future[30] else None),
        ))
    return output


def build_historical_evidence_dataset(
    underlying: str,
    sessions: Iterable[HistoricalResearchSession],
    unavailable: Iterable[HistoricalEvidenceSessionSummary] = (),
) -> HistoricalEvidenceDataset:
    available_sessions = sorted(sessions, key=lambda item: item.session_date)
    unavailable_summaries = list(unavailable)
    summaries: list[HistoricalEvidenceSessionSummary] = []
    rows: list[HistoricalEvidenceRow] = []

    for session in available_sessions:
        session_rows = build_historical_evidence_rows(session)
        rows.extend(session_rows)
        summaries.append(HistoricalEvidenceSessionSummary(
            session_date=session.session_date,
            expiry=session.expiry,
            status=session.status,
            row_count=len(session_rows),
            first_timestamp=session_rows[0].timestamp if session_rows else None,
            last_timestamp=session_rows[-1].timestamp if session_rows else None,
            fixed_rows_available=sum(row.fixed_pcr is not None for row in session_rows),
            moving_rows_available=sum(row.moving_pcr is not None for row in session_rows),
            full_rows_available=sum(row.full_pcr is not None for row in session_rows),
            issues=session.issues,
        ))

    summaries.extend(unavailable_summaries)
    summaries.sort(key=lambda item: item.session_date)
    requested = len(summaries)
    available_count = sum(item.status == "AVAILABLE" for item in summaries)
    unavailable_count = requested - available_count
    if requested == 0 or available_count == 0:
        status = "UNAVAILABLE"
    elif unavailable_count:
        status = "PARTIAL"
    else:
        status = "AVAILABLE"

    rows.sort(key=lambda item: (item.session_date, item.timestamp))
    return HistoricalEvidenceDataset(
        status=status,
        underlying=underlying,
        requested_session_count=requested,
        available_session_count=available_count,
        unavailable_session_count=unavailable_count,
        row_count=len(rows),
        sessions=summaries,
        rows=rows,
    )


def write_historical_evidence_json(dataset: HistoricalEvidenceDataset, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")


def write_historical_evidence_csv(dataset: HistoricalEvidenceDataset, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(HistoricalEvidenceRow.model_fields)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in dataset.rows:
            payload = row.model_dump(mode="json")
            writer.writerow(payload)
