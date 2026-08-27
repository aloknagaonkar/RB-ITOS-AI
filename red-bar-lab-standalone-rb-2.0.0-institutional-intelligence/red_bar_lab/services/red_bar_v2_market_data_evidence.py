from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path

import pandas as pd


FILENAME = "red_bar_v2_market_data_evidence.json"


@dataclass(frozen=True, slots=True)
class CandlePullEvidence:
    dataset: str
    instrument_key: str
    requested_at: str
    received_at: str
    duration_ms: float
    status: str
    reason: str
    row_count: int
    first_timestamp: str | None
    latest_timestamp: str | None
    latest_completed_timestamp: str | None
    expected_completed_timestamp: str
    freshness_seconds: float | None
    duplicate_timestamps: int
    missing_intervals: int
    provider: str = "UPSTOX"
    interval_minutes: int = 1
    source_mode: str = "PROVIDER_INTRADAY_RESPONSE"
    retry_count: int | None = None


def _timestamps(frame: pd.DataFrame) -> pd.Series:
    source = None
    for name in ("timestamp", "date", "datetime", "time"):
        if name in frame.columns:
            source = frame[name]
            break
    if source is None and isinstance(frame.index, pd.DatetimeIndex):
        source = frame.index
    parsed = pd.to_datetime(source, errors="coerce", utc=True)
    return pd.Series(parsed).dropna().sort_values().reset_index(drop=True)


def build_candle_pull_evidence(
    frame: pd.DataFrame,
    *,
    dataset: str,
    instrument_key: str,
    requested_at: datetime,
    received_at: datetime,
    duration_ms: float,
) -> CandlePullEvidence:
    """Summarize an existing provider response without another request."""
    valid = _timestamps(frame)
    duplicates = int(valid.duplicated().sum())
    unique = valid.drop_duplicates().reset_index(drop=True)
    expected = pd.Timestamp(received_at).floor("min") - pd.Timedelta(minutes=1)
    expected = expected.tz_localize("UTC") if expected.tzinfo is None else expected.tz_convert("UTC")
    completed = unique[unique <= expected]
    latest_completed = completed.iloc[-1] if not completed.empty else None
    missing = sum(
        max(0, int(round(value)) - 1)
        for value in (unique.diff().dropna().dt.total_seconds() / 60.0)
        if 0 < value <= 720
    )
    freshness = None
    if latest_completed is not None:
        received = pd.Timestamp(received_at)
        received = received.tz_localize("UTC") if received.tzinfo is None else received.tz_convert("UTC")
        freshness = max(0.0, float((received - latest_completed).total_seconds()))
    rows = int(len(frame))
    status = "READY" if rows and latest_completed is not None else "WAITING"
    reason = "COMPLETED_CANDLE_AVAILABLE" if status == "READY" else "PROVIDER_RETURNED_NO_COMPLETED_CANDLE" if rows else "PROVIDER_RETURNED_NO_ROWS"
    return CandlePullEvidence(
        dataset=dataset, instrument_key=instrument_key,
        requested_at=requested_at.isoformat(), received_at=received_at.isoformat(),
        duration_ms=round(float(duration_ms), 3), status=status, reason=reason,
        row_count=rows,
        first_timestamp=unique.iloc[0].isoformat() if not unique.empty else None,
        latest_timestamp=unique.iloc[-1].isoformat() if not unique.empty else None,
        latest_completed_timestamp=latest_completed.isoformat() if latest_completed is not None else None,
        expected_completed_timestamp=expected.isoformat(),
        freshness_seconds=round(freshness, 3) if freshness is not None else None,
        duplicate_timestamps=duplicates, missing_intervals=int(missing),
    )


def persist_market_data_evidence(
    artifacts_root: str | Path,
    evidence: tuple[CandlePullEvidence, ...],
    *,
    correlation_id: str | None,
    recorded_at: datetime,
) -> bool:
    """Atomically replace one bounded latest-cycle evidence artifact."""
    target = Path(artifacts_root) / "operations" / FILENAME
    temporary = target.with_suffix(".tmp")
    payload = {
        "schema_version": "RED_BAR_V2_MARKET_DATA_EVIDENCE_V1",
        "correlation_id": correlation_id,
        "recorded_at": recorded_at.isoformat(),
        "datasets": [asdict(item) for item in evidence],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(target)
    except OSError:
        return False
    return True


def read_market_data_evidence(artifacts_root: str | Path) -> dict[str, object]:
    target = Path(artifacts_root) / "operations" / FILENAME
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def persist_stage_latency(
    artifacts_root: str | Path,
    *,
    architecture: str,
    correlation_id: str | None,
    stages: list[dict[str, object]],
    recorded_at: datetime,
) -> bool:
    """Persist one bounded post-processing latency projection."""
    normalized = str(architecture).strip().lower()
    if normalized not in {"legacy", "canonical"}:
        raise ValueError("architecture must be legacy or canonical")
    target = Path(artifacts_root) / "operations" / f"red_bar_v2_{normalized}_stage_latency.json"
    temporary = target.with_suffix(".tmp")
    payload = {
        "schema_version": "RED_BAR_V2_STAGE_LATENCY_V1",
        "architecture": normalized.upper(),
        "correlation_id": correlation_id,
        "recorded_at": recorded_at.isoformat(),
        "stages": stages,
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(target)
    except OSError:
        return False
    return True


def read_stage_latency(
    artifacts_root: str | Path,
    architecture: str,
) -> dict[str, object]:
    normalized = str(architecture).strip().lower()
    target = Path(artifacts_root) / "operations" / f"red_bar_v2_{normalized}_stage_latency.json"
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


__all__ = [
    "CandlePullEvidence",
    "build_candle_pull_evidence",
    "persist_market_data_evidence",
    "read_market_data_evidence",
    "persist_stage_latency",
    "read_stage_latency",
]
