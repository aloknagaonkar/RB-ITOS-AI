from __future__ import annotations

from typing import Mapping, Sequence

import pandas as pd

from red_bar_lab.execution.bundles.bundle_identity import directional_regime_bundle_identity
from red_bar_lab.execution.bundles.bundle_model import DIRECTIONAL_REGIME, StrategySignalBundle


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def build_directional_regime_bundle(
    legacy_bundle: Mapping[str, object],
    *,
    instrument_key: str,
    primary_signal: Mapping[str, object] | None = None,
    supporting_signals: Sequence[Mapping[str, object]] = (),
    entry_slots_consumed: int = 0,
) -> StrategySignalBundle:
    """Adapt one persisted DRI bundle to the common strategy-owned contract.

    The adapter is additive and read-compatible with legacy ``BND-...`` records.
    It does not rewrite the source artifact or change DRI signal grouping rules.
    """
    row = dict(legacy_bundle or {})
    primary = dict(primary_signal or {})
    direction = str(row.get("direction") or primary.get("direction") or "").upper()
    if direction not in {"BULLISH", "BEARISH"}:
        raise ValueError("Directional Regime bundle requires a bullish or bearish direction")

    transition_id = (
        row.get("transition_id")
        or primary.get("transition_id")
        or row.get("bundle_id")
    )
    detected_at = row.get("detected_at") or primary.get("detected_at")
    if not transition_id or not detected_at:
        raise ValueError("Directional Regime bundle requires transition identity and detection time")

    bundle_id, canonical = directional_regime_bundle_identity(
        instrument_key=instrument_key,
        transition_id=transition_id,
        detected_at=detected_at,
        direction=direction,
    )
    fresh_until = row.get("fresh_until") or primary.get("fresh_until")
    if not fresh_until:
        fresh_until = (pd.Timestamp(detected_at) + pd.Timedelta(minutes=30)).isoformat()

    supporting_ids = tuple(
        str(item.get("signal_id") or "")
        for item in supporting_signals
        if str(item.get("signal_id") or "")
    )
    supporting_types = tuple(
        str(item.get("setup_type") or item.get("level_name") or "DRI_SUPPORT")
        for item in supporting_signals
        if str(item.get("signal_id") or "")
    )
    allowed = max(1, int(row.get("entry_slots_allowed") or 1))
    consumed = max(0, min(allowed, int(entry_slots_consumed)))

    return StrategySignalBundle(
        bundle_id=bundle_id,
        strategy_id=DIRECTIONAL_REGIME,
        instrument_key=instrument_key,
        direction=direction,
        option_side="CE" if direction == "BULLISH" else "PE",
        detected_at=str(detected_at),
        fresh_until=str(fresh_until),
        primary_signal_id=str(
            row.get("primary_signal_id") or primary.get("signal_id") or ""
        ),
        primary_setup_type=str(
            row.get("primary_setup_type")
            or primary.get("setup_type")
            or "DIRECTIONAL_REGIME_SETUP"
        ),
        supporting_signal_ids=supporting_ids,
        supporting_setup_types=supporting_types,
        trigger_level=_number(row.get("trigger_level") or primary.get("trigger_level")),
        invalidation_level=_number(
            row.get("invalidation_level") or primary.get("invalidation_level")
        ),
        bundle_state="CONSUMED" if consumed >= allowed else "FRESH",
        execution_allowed=False,
        entry_slots_allowed=allowed,
        entry_slots_consumed=consumed,
        canonical_event_identity=canonical,
    )
