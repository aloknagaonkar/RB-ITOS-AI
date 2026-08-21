from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping

import pandas as pd


RSI_READINESS_POLICY_VERSION = "rsi-readiness-v1"


@dataclass(frozen=True)
class RsiReadiness:
    status: str
    rsi_value: float | None
    period: int | None
    candle_count: int | None
    source_timestamp: str | None
    as_of_timestamp: str | None
    age_seconds: int | None
    no_lookahead_passed: bool | None
    reason_code: str | None = None
    reason: str | None = None
    authority: str = "OBSERVATIONAL_ONLY"
    policy_version: str = RSI_READINESS_POLICY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if result.tzinfo is None:
        return result.tz_localize("Asia/Kolkata")
    return result.tz_convert("Asia/Kolkata")


def _float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def assess_rsi_readiness(
    observation: Mapping[str, Any] | None,
    *,
    as_of_timestamp: object,
    expected_period: int = 7,
    minimum_candles: int | None = None,
    max_age_seconds: int = 120,
) -> RsiReadiness:
    """Assess RSI readiness only from observed, timestamped inputs.

    The result never infers support from configuration alone. Missing value,
    period, candle count, timestamp, stale data, or lookahead all prevent READY.
    """

    row = dict(observation or {})
    as_of = _timestamp(as_of_timestamp)
    source = _timestamp(
        row.get("source_timestamp")
        or row.get("timestamp")
        or row.get("candle_timestamp")
        or row.get("calculated_at")
    )
    value = _float(row.get("rsi_value") if "rsi_value" in row else row.get("rsi"))
    period = _int(row.get("period") if "period" in row else row.get("rsi_period"))
    candle_count = _int(
        row.get("candle_count")
        if "candle_count" in row
        else row.get("source_candle_count")
    )
    required_candles = minimum_candles or expected_period + 1

    base = dict(
        rsi_value=value,
        period=period,
        candle_count=candle_count,
        source_timestamp=source.isoformat() if source is not None else None,
        as_of_timestamp=as_of.isoformat() if as_of is not None else None,
        age_seconds=None,
        no_lookahead_passed=None,
    )

    if as_of is None:
        return RsiReadiness(
            status="FAILED",
            reason_code="RSI_AS_OF_TIMESTAMP_INVALID",
            reason="The RSI readiness as-of timestamp is invalid.",
            **base,
        )
    if not row:
        return RsiReadiness(
            status="MISSING",
            reason_code="RSI_OBSERVATION_MISSING",
            reason="No observed RSI calculation is available.",
            **base,
        )
    if source is None:
        return RsiReadiness(
            status="MISSING",
            reason_code="RSI_SOURCE_TIMESTAMP_MISSING",
            reason="The observed RSI calculation has no source timestamp.",
            **base,
        )

    no_lookahead = source <= as_of
    age = int((as_of - source).total_seconds()) if no_lookahead else None
    base["age_seconds"] = age
    base["no_lookahead_passed"] = no_lookahead

    if not no_lookahead:
        return RsiReadiness(
            status="FAILED",
            reason_code="RSI_LOOKAHEAD_DETECTED",
            reason="The RSI source timestamp is later than the readiness cutoff.",
            **base,
        )
    if value is None or not 0.0 <= value <= 100.0:
        return RsiReadiness(
            status="MISSING",
            reason_code="RSI_VALUE_MISSING_OR_INVALID",
            reason="A finite RSI value between 0 and 100 is required.",
            **base,
        )
    if period != expected_period:
        return RsiReadiness(
            status="MISSING",
            reason_code="RSI_PERIOD_NOT_OBSERVED",
            reason=f"Observed RSI period must equal {expected_period}.",
            **base,
        )
    if candle_count is None or candle_count < required_candles:
        return RsiReadiness(
            status="MISSING",
            reason_code="RSI_CANDLE_COVERAGE_INSUFFICIENT",
            reason=f"At least {required_candles} completed candles are required.",
            **base,
        )
    if age is not None and age > max_age_seconds:
        return RsiReadiness(
            status="STALE",
            reason_code="RSI_OBSERVATION_STALE",
            reason=f"The observed RSI value is {age} seconds old.",
            **base,
        )

    return RsiReadiness(status="READY", **base)


__all__ = [
    "RSI_READINESS_POLICY_VERSION",
    "RsiReadiness",
    "assess_rsi_readiness",
]
