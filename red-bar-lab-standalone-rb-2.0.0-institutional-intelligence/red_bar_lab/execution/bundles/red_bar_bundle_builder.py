from __future__ import annotations

from datetime import timedelta
from typing import Mapping

import pandas as pd

from red_bar_lab.execution.bundles.bundle_identity import red_bar_bundle_identity
from red_bar_lab.execution.bundles.bundle_model import RED_BAR, StrategySignalBundle


def _required_number(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Red Bar bundle requires numeric {field}") from None
    if pd.isna(number):
        raise ValueError(f"Red Bar bundle requires numeric {field}")
    return number


def build_red_bar_bundle(
    signal: Mapping[str, object],
    reference: Mapping[str, object],
    *,
    instrument_key: str,
    entry_slots_consumed: int = 0,
) -> StrategySignalBundle:
    direction = str(signal.get("direction") or "").upper()
    if direction not in {"BULLISH", "BEARISH"}:
        raise ValueError("Red Bar bundle requires a confirmed bullish or bearish signal")
    reference_at = reference.get("source_timestamp")
    cross_at = signal.get("cross_timestamp")
    confirmed_at = signal.get("confirmation_timestamp") or cross_at
    if not reference_at or not cross_at or not confirmed_at:
        raise ValueError("Red Bar bundle requires reference, cross and confirmation timestamps")
    bundle_id, canonical = red_bar_bundle_identity(
        instrument_key=instrument_key,
        direction=direction,
        reference_timestamp=reference_at,
        cross_timestamp=cross_at,
    )
    fresh_until = signal.get("fresh_until")
    if not fresh_until:
        fresh_until = (pd.Timestamp(confirmed_at) + timedelta(minutes=5)).isoformat()
    allowed = 1
    consumed = max(0, min(allowed, int(entry_slots_consumed)))
    trigger = _required_number(
        signal.get("trigger_level") or reference.get("level_value") or reference.get("midpoint"),
        "trigger_level",
    )
    invalidation_source = (
        signal.get("invalidation_level")
        if signal.get("invalidation_level") not in (None, "")
        else reference.get("source_low") if direction == "BULLISH" else reference.get("source_high")
    )
    invalidation = _required_number(invalidation_source, "invalidation_level")
    return StrategySignalBundle(
        bundle_id=bundle_id,
        strategy_id=RED_BAR,
        instrument_key=instrument_key,
        direction=direction,
        option_side="CE" if direction == "BULLISH" else "PE",
        detected_at=str(confirmed_at),
        fresh_until=str(fresh_until),
        primary_signal_id=str(signal.get("signal_id") or ""),
        primary_setup_type="RED_BAR_REFERENCE_CROSS",
        trigger_level=trigger,
        invalidation_level=invalidation,
        bundle_state="CONSUMED" if consumed else "FRESH",
        execution_allowed=False,
        entry_slots_allowed=allowed,
        entry_slots_consumed=consumed,
        canonical_event_identity=canonical,
    )
