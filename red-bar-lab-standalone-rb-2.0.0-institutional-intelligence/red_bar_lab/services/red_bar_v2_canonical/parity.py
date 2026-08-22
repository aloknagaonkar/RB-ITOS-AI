from __future__ import annotations

from typing import Mapping

from red_bar_lab.domain.red_bar_v2 import AdmissionOutcome, Direction, OptionSide, RedBarV2Decision

from .models import RedBarV2ParityResult


def _value(value: object) -> object:
    return getattr(value, "value", value)


def _field(source: object | None, name: str, default: object = None) -> object:
    if source is None:
        return default
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _text(source: object | None, name: str) -> str | None:
    value = _value(_field(source, name))
    return value if isinstance(value, str) else None


def compare_legacy_to_canonical(
    *,
    legacy_event: object | None,
    canonical_decision: RedBarV2Decision,
    legacy_timeframe: str | None = None,
) -> RedBarV2ParityResult:
    """Compare outcomes without changing either execution path."""
    legacy_direction = _text(legacy_event, "direction")
    legacy_option_side = _text(legacy_event, "option_side")
    legacy_entry_type = _text(legacy_event, "entry_type")
    legacy_strength = _text(legacy_event, "trend_strength")
    legacy_code = _text(legacy_event, "admission_code")
    raw_allowed = _field(legacy_event, "candidate_allowed")
    legacy_allowed = raw_allowed if isinstance(raw_allowed, bool) else None

    mismatches: list[str] = []

    def compare(name: str, legacy: object, canonical: object) -> None:
        canonical_value = _value(canonical)
        if legacy != canonical_value:
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

    legacy_reference_timestamp = _text(legacy_event, "reference_timestamp")
    if legacy_reference_timestamp is not None and canonical_decision.reference is not None:
        if legacy_reference_timestamp != canonical_decision.reference.timestamp.isoformat():
            mismatches.append("reference_timestamp")

    legacy_context_timestamp = _text(legacy_event, "context_timestamp")
    if legacy_context_timestamp is not None:
        if legacy_context_timestamp != canonical_decision.evaluation_timestamp.isoformat():
            mismatches.append("evaluation_timestamp")

    conditions = _field(legacy_event, "conditions")
    if isinstance(conditions, Mapping):
        direction = canonical_decision.direction
        expected_rsi = None
        expected_vwap = None
        expected_midpoint = None
        if direction is Direction.BULLISH:
            expected_rsi = canonical_decision.rsi.bullish_aligned if canonical_decision.rsi else None
            expected_vwap = (
                canonical_decision.futures_vwap.bullish_aligned
                if canonical_decision.futures_vwap
                else None
            )
            expected_midpoint = (
                canonical_decision.midpoint.bullish_aligned
                if canonical_decision.midpoint
                else None
            )
        elif direction is Direction.BEARISH:
            expected_rsi = canonical_decision.rsi.bearish_aligned if canonical_decision.rsi else None
            expected_vwap = (
                canonical_decision.futures_vwap.bearish_aligned
                if canonical_decision.futures_vwap
                else None
            )
            expected_midpoint = (
                canonical_decision.midpoint.bearish_aligned
                if canonical_decision.midpoint
                else None
            )
        for name, expected in (
            ("rsi_aligned", expected_rsi),
            ("vwap_aligned", expected_vwap),
            ("midpoint_aligned", expected_midpoint),
        ):
            legacy_value = conditions.get(name)
            if isinstance(legacy_value, bool) and expected is not None and legacy_value != expected:
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
