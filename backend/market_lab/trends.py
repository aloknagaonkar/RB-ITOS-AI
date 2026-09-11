"""Pure, deterministic PCR trend calculations over persisted normalized history."""

from datetime import timedelta
from typing import Iterable

from .domain import IST, PCRHistoryRecord, PCRTrendClassification, PCRTrendConfig, PCRTrendResult

TREND_HORIZONS_SECONDS = (60, 300, 900, 1800)


def calculate_trend(
    current: PCRHistoryRecord,
    history: Iterable[PCRHistoryRecord],
    horizon_seconds: int,
    config: PCRTrendConfig,
) -> PCRTrendResult:
    base = {
        "record_id": current.id,
        "observation_id": current.observation_id,
        "configuration_version": current.configuration_version,
        "record_kind": current.record_kind,
        "mode": current.mode,
        "strike": current.strike,
        "requested_horizon_seconds": horizon_seconds,
        "current_pcr": current.pcr,
    }
    if current.data_status != "AVAILABLE" or current.pcr is None:
        return PCRTrendResult(
            **base,
            classification=PCRTrendClassification.UNAVAILABLE,
            status="UNAVAILABLE",
        )
    target = current.received_at - timedelta(seconds=horizon_seconds)
    earliest = target - timedelta(seconds=config.timestamp_tolerance_seconds)
    current_session_date = current.received_at.astimezone(IST).date()
    candidates = [
        item for item in history
        if item.fingerprint == current.fingerprint
        and item.id != current.id
        and item.data_status == "AVAILABLE"
        and item.pcr is not None
        and item.received_at.astimezone(IST).date() == current_session_date
        and earliest <= item.received_at <= target
    ]
    if not candidates:
        return PCRTrendResult(
            **base,
            classification=PCRTrendClassification.UNAVAILABLE,
            status="UNAVAILABLE",
        )
    baseline = max(candidates, key=lambda item: (item.received_at, item.id or -1))
    change = current.pcr - baseline.pcr
    percentage = change / baseline.pcr * 100 if baseline.pcr != 0 else None
    classification = (
        PCRTrendClassification.RISING if change > config.flat_threshold else
        PCRTrendClassification.FALLING if change < -config.flat_threshold else
        PCRTrendClassification.FLAT
    )
    return PCRTrendResult(
        **base,
        baseline_pcr=baseline.pcr,
        absolute_pcr_change=change,
        percentage_change=percentage,
        actual_elapsed_seconds=(current.received_at - baseline.received_at).total_seconds(),
        baseline_received_at=baseline.received_at,
        classification=classification,
        status="AVAILABLE",
    )
