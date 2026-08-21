from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

import pandas as pd

FRESHNESS_ALIGNMENT_POLICY_VERSION = "freshness-alignment-v1"


@dataclass(frozen=True)
class CollectorFreshnessResult:
    status: str
    latest_timestamp: str | None
    age_seconds: float | None
    threshold_seconds: float
    reason_code: str | None
    policy_version: str = FRESHNESS_ALIGNMENT_POLICY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SignalAlignmentResult:
    signal_id: str
    status: str
    signal_timestamp: str | None
    source_timestamp: str | None
    delay_seconds: float | None
    tolerance_seconds: float
    no_lookahead_passed: bool
    reason_code: str | None
    policy_version: str = FRESHNESS_ALIGNMENT_POLICY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        return stamp.tz_localize("Asia/Kolkata")
    return stamp.tz_convert("Asia/Kolkata")


def assess_collector_freshness(
    *,
    latest_timestamp: object,
    as_of_timestamp: object | None = None,
    threshold_seconds: float = 120.0,
) -> CollectorFreshnessResult:
    latest = _timestamp(latest_timestamp)
    as_of = _timestamp(as_of_timestamp or datetime.now().astimezone())
    if latest is None or as_of is None:
        return CollectorFreshnessResult(
            status="MISSING",
            latest_timestamp=latest.isoformat() if latest is not None else None,
            age_seconds=None,
            threshold_seconds=float(threshold_seconds),
            reason_code="COLLECTOR_TIMESTAMP_MISSING",
        )
    age = (as_of - latest).total_seconds()
    if age < 0:
        return CollectorFreshnessResult(
            status="FAILED",
            latest_timestamp=latest.isoformat(),
            age_seconds=float(age),
            threshold_seconds=float(threshold_seconds),
            reason_code="COLLECTOR_TIMESTAMP_IN_FUTURE",
        )
    return CollectorFreshnessResult(
        status="READY" if age <= threshold_seconds else "STALE",
        latest_timestamp=latest.isoformat(),
        age_seconds=float(age),
        threshold_seconds=float(threshold_seconds),
        reason_code=None if age <= threshold_seconds else "COLLECTOR_STALE",
    )


def assess_signal_alignment(
    *,
    signal_id: str,
    signal_timestamp: object,
    source_timestamp: object,
    tolerance_seconds: float = 120.0,
) -> SignalAlignmentResult:
    signal = _timestamp(signal_timestamp)
    source = _timestamp(source_timestamp)
    if signal is None or source is None:
        return SignalAlignmentResult(
            signal_id=str(signal_id),
            status="MISSING",
            signal_timestamp=signal.isoformat() if signal is not None else None,
            source_timestamp=source.isoformat() if source is not None else None,
            delay_seconds=None,
            tolerance_seconds=float(tolerance_seconds),
            no_lookahead_passed=False,
            reason_code="ALIGNMENT_TIMESTAMP_MISSING",
        )
    delay = (signal - source).total_seconds()
    no_lookahead = delay >= 0
    if not no_lookahead:
        status, reason = "FAILED", "SOURCE_AFTER_SIGNAL"
    elif delay > tolerance_seconds:
        status, reason = "STALE", "SIGNAL_ALIGNMENT_OUTSIDE_TOLERANCE"
    else:
        status, reason = "READY", None
    return SignalAlignmentResult(
        signal_id=str(signal_id),
        status=status,
        signal_timestamp=signal.isoformat(),
        source_timestamp=source.isoformat(),
        delay_seconds=float(delay),
        tolerance_seconds=float(tolerance_seconds),
        no_lookahead_passed=no_lookahead,
        reason_code=reason,
    )


def summarize_alignment_coverage(
    results: Iterable[SignalAlignmentResult | Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [row.as_dict() if isinstance(row, SignalAlignmentResult) else dict(row) for row in results]
    total = len(rows)
    ready = sum(str(row.get("status") or "").upper() == "READY" for row in rows)
    return {
        "total_signals": total,
        "aligned_signals": ready,
        "alignment_coverage_pct": round(ready / total * 100.0, 2) if total else 100.0,
        "status": "READY" if total == 0 or ready == total else "PARTIAL" if ready else "MISSING",
        "policy_version": FRESHNESS_ALIGNMENT_POLICY_VERSION,
    }


__all__ = [
    "FRESHNESS_ALIGNMENT_POLICY_VERSION",
    "CollectorFreshnessResult",
    "SignalAlignmentResult",
    "assess_collector_freshness",
    "assess_signal_alignment",
    "summarize_alignment_coverage",
]
