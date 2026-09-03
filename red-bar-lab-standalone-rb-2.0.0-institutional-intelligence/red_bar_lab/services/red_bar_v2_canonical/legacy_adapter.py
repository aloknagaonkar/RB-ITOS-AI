from __future__ import annotations

from datetime import date
from typing import Mapping

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

from .event_access import event_bool, event_text
from .exceptions import LegacyMappingError
from .models import LegacyV2DecisionEvidence, LegacyV2MarketMetadata


def _attribute(source: object | None, name: str, default: object = None) -> object:
    if source is None:
        return default
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _normalised_text(value: object) -> str | None:
    value = getattr(value, "value", value)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LegacyMappingError("authoritative source text values must be non-empty strings")
    return value


def _build_reference(
    metadata: LegacyV2MarketMetadata,
    *,
    replay_reference_timestamp: object,
    replay_reference_midpoint: object,
) -> RedBarV2Reference | None:
    if replay_reference_timestamp is None:
        return None
    if metadata.reference_timestamp != replay_reference_timestamp:
        raise LegacyMappingError("market metadata reference timestamp disagrees with replay")
    if replay_reference_midpoint is not None and metadata.reference_midpoint != replay_reference_midpoint:
        raise LegacyMappingError("market metadata reference midpoint disagrees with replay")
    values = (
        metadata.reference_id,
        metadata.reference_timestamp,
        metadata.reference_high,
        metadata.reference_low,
        metadata.reference_midpoint,
        metadata.reference_source,
    )
    if any(value is None for value in values):
        raise LegacyMappingError("authoritative reference metadata is incomplete")
    return RedBarV2Reference(
        reference_id=metadata.reference_id,  # type: ignore[arg-type]
        trading_date=metadata.trading_date,
        timestamp=metadata.reference_timestamp,  # type: ignore[arg-type]
        high=metadata.reference_high,  # type: ignore[arg-type]
        low=metadata.reference_low,  # type: ignore[arg-type]
        midpoint=metadata.reference_midpoint,  # type: ignore[arg-type]
        source=metadata.reference_source,  # type: ignore[arg-type]
    )


def build_canonical_input_readiness(
    *,
    replay: object,
    health: object,
    market_metadata: LegacyV2MarketMetadata,
) -> RedBarV2InputReadiness:
    """Assemble canonical readiness from the real replay and health contracts."""
    if replay is None or health is None:
        raise LegacyMappingError("authoritative replay and health objects are required")

    replay_instrument = _normalised_text(_attribute(replay, "instrument_key"))
    replay_trading_date = _normalised_text(_attribute(replay, "trading_date"))
    if replay_instrument != market_metadata.underlying_instrument_key:
        raise LegacyMappingError("underlying instrument metadata disagrees with replay")
    if replay_trading_date != market_metadata.trading_date.isoformat():
        raise LegacyMappingError("trading date metadata disagrees with replay")

    reference = _build_reference(
        market_metadata,
        replay_reference_timestamp=_attribute(replay, "reference_timestamp"),
        replay_reference_midpoint=_attribute(replay, "reference_midpoint"),
    )

    health_status = _normalised_text(_attribute(health, "status")) or "UNAVAILABLE"
    health_price_key = _normalised_text(_attribute(health, "price_source_instrument"))
    health_rsi_key = _normalised_text(_attribute(health, "rsi_source_instrument"))
    health_vwap_key = _normalised_text(_attribute(health, "vwap_source_instrument"))
    if health_price_key != market_metadata.underlying_instrument_key:
        raise LegacyMappingError("price source instrument metadata disagrees with health")
    if health_rsi_key != market_metadata.underlying_instrument_key:
        raise LegacyMappingError("RSI source instrument metadata disagrees with health")
    if health_vwap_key != market_metadata.futures_instrument_key:
        raise LegacyMappingError("VWAP source instrument metadata disagrees with health")

    context_status = market_metadata.context_status
    if health_status != "READY" and context_status is ContextStatus.FRESH:
        context_status = ContextStatus.UNAVAILABLE

    timestamps = MarketTimestampEvidence(
        latest_index_1m=market_metadata.latest_index_1m,
        latest_index_5m=market_metadata.latest_index_5m,
        latest_futures_1m=market_metadata.latest_futures_1m,
        latest_futures_5m=market_metadata.latest_futures_5m,
        evaluated_at=market_metadata.evaluated_at,
        context_status=context_status,
        maximum_age_seconds=market_metadata.maximum_age_seconds,
        reason=market_metadata.reason,
    )

    if reference is None:
        outcome = RedBarV2Section1Outcome.REFERENCE_WAITING
    elif context_status is ContextStatus.STALE:
        outcome = RedBarV2Section1Outcome.CANDLES_STALE
    elif context_status is ContextStatus.MISALIGNED:
        outcome = RedBarV2Section1Outcome.SESSION_MISALIGNED
    elif context_status is ContextStatus.UNAVAILABLE:
        outcome = RedBarV2Section1Outcome.VWAP_SOURCE_NOT_READY if health_status != "READY" else RedBarV2Section1Outcome.INPUTS_NOT_READY
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
        futures_vwap_available=market_metadata.futures_vwap_available and health_status == "READY",
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


def _enum(enum_type, value: str | None, field: str):
    if value is None:
        return None
    try:
        return enum_type(value)
    except ValueError as exc:
        raise LegacyMappingError(f"unsupported legacy {field}: {value!r}") from exc


def _state_for(admitted: bool, direction: Direction | None, strength: TrendStrength | None) -> RedBarV2State:
    if not admitted or direction is None or strength is None:
        return RedBarV2State.SIGNAL_WAITING
    if direction is Direction.BULLISH:
        return RedBarV2State.CONFIRMED_BULLISH if strength is TrendStrength.CONFIRMED else RedBarV2State.PROVISIONAL_BULLISH
    return RedBarV2State.CONFIRMED_BEARISH if strength is TrendStrength.CONFIRMED else RedBarV2State.PROVISIONAL_BEARISH


def build_canonical_decision(
    *,
    replay_event: object | None,
    readiness: RedBarV2InputReadiness,
    evidence: LegacyV2DecisionEvidence | None,
) -> RedBarV2Decision:
    """Map the real nested ReplayEvent contract to canonical Section 2."""
    allowed = event_bool(replay_event, "candidate_allowed")
    direction = _enum(Direction, event_text(replay_event, "direction"), "direction")
    option_side = _enum(OptionSide, event_text(replay_event, "option_side"), "option_side")
    entry_type = _enum(EntryType, event_text(replay_event, "entry_type"), "entry_type")
    strength = _enum(TrendStrength, event_text(replay_event, "trend_strength"), "trend_strength")
    admission_code = event_text(replay_event, "admission_code") or "WAITING"
    admission_reason = event_text(replay_event, "admission_reason") or "No legacy admission event"

    admission_outcome = AdmissionOutcome.ALLOWED if allowed is True else AdmissionOutcome.REJECTED if allowed is False else AdmissionOutcome.WAITING
    if admission_outcome is AdmissionOutcome.ALLOWED and evidence is None:
        raise LegacyMappingError("allowed legacy decision requires complete event-time evidence")

    if evidence is None:
        evaluation_timestamp = readiness.timestamps.evaluated_at
        evaluation_timeframe = "1m"
        reference = readiness.reference
        rsi = futures_vwap = midpoint = None
    else:
        if evidence.futures_instrument_key != readiness.futures_instrument_key:
            raise LegacyMappingError("decision futures instrument disagrees with readiness")
        evaluation_timestamp = evidence.evaluation_timestamp
        evaluation_timeframe = evidence.evaluation_timeframe
        reference = _canonical_reference(evidence, readiness.trading_date)
        # No reading means no evidence block. `RsiEvidence` promises a finite
        # value in [0, 100] with truthful alignment flags, so fabricating one
        # during the Wilder RSI(14) warm-up would either break that promise or
        # assert an alignment nobody measured. `RedBarV2Decision.rsi` is
        # already optional for exactly this case.
        rsi = None
        if evidence.rsi_value is not None:
            rsi = RsiEvidence(
                value=evidence.rsi_value,
                bullish_threshold=evidence.bullish_rsi_threshold,
                bearish_threshold=evidence.bearish_rsi_threshold,
                bullish_aligned=evidence.rsi_value > evidence.bullish_rsi_threshold,
                bearish_aligned=evidence.rsi_value < evidence.bearish_rsi_threshold,
            )
        futures_vwap = FuturesVwapEvidence(
            instrument_key=evidence.futures_instrument_key,
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
    previous_state = RedBarV2State.REFERENCE_READY if readiness.outcome is RedBarV2Section1Outcome.REFERENCE_READY else RedBarV2State.REFERENCE_NOT_READY
    return RedBarV2Decision(
        strategy_id="RED_BAR_V2",
        strategy_version=readiness.strategy_version,
        evaluation_timestamp=evaluation_timestamp,
        evaluation_timeframe=evaluation_timeframe,
        entry_type=entry_type,
        previous_state=previous_state,
        current_state=_state_for(admitted, direction, strength),
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
