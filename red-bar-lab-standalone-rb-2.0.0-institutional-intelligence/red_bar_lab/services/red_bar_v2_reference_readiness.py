from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Mapping

RED_BAR_V2_REFERENCE_TYPE = "NEXT_RED_CANDLE"
REFERENCE_POLICY_VERSION = "rbv2-reference-readiness-v1"


@dataclass(frozen=True)
class RedBarV2ReferenceReadiness:
    signal_id: str
    status: str
    reference_type: str | None
    reference_timestamp: str | None
    reference_high: float | None
    reference_low: float | None
    reference_midpoint: float | None
    data_quality: str | None
    reason_code: str | None
    reason: str
    policy_version: str = REFERENCE_POLICY_VERSION
    authority: str = "OBSERVATIONAL_ONLY"


def _timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def assess_red_bar_v2_reference_readiness(
    signal: Mapping[str, Any],
    reference: Mapping[str, Any] | None,
) -> RedBarV2ReferenceReadiness:
    """Validate the frozen Red Bar V2 NEXT_RED_CANDLE reference.

    This diagnostic is additive and read-only. It does not grant admission or
    execution authority and does not modify the stable Red Bar V2 decision path.
    """

    signal_id = str(signal.get("signal_id") or "").strip()
    confirmation = _timestamp(
        signal.get("confirmation_timestamp")
        or signal.get("confirmed_at")
        or signal.get("signal_timestamp")
    )
    payload = dict(reference or {})
    if not payload:
        return RedBarV2ReferenceReadiness(
            signal_id=signal_id,
            status="MISSING",
            reference_type=None,
            reference_timestamp=None,
            reference_high=None,
            reference_low=None,
            reference_midpoint=None,
            data_quality=None,
            reason_code="REFERENCE_NOT_FOUND",
            reason="No NEXT_RED_CANDLE reference was found for the confirmed signal.",
        )

    reference_type = str(payload.get("reference_type") or "").strip().upper()
    timestamp = _timestamp(payload.get("reference_timestamp") or payload.get("timestamp"))
    high = _number(payload.get("reference_high") if "reference_high" in payload else payload.get("high"))
    low = _number(payload.get("reference_low") if "reference_low" in payload else payload.get("low"))
    midpoint = _number(
        payload.get("reference_midpoint")
        if "reference_midpoint" in payload
        else payload.get("midpoint")
    )
    quality = str(payload.get("data_quality") or "").strip().upper()

    def result(status: str, code: str, reason: str) -> RedBarV2ReferenceReadiness:
        return RedBarV2ReferenceReadiness(
            signal_id=signal_id,
            status=status,
            reference_type=reference_type or None,
            reference_timestamp=timestamp.isoformat() if timestamp else None,
            reference_high=high,
            reference_low=low,
            reference_midpoint=midpoint,
            data_quality=quality or None,
            reason_code=code,
            reason=reason,
        )

    if reference_type != RED_BAR_V2_REFERENCE_TYPE:
        return result(
            "FAILED",
            "REFERENCE_TYPE_MISMATCH",
            f"Expected {RED_BAR_V2_REFERENCE_TYPE}; received {reference_type or 'MISSING'}.",
        )
    if timestamp is None:
        return result("MISSING", "REFERENCE_TIMESTAMP_INVALID", "Reference timestamp is missing or invalid.")
    if confirmation is None:
        return result("FAILED", "SIGNAL_TIMESTAMP_INVALID", "Signal confirmation timestamp is missing or invalid.")
    if timestamp > confirmation:
        return result(
            "FAILED",
            "REFERENCE_AFTER_CONFIRMATION",
            "Reference timestamp is later than the signal confirmation timestamp.",
        )
    if high is None:
        return result("MISSING", "REFERENCE_HIGH_INVALID", "Reference high is missing or non-finite.")
    if low is None:
        return result("MISSING", "REFERENCE_LOW_INVALID", "Reference low is missing or non-finite.")
    if high < low:
        return result("FAILED", "REFERENCE_RANGE_INVALID", "Reference high is below reference low.")
    if midpoint is None:
        return result("MISSING", "REFERENCE_MIDPOINT_INVALID", "Reference midpoint is missing or non-finite.")
    if not low <= midpoint <= high:
        return result(
            "FAILED",
            "REFERENCE_MIDPOINT_OUTSIDE_RANGE",
            "Reference midpoint is outside the reference high/low range.",
        )
    if quality != "VALID":
        return result(
            "FAILED",
            "REFERENCE_DATA_QUALITY_INVALID",
            f"Reference data quality must be VALID; received {quality or 'MISSING'}.",
        )

    return RedBarV2ReferenceReadiness(
        signal_id=signal_id,
        status="READY",
        reference_type=reference_type,
        reference_timestamp=timestamp.isoformat(),
        reference_high=high,
        reference_low=low,
        reference_midpoint=midpoint,
        data_quality=quality,
        reason_code=None,
        reason="NEXT_RED_CANDLE reference is complete, valid and point-in-time safe.",
    )


__all__ = [
    "RED_BAR_V2_REFERENCE_TYPE",
    "REFERENCE_POLICY_VERSION",
    "RedBarV2ReferenceReadiness",
    "assess_red_bar_v2_reference_readiness",
]
