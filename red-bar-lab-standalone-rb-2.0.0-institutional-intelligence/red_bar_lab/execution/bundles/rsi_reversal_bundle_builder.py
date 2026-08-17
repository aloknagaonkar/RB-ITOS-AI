from __future__ import annotations

from datetime import timedelta
from typing import Mapping

import pandas as pd

from red_bar_lab.execution.bundles.bundle_identity import rsi_bundle_identity
from red_bar_lab.execution.bundles.bundle_model import RSI_EXTREME_REVERSAL, StrategySignalBundle


def build_rsi_reversal_bundle(
    signal: Mapping[str, object],
    *,
    instrument_key: str,
    entry_slots_consumed: int = 0,
) -> StrategySignalBundle:
    direction = str(signal.get("direction") or "").upper()
    if direction not in {"BULLISH", "BEARISH"}:
        raise ValueError("RSI bundle requires a confirmed bullish or bearish signal")
    extreme_at = signal.get("rsi_armed_timestamp")
    confirmed_at = signal.get("confirmation_timestamp") or signal.get("detected_at")
    if not extreme_at or not confirmed_at:
        raise ValueError("RSI bundle requires extreme and confirmation timestamps")
    bundle_id, canonical = rsi_bundle_identity(
        instrument_key=instrument_key,
        direction=direction,
        extreme_timestamp=extreme_at,
        confirmation_timestamp=confirmed_at,
    )
    detected = pd.Timestamp(confirmed_at)
    fresh_until = signal.get("fresh_until")
    if not fresh_until:
        fresh_until = (detected + timedelta(minutes=5)).isoformat()
    state = (
        "CONSUMED" if entry_slots_consumed >= 2
        else "PARTIALLY_CONSUMED" if entry_slots_consumed == 1
        else "FRESH"
    )
    return StrategySignalBundle(
        bundle_id=bundle_id,
        strategy_id=RSI_EXTREME_REVERSAL,
        instrument_key=instrument_key,
        direction=direction,
        option_side="CE" if direction == "BULLISH" else "PE",
        detected_at=str(confirmed_at),
        fresh_until=str(fresh_until),
        primary_signal_id=str(signal.get("signal_id") or ""),
        primary_setup_type=str(signal.get("level_name") or "RSI_EXTREME_REVERSAL"),
        trigger_level=float(signal.get("trigger_level") or signal.get("confirmation_close")),
        invalidation_level=float(signal.get("invalidation_level")),
        bundle_state=state,
        execution_allowed=False,
        entry_slots_allowed=2,
        entry_slots_consumed=max(0, min(2, int(entry_slots_consumed))),
        canonical_event_identity=canonical,
    )
