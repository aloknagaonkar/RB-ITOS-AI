from __future__ import annotations

from datetime import datetime

from red_bar_lab.domain.red_bar_v2 import (
    AdmissionOutcome,
    BundleLifecycleStatus,
    RedBarV2Decision,
    RedBarV2SignalBundle,
    build_red_bar_v2_bundle_id,
    build_red_bar_v2_idempotency_key,
    build_red_bar_v2_signal_id,
)

from .exceptions import CanonicalResolutionError


def create_red_bar_v2_signal_bundle(
    *,
    instrument_key: str,
    decision: RedBarV2Decision,
    created_at: datetime,
    schema_version: str = "1.0",
) -> RedBarV2SignalBundle | None:
    """Create a deterministic bundle using the underlying strategy instrument."""
    if decision.admission_outcome is not AdmissionOutcome.ALLOWED:
        return None
    if not isinstance(instrument_key, str) or not instrument_key.strip():
        raise CanonicalResolutionError("underlying instrument_key must be non-empty")
    if decision.reference is None:
        raise CanonicalResolutionError("allowed decision requires a reference")
    if decision.entry_type is None or decision.direction is None or decision.option_side is None:
        raise CanonicalResolutionError("allowed decision is missing bundle identity fields")
    if decision.futures_vwap is None:
        raise CanonicalResolutionError("allowed decision requires futures VWAP evidence")

    trading_date = decision.reference.trading_date
    signal_id = build_red_bar_v2_signal_id(
        strategy_version=decision.strategy_version,
        instrument_key=instrument_key,
        trading_date=trading_date,
        reference_id=decision.reference.reference_id,
        evaluation_timestamp=decision.evaluation_timestamp,
        entry_type=decision.entry_type,
        direction=decision.direction,
    )
    bundle_id = build_red_bar_v2_bundle_id(signal_id=signal_id, schema_version=schema_version)
    idempotency_key = build_red_bar_v2_idempotency_key(
        signal_id=signal_id,
        option_side=decision.option_side,
    )
    return RedBarV2SignalBundle(
        schema_version=schema_version,
        bundle_id=bundle_id,
        signal_id=signal_id,
        strategy_id=decision.strategy_id,
        strategy_version=decision.strategy_version,
        trading_date=trading_date,
        evaluation_timestamp=decision.evaluation_timestamp,
        evaluation_timeframe=decision.evaluation_timeframe,
        entry_type=decision.entry_type,
        direction=decision.direction,
        option_side=decision.option_side,
        decision=decision,
        idempotency_key=idempotency_key,
        lifecycle_status=BundleLifecycleStatus.AVAILABLE,
        created_at=created_at,
        instrument_key=instrument_key,
    )
