from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from red_bar_lab.domain.red_bar_v2 import (
    AdmissionOutcome,
    ContextStatus,
    Direction,
    EntryType,
    FuturesVwapEvidence,
    MarketTimestampEvidence,
    MidpointEvidence,
    OptionSide,
    RedBarV2Decision,
    RedBarV2InputReadiness,
    RedBarV2Reference,
    RedBarV2Section1Outcome,
    RedBarV2State,
    RsiEvidence,
    TrendStrength,
)

from .exceptions import LegacyMappingError
from .models import LegacyV2DecisionEvidence, LegacyV2MarketMetadata


def _legacy_value(value: object) -> object:
    return getattr(value, "value", value)


def _attribute(source: object | None, name: str, default: object = None) -> object:
    if source is None:
        return default
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _text_attribute(source: object | None, name: str) -> str | None:
    value = _attribute(source, name)
    value = _legacy_value(value)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LegacyMappingError(f"legacy {name} must be a non-empty string when present")
    return value


def _bool_attribute(source: object | None, name: str) -> bool | None:
    value = _attribute(source, name)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise LegacyMappingError(f"legacy {name} must be a bool when present")
    return value


def _build_reference_from_metadata(metadata: LegacyV2MarketMetadata) -> RedBarV2Reference | None:
    values = (
        metadata.reference_id,
        metadata.reference_timestamp,
        metadata.reference_high,
        metadata.reference_low,
        metadata.reference_midpoint,
        metadata.reference_source,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise LegacyMappingError("legacy reference metadata is incomplete")
    assert metadata.reference_id is not None
    assert metadata.reference_timestamp is not None
    assert metadata.reference_high is not None
    assert metadata.reference_low is not None
    assert metadata.reference_midpoint is not None
    assert metadata.reference_source is not None
    return RedBarV2Reference(
        reference_id=metadata.reference_id,
        trading_date=metadata.trading_date,
        timestamp=metadata.reference_timestamp,
        high=metadata.reference_high,
        low=metadata.reference_low,
        midpoint=metadata.reference_midpoint,
        source=metadata.reference_source,
    )


def build_canonical_input_readiness(
    *,
    replay: object | None,
    health: object | None,
    market_metadata: LegacyV2MarketMetadata,
) -> RedBarV2InputReadiness:
    """Map existing replay and health metadata to canonical Section 1.

    The function performs no market-data queries and does not recalculate the
    strategy. ``replay`` and ``health`` are accepted as the authoritative source
    objects for the integration boundary; event-time values are supplied through
    ``market_metadata`` so mapping remains deterministic and testable.
    """
    del replay, health
    reference = _build_reference_from_metadata(market_metadata)
    timestamps = MarketTimestampEvidence(
        latest_index_1m=market_metadata.latest_index_1m,
        latest_index_5m=market_metadata.latest_index_5m,
        latest_futures_1m=market_metadata.latest_futures_1m,
        latest_futures_5m=market_metadata.latest_futures_5m,
        evaluated_at=market_metadata.evaluated_at,
        context_status=market_metadata.context_status,
        maximum_age_seconds=market_metadata.maximum_age_seconds,
        reason=market_metadata.reason,
    )

    if reference is None:
        outcome = RedBarV2Section1Outcome.REFERENCE_WAITING
    elif market_metadata.context_status is ContextStatus.STALE:
        outcome = RedBarV2Section1Outcome.CANDLES_STALE
    elif market_metadata.context_status is ContextStatus.MISALIGNED:
        outcome = RedBarV2Section1Outcome.SESSION_MISALIGNED
    elif market_metadata.context_status is ContextStatus.UNAVAILABLE:
        outcome = RedBarV2Section1Outcome.INPUTS_NOT_READY
    elif not market_metadata.futures_instrument_key or not market_metadata.futures_volume_available:
        outcome = RedBarV2Section1Outcome.FUTURES_NOT_READY
    elif not market_metadata.futures_vwap_available:
        outcome = RedBarV2Section1Outcome.VWAP_SOURCE_NOT_READY
    else:
        outcome = RedBarV2Section1Outcome.REFERENCE_READY

    return RedBarV2InputReadiness(
        strategy_id="RED_BAR_V2",
        strategy_version=market_metadata.strategy_version,
        trading_date=market_metadata.trading_date,
        outcome=outcome,
        reference=reference,
        timestamps=timestamps,
        futures_instrument_key=market_metadata.futures_instrument_key,
        futures_expiry=market_metadata.futures_expiry,
        futures_volume_available=market_metadata.futures_volume_available,
        futures_vwap_available=market_metadata.futures_vwap_available,
        source_name=market_metadata.source_name,
        source_version=market_metadata.source_version,
        reason_code=market_metadata.reason_code,
        reason=market_metadata.reason,
    )


def _canonical_reference(evidence: LegacyV2DecisionEvidence, trading_date: date) -> RedBarV2Reference:
    return RedBarV2Reference(
        reference_id=evidence.reference_id,
        trading_date=trading_date,
        timestamp=evidence.reference_timestamp,
        high=evidence.reference_high,
        low=evidence.reference_low,
        midpoint=evidence.reference_midpoint,
        source=evidence.reference_source,
    )


def _map_entry_type(value: str | None) -> EntryType | None:
    if value is None:
        return None
    try:
        return EntryType(value)
    except ValueError as exc:
        raise LegacyMappingError(f"unsupported legacy entry_type: {value!r}") from exc


def _map_direction(value: str | None) -> Direction | None:
    if value is None:
        return None
    try:
        return Direction(value)
    except ValueError as exc:
        raise LegacyMappingError(f"unsupported legacy direction: {value!r}") from exc


def _map_option_side(value: str | None) -> OptionSide | None:
    if value is None:
        return None
    try:
        return OptionSide(value)
    except ValueError as exc:
        raise LegacyMappingError(f"unsupported legacy option_side: {value!r}") from exc


def _map_strength(value: str | None) -> TrendStrength | None:
    if value is None:
        return None
    try:
        return TrendStrength(value)
    except ValueError as exc:
        raise LegacyMappingError(f"unsupported legacy trend_strength: {value!r}") from exc


def _state_for(
    *,
    admitted: bool,
    direction: Direction | None,
    strength: TrendStrength | None,
) -> RedBarV2State:
    if not admitted or direction is None or strength is None:
        return RedBarV2State.SIGNAL_WAITING
    if direction is Direction.BULLISH:
        return (
            RedBarV2State.CONFIRMED_BULLISH
            if strength is TrendStrength.CONFIRMED
            else RedBarV2State.PROVISIONAL_BULLISH
        )
    return (
        RedBarV2State.CONFIRMED_BEARISH
        if strength is TrendStrength.CONFIRMED
        else RedBarV2State.PROVISIONAL_BEARISH
    )


def build_canonical_decision(
    *,
    replay_event: object | None,
    readiness: RedBarV2InputReadiness,
    evidence: LegacyV2DecisionEvidence | None,
) -> RedBarV2Decision:
    """Map one authoritative legacy admission event to canonical Section 2."""
    allowed = _bool_attribute(replay_event, "candidate_allowed")
    direction = _map_direction(_text_attribute(replay_event, "direction"))
    option_side = _map_option_side(_text_attribute(replay_event, "option_side"))
    entry_type = _map_entry_type(_text_attribute(replay_event, "entry_type"))
    strength = _map_strength(_text_attribute(replay_event, "trend_strength"))
    admission_code = _text_attribute(replay_event, "admission_code") or "WAITING"
    admission_reason = _text_attribute(replay_event, "admission_reason") or "No legacy admission event"

    if allowed is True:
        admission_outcome = AdmissionOutcome.ALLOWED
    elif allowed is False:
        admission_outcome = AdmissionOutcome.REJECTED
    else:
        admission_outcome = AdmissionOutcome.WAITING

    if admission_outcome is AdmissionOutcome.ALLOWED and evidence is None:
        raise LegacyMappingError("allowed legacy decision requires complete event-time evidence")

    if evidence is None:
        evaluation_timestamp = readiness.timestamps.evaluated_at
        evaluation_timeframe = "1m"
        reference = readiness.reference
        rsi = None
        futures_vwap = None
        midpoint = None
    else:
        evaluation_timestamp = evidence.evaluation_timestamp
        evaluation_timeframe = evidence.evaluation_timeframe
        reference = _canonical_reference(evidence, readiness.trading_date)
        rsi = RsiEvidence(
            value=evidence.rsi_value,
            bullish_threshold=evidence.bullish_rsi_threshold,
            bearish_threshold=evidence.bearish_rsi_threshold,
            bullish_aligned=evidence.rsi_value > evidence.bullish_rsi_threshold,
            bearish_aligned=evidence.rsi_value < evidence.bearish_rsi_threshold,
        )
        futures_vwap = FuturesVwapEvidence(
            instrument_key=evidence.instrument_key,
            comparison_price=evidence.futures_comparison_price,
            vwap=evidence.futures_vwap,
            volume=evidence.futures_volume,
            bullish_aligned=evidence.futures_comparison_price > evidence.futures_vwap,
            bearish_aligned=evidence.futures_comparison_price < evidence.futures_vwap,
            fresh=evidence.futures_fresh,
        )
        midpoint = MidpointEvidence(
            index_close=evidence.index_close,
            midpoint=evidence.reference_midpoint,
            bullish_aligned=evidence.index_close > evidence.reference_midpoint,
            bearish_aligned=evidence.index_close < evidence.reference_midpoint,
        )

    admitted = admission_outcome is AdmissionOutcome.ALLOWED
    current_state = _state_for(admitted=admitted, direction=direction, strength=strength)
    previous_state = (
        RedBarV2State.REFERENCE_READY
        if readiness.outcome is RedBarV2Section1Outcome.REFERENCE_READY
        else RedBarV2State.REFERENCE_NOT_READY
    )

    return RedBarV2Decision(
        strategy_id="RED_BAR_V2",
        strategy_version=readiness.strategy_version,
        evaluation_timestamp=evaluation_timestamp,
        evaluation_timeframe=evaluation_timeframe,
        entry_type=entry_type,
        previous_state=previous_state,
        current_state=current_state,
        direction=direction,
        option_side=option_side,
        trend_strength=strength,
        reference=reference,
        rsi=rsi,
        futures_vwap=futures_vwap,
        midpoint=midpoint,
        context_status=readiness.timestamps.context_status,
        admission_outcome=admission_outcome,
        admission_code=admission_code,
        admission_reason=admission_reason,
    )
