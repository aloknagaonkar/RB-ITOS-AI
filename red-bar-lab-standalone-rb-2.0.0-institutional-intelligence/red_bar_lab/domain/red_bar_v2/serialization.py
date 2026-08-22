from __future__ import annotations

from datetime import date, datetime
from typing import Mapping, TypeVar

from .enums import (
    AdmissionOutcome,
    BundleLifecycleStatus,
    ContextStatus,
    Direction,
    EntryType,
    OptionSide,
    RedBarV2State,
    TrendStrength,
)
from .exceptions import DomainValidationError, UnsupportedSchemaVersionError
from .models import (
    FuturesVwapEvidence,
    MidpointEvidence,
    RedBarV2Decision,
    RedBarV2InputReadiness,
    RedBarV2Reference,
    RedBarV2SignalBundle,
    RsiEvidence,
)

SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})
_EnumT = TypeVar("_EnumT")


def _required(payload: Mapping[str, object], name: str) -> object:
    if name not in payload:
        raise DomainValidationError(f"missing mandatory field: {name}")
    return payload[name]


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DomainValidationError(f"{name} must be a mapping")
    return value


def _text(payload: Mapping[str, object], name: str) -> str:
    value = _required(payload, name)
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{name} must be a non-empty string")
    return value


def _bool(payload: Mapping[str, object], name: str) -> bool:
    value = _required(payload, name)
    if not isinstance(value, bool):
        raise DomainValidationError(f"{name} must be a bool")
    return value


def _number(payload: Mapping[str, object], name: str) -> object:
    value = _required(payload, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainValidationError(f"{name} must be a number")
    return value


def _date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise DomainValidationError(f"{name} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DomainValidationError(f"invalid {name}: {value!r}") from exc


def _datetime(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise DomainValidationError(f"{name} must be an ISO datetime string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DomainValidationError(f"invalid {name}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DomainValidationError(f"{name} must preserve timezone information")
    return parsed


def _enum(enum_type: type[_EnumT], value: object, name: str) -> _EnumT:
    if not isinstance(value, str):
        raise DomainValidationError(f"{name} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise DomainValidationError(f"invalid {name}: {value!r}") from exc


def _reference_to_dict(reference: RedBarV2Reference) -> dict[str, object]:
    return {
        "reference_id": reference.reference_id,
        "trading_date": reference.trading_date.isoformat(),
        "timestamp": reference.timestamp.isoformat(),
        "high": reference.high,
        "low": reference.low,
        "midpoint": reference.midpoint,
        "source": reference.source,
    }


def _reference_from_dict(payload: Mapping[str, object]) -> RedBarV2Reference:
    return RedBarV2Reference(
        reference_id=_text(payload, "reference_id"),
        trading_date=_date(_required(payload, "trading_date"), "reference.trading_date"),
        timestamp=_datetime(_required(payload, "timestamp"), "reference.timestamp"),
        high=_number(payload, "high"),
        low=_number(payload, "low"),
        midpoint=_number(payload, "midpoint"),
        source=_text(payload, "source"),
    )


def red_bar_v2_resolution_to_dict(
    resolution: RedBarV2InputReadiness | RedBarV2Decision,
) -> dict[str, object]:
    """Serialize a canonical Section 1 or Section 2 resolution."""
    if isinstance(resolution, RedBarV2InputReadiness):
        timestamps = resolution.timestamps
        return {
            "kind": "INPUT_READINESS",
            "strategy_id": resolution.strategy_id,
            "strategy_version": resolution.strategy_version,
            "trading_date": resolution.trading_date.isoformat(),
            "outcome": resolution.outcome.value,
            "reference": _reference_to_dict(resolution.reference) if resolution.reference else None,
            "timestamps": {
                "latest_index_1m": timestamps.latest_index_1m.isoformat() if timestamps.latest_index_1m else None,
                "latest_index_5m": timestamps.latest_index_5m.isoformat() if timestamps.latest_index_5m else None,
                "latest_futures_1m": timestamps.latest_futures_1m.isoformat() if timestamps.latest_futures_1m else None,
                "latest_futures_5m": timestamps.latest_futures_5m.isoformat() if timestamps.latest_futures_5m else None,
                "evaluated_at": timestamps.evaluated_at.isoformat(),
                "context_status": timestamps.context_status.value,
                "maximum_age_seconds": timestamps.maximum_age_seconds,
                "reason": timestamps.reason,
            },
            "futures_instrument_key": resolution.futures_instrument_key,
            "futures_expiry": resolution.futures_expiry.isoformat() if resolution.futures_expiry else None,
            "futures_volume_available": resolution.futures_volume_available,
            "futures_vwap_available": resolution.futures_vwap_available,
            "source_name": resolution.source_name,
            "source_version": resolution.source_version,
            "reason_code": resolution.reason_code,
            "reason": resolution.reason,
        }
    if isinstance(resolution, RedBarV2Decision):
        return _decision_to_dict(resolution)
    raise TypeError(f"unsupported Red Bar V2 resolution type: {type(resolution).__name__}")


def _decision_to_dict(decision: RedBarV2Decision) -> dict[str, object]:
    return {
        "kind": "DECISION",
        "strategy_id": decision.strategy_id,
        "strategy_version": decision.strategy_version,
        "evaluation_timestamp": decision.evaluation_timestamp.isoformat(),
        "evaluation_timeframe": decision.evaluation_timeframe,
        "entry_type": decision.entry_type.value if decision.entry_type else None,
        "previous_state": decision.previous_state.value,
        "current_state": decision.current_state.value,
        "direction": decision.direction.value if decision.direction else None,
        "option_side": decision.option_side.value if decision.option_side else None,
        "trend_strength": decision.trend_strength.value if decision.trend_strength else None,
        "reference": _reference_to_dict(decision.reference) if decision.reference else None,
        "rsi": None if decision.rsi is None else {
            "value": decision.rsi.value,
            "bullish_threshold": decision.rsi.bullish_threshold,
            "bearish_threshold": decision.rsi.bearish_threshold,
            "bullish_aligned": decision.rsi.bullish_aligned,
            "bearish_aligned": decision.rsi.bearish_aligned,
        },
        "futures_vwap": None if decision.futures_vwap is None else {
            "instrument_key": decision.futures_vwap.instrument_key,
            "comparison_price": decision.futures_vwap.comparison_price,
            "vwap": decision.futures_vwap.vwap,
            "volume": decision.futures_vwap.volume,
            "bullish_aligned": decision.futures_vwap.bullish_aligned,
            "bearish_aligned": decision.futures_vwap.bearish_aligned,
            "fresh": decision.futures_vwap.fresh,
        },
        "midpoint": None if decision.midpoint is None else {
            "index_close": decision.midpoint.index_close,
            "midpoint": decision.midpoint.midpoint,
            "bullish_aligned": decision.midpoint.bullish_aligned,
            "bearish_aligned": decision.midpoint.bearish_aligned,
        },
        "context_status": decision.context_status.value,
        "admission_outcome": decision.admission_outcome.value,
        "admission_code": decision.admission_code,
        "admission_reason": decision.admission_reason,
    }


def _rsi_from_dict(payload: Mapping[str, object]) -> RsiEvidence:
    return RsiEvidence(
        value=_number(payload, "value"),
        bullish_threshold=_number(payload, "bullish_threshold"),
        bearish_threshold=_number(payload, "bearish_threshold"),
        bullish_aligned=_bool(payload, "bullish_aligned"),
        bearish_aligned=_bool(payload, "bearish_aligned"),
    )


def _futures_from_dict(payload: Mapping[str, object]) -> FuturesVwapEvidence:
    return FuturesVwapEvidence(
        instrument_key=_text(payload, "instrument_key"),
        comparison_price=_number(payload, "comparison_price"),
        vwap=_number(payload, "vwap"),
        volume=_number(payload, "volume"),
        bullish_aligned=_bool(payload, "bullish_aligned"),
        bearish_aligned=_bool(payload, "bearish_aligned"),
        fresh=_bool(payload, "fresh"),
    )


def _midpoint_from_dict(payload: Mapping[str, object]) -> MidpointEvidence:
    return MidpointEvidence(
        index_close=_number(payload, "index_close"),
        midpoint=_number(payload, "midpoint"),
        bullish_aligned=_bool(payload, "bullish_aligned"),
        bearish_aligned=_bool(payload, "bearish_aligned"),
    )


def _decision_from_dict(payload: Mapping[str, object]) -> RedBarV2Decision:
    reference_payload = payload.get("reference")
    rsi_payload = payload.get("rsi")
    futures_payload = payload.get("futures_vwap")
    midpoint_payload = payload.get("midpoint")
    return RedBarV2Decision(
        strategy_id=_text(payload, "strategy_id"),
        strategy_version=_text(payload, "strategy_version"),
        evaluation_timestamp=_datetime(_required(payload, "evaluation_timestamp"), "decision.evaluation_timestamp"),
        evaluation_timeframe=_text(payload, "evaluation_timeframe"),
        entry_type=None if payload.get("entry_type") is None else _enum(EntryType, payload.get("entry_type"), "decision.entry_type"),
        previous_state=_enum(RedBarV2State, _required(payload, "previous_state"), "decision.previous_state"),
        current_state=_enum(RedBarV2State, _required(payload, "current_state"), "decision.current_state"),
        direction=None if payload.get("direction") is None else _enum(Direction, payload.get("direction"), "decision.direction"),
        option_side=None if payload.get("option_side") is None else _enum(OptionSide, payload.get("option_side"), "decision.option_side"),
        trend_strength=None if payload.get("trend_strength") is None else _enum(TrendStrength, payload.get("trend_strength"), "decision.trend_strength"),
        reference=None if reference_payload is None else _reference_from_dict(_mapping(reference_payload, "decision.reference")),
        rsi=None if rsi_payload is None else _rsi_from_dict(_mapping(rsi_payload, "decision.rsi")),
        futures_vwap=None if futures_payload is None else _futures_from_dict(_mapping(futures_payload, "decision.futures_vwap")),
        midpoint=None if midpoint_payload is None else _midpoint_from_dict(_mapping(midpoint_payload, "decision.midpoint")),
        context_status=_enum(ContextStatus, _required(payload, "context_status"), "decision.context_status"),
        admission_outcome=_enum(AdmissionOutcome, _required(payload, "admission_outcome"), "decision.admission_outcome"),
        admission_code=_text(payload, "admission_code"),
        admission_reason=_text(payload, "admission_reason"),
    )


def red_bar_v2_bundle_to_dict(bundle: RedBarV2SignalBundle) -> dict[str, object]:
    """Serialize a canonical signal bundle to JSON-compatible primitives."""
    return {
        "schema_version": bundle.schema_version,
        "bundle_id": bundle.bundle_id,
        "signal_id": bundle.signal_id,
        "strategy_id": bundle.strategy_id,
        "strategy_version": bundle.strategy_version,
        "trading_date": bundle.trading_date.isoformat(),
        "evaluation_timestamp": bundle.evaluation_timestamp.isoformat(),
        "evaluation_timeframe": bundle.evaluation_timeframe,
        "entry_type": bundle.entry_type.value,
        "direction": bundle.direction.value,
        "option_side": bundle.option_side.value,
        "decision": _decision_to_dict(bundle.decision),
        "idempotency_key": bundle.idempotency_key,
        "lifecycle_status": bundle.lifecycle_status.value,
        "created_at": bundle.created_at.isoformat(),
    }


def red_bar_v2_bundle_from_dict(payload: Mapping[str, object]) -> RedBarV2SignalBundle:
    """Deserialize and validate a canonical signal bundle."""
    schema_version = _text(payload, "schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(f"unsupported Red Bar V2 schema version: {schema_version}")
    decision = _decision_from_dict(_mapping(_required(payload, "decision"), "decision"))
    return RedBarV2SignalBundle(
        schema_version=schema_version,
        bundle_id=_text(payload, "bundle_id"),
        signal_id=_text(payload, "signal_id"),
        strategy_id=_text(payload, "strategy_id"),
        strategy_version=_text(payload, "strategy_version"),
        trading_date=_date(_required(payload, "trading_date"), "trading_date"),
        evaluation_timestamp=_datetime(_required(payload, "evaluation_timestamp"), "evaluation_timestamp"),
        evaluation_timeframe=_text(payload, "evaluation_timeframe"),
        entry_type=_enum(EntryType, _required(payload, "entry_type"), "entry_type"),
        direction=_enum(Direction, _required(payload, "direction"), "direction"),
        option_side=_enum(OptionSide, _required(payload, "option_side"), "option_side"),
        decision=decision,
        idempotency_key=_text(payload, "idempotency_key"),
        lifecycle_status=_enum(BundleLifecycleStatus, _required(payload, "lifecycle_status"), "lifecycle_status"),
        created_at=_datetime(_required(payload, "created_at"), "created_at"),
    )
