from __future__ import annotations

from red_bar_lab.domain.red_bar_v2 import AdmissionOutcome, Direction, RedBarV2Decision

from .event_access import event_bool, event_conditions, event_datetime, event_text
from .models import RedBarV2ParityResult


def _value(value: object) -> object:
    return getattr(value, "value", value)


def compare_legacy_to_canonical(
    *,
    legacy_event: object | None,
    canonical_decision: RedBarV2Decision,
    legacy_timeframe: str | None = None,
) -> RedBarV2ParityResult:
    """Compare the real nested ReplayEvent contract without affecting execution."""
    legacy_direction = event_text(legacy_event, "direction")
    legacy_option_side = event_text(legacy_event, "option_side")
    legacy_entry_type = event_text(legacy_event, "entry_type")
    legacy_strength = event_text(legacy_event, "trend_strength")
    legacy_code = event_text(legacy_event, "admission_code")
    legacy_allowed = event_bool(legacy_event, "candidate_allowed")

    mismatches: list[str] = []

    def compare(name: str, legacy: object, canonical: object) -> None:
        if legacy != _value(canonical):
            mismatches.append(name)

    compare("direction", legacy_direction, canonical_decision.direction)
    compare("option_side", legacy_option_side, canonical_decision.option_side)
    compare("entry_type", legacy_entry_type, canonical_decision.entry_type)
    compare("trend_strength", legacy_strength, canonical_decision.trend_strength)
    compare(
        "admission_outcome",
        legacy_allowed,
        canonical_decision.admission_outcome is AdmissionOutcome.ALLOWED,
    )
    if legacy_code is not None:
        compare("admission_code", legacy_code, canonical_decision.admission_code)
    if legacy_timeframe is not None:
        compare("timeframe", legacy_timeframe, canonical_decision.evaluation_timeframe)

    legacy_reference_timestamp = event_datetime(legacy_event, "reference_timestamp")
    canonical_reference_timestamp = (
        canonical_decision.reference.timestamp if canonical_decision.reference is not None else None
    )
    if legacy_reference_timestamp != canonical_reference_timestamp:
        mismatches.append("reference_timestamp")

    legacy_context_timestamp = event_datetime(legacy_event, "context_timestamp")
    if legacy_context_timestamp != canonical_decision.evaluation_timestamp:
        mismatches.append("evaluation_timestamp")

    conditions = event_conditions(legacy_event)
    direction = canonical_decision.direction
    if direction is Direction.BULLISH:
        expected = {
            "rsi_aligned": canonical_decision.rsi.bullish_aligned if canonical_decision.rsi else None,
            "vwap_aligned": canonical_decision.futures_vwap.bullish_aligned if canonical_decision.futures_vwap else None,
            "midpoint_aligned": canonical_decision.midpoint.bullish_aligned if canonical_decision.midpoint else None,
        }
    elif direction is Direction.BEARISH:
        expected = {
            "rsi_aligned": canonical_decision.rsi.bearish_aligned if canonical_decision.rsi else None,
            "vwap_aligned": canonical_decision.futures_vwap.bearish_aligned if canonical_decision.futures_vwap else None,
            "midpoint_aligned": canonical_decision.midpoint.bearish_aligned if canonical_decision.midpoint else None,
        }
    else:
        expected = {"rsi_aligned": None, "vwap_aligned": None, "midpoint_aligned": None}

    for name, canonical_value in expected.items():
        legacy_value = conditions.get(name)
        if canonical_value is not None:
            if not isinstance(legacy_value, bool) or legacy_value != canonical_value:
                mismatches.append(name)

    return RedBarV2ParityResult(
        matches=not mismatches,
        mismatches=tuple(mismatches),
        legacy_direction=legacy_direction,
        canonical_direction=canonical_decision.direction,
        legacy_option_side=legacy_option_side,
        canonical_option_side=canonical_decision.option_side,
        legacy_allowed=legacy_allowed,
        canonical_allowed=canonical_decision.admission_outcome is AdmissionOutcome.ALLOWED,
        legacy_entry_type=legacy_entry_type,
        canonical_entry_type=canonical_decision.entry_type,
        legacy_timeframe=legacy_timeframe,
        canonical_timeframe=canonical_decision.evaluation_timeframe,
        legacy_trend_strength=legacy_strength,
        canonical_trend_strength=canonical_decision.trend_strength,
        legacy_admission_code=legacy_code,
        canonical_admission_code=canonical_decision.admission_code,
    )
