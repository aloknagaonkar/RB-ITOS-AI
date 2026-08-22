from __future__ import annotations

from datetime import date, datetime
import json
from typing import Mapping, TypeVar

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
    RedBarV2SignalBundle,
    RedBarV2State,
    RsiEvidence,
    TrendStrength,
    red_bar_v2_bundle_from_dict,
    red_bar_v2_bundle_to_dict,
    red_bar_v2_resolution_to_dict,
)

from .models import RedBarV2ParityResult
from .persistence_identity import canonical_json
from .persistence_models import (
    CanonicalBundleEventType,
    CanonicalBundleLifecycleEvent,
    CanonicalPersistenceCorruptionError,
    PersistedRedBarV2Resolution,
)

SUPPORTED_RESOLUTION_SCHEMA_VERSIONS = frozenset({"1.0"})
_E = TypeVar("_E")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CanonicalPersistenceCorruptionError(f"{name} must be a mapping")
    return value


def _text(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise CanonicalPersistenceCorruptionError(f"{name} must be a non-empty string")
    return value


def _bool(payload: Mapping[str, object], name: str) -> bool:
    value = payload.get(name)
    if not isinstance(value, bool):
        raise CanonicalPersistenceCorruptionError(f"{name} must be a bool")
    return value


def _number(payload: Mapping[str, object], name: str) -> float:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanonicalPersistenceCorruptionError(f"{name} must be numeric")
    return float(value)


def _datetime(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise CanonicalPersistenceCorruptionError(f"{name} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanonicalPersistenceCorruptionError(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CanonicalPersistenceCorruptionError(f"{name} must preserve timezone")
    return parsed


def _date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise CanonicalPersistenceCorruptionError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CanonicalPersistenceCorruptionError(f"invalid {name}") from exc


def _enum(enum_type: type[_E], value: object, name: str) -> _E:
    if not isinstance(value, str):
        raise CanonicalPersistenceCorruptionError(f"{name} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise CanonicalPersistenceCorruptionError(f"invalid {name}: {value!r}") from exc


def _optional_datetime(value: object, name: str) -> datetime | None:
    return None if value is None else _datetime(value, name)


def _reference(payload: Mapping[str, object]) -> RedBarV2Reference:
    return RedBarV2Reference(
        reference_id=_text(payload, "reference_id"),
        trading_date=_date(payload.get("trading_date"), "reference.trading_date"),
        timestamp=_datetime(payload.get("timestamp"), "reference.timestamp"),
        high=_number(payload, "high"),
        low=_number(payload, "low"),
        midpoint=_number(payload, "midpoint"),
        source=_text(payload, "source"),
    )


def _readiness(payload: Mapping[str, object]) -> RedBarV2InputReadiness:
    timestamps = _mapping(payload.get("timestamps"), "section_1.timestamps")
    reference_payload = payload.get("reference")
    futures_expiry = payload.get("futures_expiry")
    return RedBarV2InputReadiness(
        strategy_id=_text(payload, "strategy_id"),
        strategy_version=_text(payload, "strategy_version"),
        trading_date=_date(payload.get("trading_date"), "section_1.trading_date"),
        outcome=_enum(RedBarV2Section1Outcome, payload.get("outcome"), "section_1.outcome"),
        reference=None if reference_payload is None else _reference(_mapping(reference_payload, "section_1.reference")),
        timestamps=MarketTimestampEvidence(
            latest_index_1m=_optional_datetime(timestamps.get("latest_index_1m"), "latest_index_1m"),
            latest_index_5m=_optional_datetime(timestamps.get("latest_index_5m"), "latest_index_5m"),
            latest_futures_1m=_optional_datetime(timestamps.get("latest_futures_1m"), "latest_futures_1m"),
            latest_futures_5m=_optional_datetime(timestamps.get("latest_futures_5m"), "latest_futures_5m"),
            evaluated_at=_datetime(timestamps.get("evaluated_at"), "evaluated_at"),
            context_status=_enum(ContextStatus, timestamps.get("context_status"), "context_status"),
            maximum_age_seconds=int(_number(timestamps, "maximum_age_seconds")),
            reason=_text(timestamps, "reason"),
        ),
        futures_instrument_key=None if payload.get("futures_instrument_key") is None else _text(payload, "futures_instrument_key"),
        futures_expiry=None if futures_expiry is None else _date(futures_expiry, "futures_expiry"),
        futures_volume_available=_bool(payload, "futures_volume_available"),
        futures_vwap_available=_bool(payload, "futures_vwap_available"),
        source_name=_text(payload, "source_name"),
        source_version=_text(payload, "source_version"),
        reason_code=_text(payload, "reason_code"),
        reason=_text(payload, "reason"),
    )


def _decision(payload: Mapping[str, object]) -> RedBarV2Decision:
    reference_payload = payload.get("reference")
    rsi_payload = payload.get("rsi")
    futures_payload = payload.get("futures_vwap")
    midpoint_payload = payload.get("midpoint")
    rsi = None
    if rsi_payload is not None:
        item = _mapping(rsi_payload, "section_2.rsi")
        rsi = RsiEvidence(
            value=_number(item, "value"),
            bullish_threshold=_number(item, "bullish_threshold"),
            bearish_threshold=_number(item, "bearish_threshold"),
            bullish_aligned=_bool(item, "bullish_aligned"),
            bearish_aligned=_bool(item, "bearish_aligned"),
        )
    futures = None
    if futures_payload is not None:
        item = _mapping(futures_payload, "section_2.futures_vwap")
        futures = FuturesVwapEvidence(
            instrument_key=_text(item, "instrument_key"),
            comparison_price=_number(item, "comparison_price"),
            vwap=_number(item, "vwap"),
            volume=_number(item, "volume"),
            bullish_aligned=_bool(item, "bullish_aligned"),
            bearish_aligned=_bool(item, "bearish_aligned"),
            fresh=_bool(item, "fresh"),
        )
    midpoint = None
    if midpoint_payload is not None:
        item = _mapping(midpoint_payload, "section_2.midpoint")
        midpoint = MidpointEvidence(
            index_close=_number(item, "index_close"),
            midpoint=_number(item, "midpoint"),
            bullish_aligned=_bool(item, "bullish_aligned"),
            bearish_aligned=_bool(item, "bearish_aligned"),
        )
    return RedBarV2Decision(
        strategy_id=_text(payload, "strategy_id"),
        strategy_version=_text(payload, "strategy_version"),
        evaluation_timestamp=_datetime(payload.get("evaluation_timestamp"), "evaluation_timestamp"),
        evaluation_timeframe=_text(payload, "evaluation_timeframe"),
        entry_type=None if payload.get("entry_type") is None else _enum(EntryType, payload.get("entry_type"), "entry_type"),
        previous_state=_enum(RedBarV2State, payload.get("previous_state"), "previous_state"),
        current_state=_enum(RedBarV2State, payload.get("current_state"), "current_state"),
        direction=None if payload.get("direction") is None else _enum(Direction, payload.get("direction"), "direction"),
        option_side=None if payload.get("option_side") is None else _enum(OptionSide, payload.get("option_side"), "option_side"),
        trend_strength=None if payload.get("trend_strength") is None else _enum(TrendStrength, payload.get("trend_strength"), "trend_strength"),
        reference=None if reference_payload is None else _reference(_mapping(reference_payload, "section_2.reference")),
        rsi=rsi,
        futures_vwap=futures,
        midpoint=midpoint,
        context_status=_enum(ContextStatus, payload.get("context_status"), "context_status"),
        admission_outcome=_enum(AdmissionOutcome, payload.get("admission_outcome"), "admission_outcome"),
        admission_code=_text(payload, "admission_code"),
        admission_reason=_text(payload, "admission_reason"),
    )


def _parity_to_dict(parity: RedBarV2ParityResult | None) -> dict[str, object] | None:
    if parity is None:
        return None
    return {
        "matches": parity.matches,
        "mismatches": list(parity.mismatches),
        "legacy_direction": parity.legacy_direction,
        "canonical_direction": parity.canonical_direction.value if parity.canonical_direction else None,
        "legacy_option_side": parity.legacy_option_side,
        "canonical_option_side": parity.canonical_option_side.value if parity.canonical_option_side else None,
        "legacy_allowed": parity.legacy_allowed,
        "canonical_allowed": parity.canonical_allowed,
        "legacy_entry_type": parity.legacy_entry_type,
        "canonical_entry_type": parity.canonical_entry_type.value if parity.canonical_entry_type else None,
        "legacy_timeframe": parity.legacy_timeframe,
        "canonical_timeframe": parity.canonical_timeframe,
        "legacy_trend_strength": parity.legacy_trend_strength,
        "canonical_trend_strength": parity.canonical_trend_strength.value if parity.canonical_trend_strength else None,
        "legacy_admission_code": parity.legacy_admission_code,
        "canonical_admission_code": parity.canonical_admission_code,
    }


def _parity(payload: Mapping[str, object] | None) -> RedBarV2ParityResult | None:
    if payload is None:
        return None
    mismatches = payload.get("mismatches")
    if not isinstance(mismatches, list) or not all(isinstance(item, str) for item in mismatches):
        raise CanonicalPersistenceCorruptionError("parity.mismatches must be a string list")
    return RedBarV2ParityResult(
        matches=_bool(payload, "matches"),
        mismatches=tuple(mismatches),
        legacy_direction=payload.get("legacy_direction") if isinstance(payload.get("legacy_direction"), str) else None,
        canonical_direction=None if payload.get("canonical_direction") is None else _enum(Direction, payload.get("canonical_direction"), "canonical_direction"),
        legacy_option_side=payload.get("legacy_option_side") if isinstance(payload.get("legacy_option_side"), str) else None,
        canonical_option_side=None if payload.get("canonical_option_side") is None else _enum(OptionSide, payload.get("canonical_option_side"), "canonical_option_side"),
        legacy_allowed=payload.get("legacy_allowed") if isinstance(payload.get("legacy_allowed"), bool) else None,
        canonical_allowed=_bool(payload, "canonical_allowed"),
        legacy_entry_type=payload.get("legacy_entry_type") if isinstance(payload.get("legacy_entry_type"), str) else None,
        canonical_entry_type=None if payload.get("canonical_entry_type") is None else _enum(EntryType, payload.get("canonical_entry_type"), "canonical_entry_type"),
        legacy_timeframe=payload.get("legacy_timeframe") if isinstance(payload.get("legacy_timeframe"), str) else None,
        canonical_timeframe=_text(payload, "canonical_timeframe"),
        legacy_trend_strength=payload.get("legacy_trend_strength") if isinstance(payload.get("legacy_trend_strength"), str) else None,
        canonical_trend_strength=None if payload.get("canonical_trend_strength") is None else _enum(TrendStrength, payload.get("canonical_trend_strength"), "canonical_trend_strength"),
        legacy_admission_code=payload.get("legacy_admission_code") if isinstance(payload.get("legacy_admission_code"), str) else None,
        canonical_admission_code=_text(payload, "canonical_admission_code"),
    )


def resolution_envelope_to_dict(envelope: PersistedRedBarV2Resolution) -> dict[str, object]:
    return {
        "schema_version": envelope.schema_version,
        "resolution_id": envelope.resolution_id,
        "instrument_key": envelope.instrument_key,
        "trading_date": envelope.trading_date.isoformat(),
        "source_replay_id": envelope.source_replay_id,
        "resolved_at": envelope.resolved_at.isoformat(),
        "section_1": red_bar_v2_resolution_to_dict(envelope.section_1),
        "section_2": red_bar_v2_resolution_to_dict(envelope.section_2),
        "section_3": None if envelope.section_3 is None else red_bar_v2_bundle_to_dict(envelope.section_3),
        "parity": _parity_to_dict(envelope.parity),
    }


def resolution_envelope_to_json(envelope: PersistedRedBarV2Resolution) -> str:
    return canonical_json(resolution_envelope_to_dict(envelope))


def resolution_envelope_from_json(payload_json: str) -> PersistedRedBarV2Resolution:
    try:
        raw = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CanonicalPersistenceCorruptionError("resolution payload is not valid JSON") from exc
    payload = _mapping(raw, "resolution")
    schema_version = _text(payload, "schema_version")
    if schema_version not in SUPPORTED_RESOLUTION_SCHEMA_VERSIONS:
        raise CanonicalPersistenceCorruptionError(f"unsupported resolution schema: {schema_version}")
    section_3_payload = payload.get("section_3")
    return PersistedRedBarV2Resolution(
        schema_version=schema_version,
        resolution_id=_text(payload, "resolution_id"),
        instrument_key=_text(payload, "instrument_key"),
        trading_date=_date(payload.get("trading_date"), "trading_date"),
        source_replay_id=_text(payload, "source_replay_id"),
        resolved_at=_datetime(payload.get("resolved_at"), "resolved_at"),
        section_1=_readiness(_mapping(payload.get("section_1"), "section_1")),
        section_2=_decision(_mapping(payload.get("section_2"), "section_2")),
        section_3=None if section_3_payload is None else red_bar_v2_bundle_from_dict(_mapping(section_3_payload, "section_3")),
        parity=_parity(None if payload.get("parity") is None else _mapping(payload.get("parity"), "parity")),
    )


def lifecycle_event_to_dict(event: CanonicalBundleLifecycleEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "bundle_id": event.bundle_id,
        "event_type": event.event_type.value,
        "event_timestamp": event.event_timestamp.isoformat(),
        "source": event.source,
        "reason_code": event.reason_code,
        "metadata": dict(event.metadata),
    }


def lifecycle_event_to_json(event: CanonicalBundleLifecycleEvent) -> str:
    return canonical_json(lifecycle_event_to_dict(event))


def lifecycle_event_from_json(payload_json: str) -> CanonicalBundleLifecycleEvent:
    try:
        raw = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CanonicalPersistenceCorruptionError("lifecycle payload is not valid JSON") from exc
    payload = _mapping(raw, "lifecycle_event")
    return CanonicalBundleLifecycleEvent(
        event_id=_text(payload, "event_id"),
        bundle_id=_text(payload, "bundle_id"),
        event_type=_enum(CanonicalBundleEventType, payload.get("event_type"), "event_type"),
        event_timestamp=_datetime(payload.get("event_timestamp"), "event_timestamp"),
        source=_text(payload, "source"),
        reason_code=_text(payload, "reason_code"),
        metadata=_mapping(payload.get("metadata"), "metadata"),
    )
