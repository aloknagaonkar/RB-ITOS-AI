from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.execution.bundles import RSI_EXTREME_REVERSAL, build_rsi_reversal_bundle
from red_bar_lab.execution.rsi_extreme_reversal import RsiExtremeReversalEngine
from red_bar_lab.ui.strategy_bundle_lifecycle import (
    CONSUMING_STATES,
    consumed_contract_keys,
    read_scoped_execution_events,
    strategy_owned,
)

IST = ZoneInfo("Asia/Kolkata")
RSI_SOURCE = "RSI_EXTREME_REVERSAL_V1"


def _text(value: object) -> str:
    return "Unavailable" if value in (None, "") else str(value)


def _latest(rows, fields):
    values = [dict(row) for row in (rows or [])]
    if not values:
        return {}
    return max(
        values,
        key=lambda row: next(
            (str(row.get(field) or "") for field in fields if row.get(field)),
            "",
        ),
    )


def _as_ist(value: object) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            return ts.tz_localize(IST)
        return ts.tz_convert(IST)
    except (TypeError, ValueError):
        return None


def _not_ready(reason: str) -> dict[str, object]:
    return {
        "signal_state": "NOT AVAILABLE",
        "normalized_intent": "OBSERVE / WAIT",
        "bundle_state": "NOT CREATED",
        "final_outcome": "OBSERVE",
        "signal_id": "Not created",
        "bundle_id": "Not created",
        "strategy_owner": "RSI Extreme Reversal",
        "signal_age": "Unavailable",
        "entry_capacity": "0 of 2 consumed",
        "next_step": "Wait for a confirmed RSI reversal signal.",
        "raw_rows": [],
        "normalization_rows": [],
        "freshness_rows": [],
        "bundle_rows": [],
        "lifecycle_rows": [],
        "decision_reason": reason,
        "applied_rule": "Armed or incomplete RSI states do not create a bundle.",
        "refreshed_at": None,
    }


def build_rsi_signal_resolution(
    *,
    candles: pd.DataFrame,
    database,
    settings,
    instrument_key: str,
    trading_date: str,
) -> dict[str, object]:
    signals = [
        item.as_record()
        for item in RsiExtremeReversalEngine().detect(candles, instrument_key=instrument_key)
    ]
    signal = _latest(signals, ("confirmation_timestamp", "detected_at"))
    if not signal:
        return _not_ready("No confirmed RSI reversal signal is available.")

    try:
        preview = build_rsi_reversal_bundle(
            signal,
            instrument_key=instrument_key,
            entry_slots_consumed=0,
        )
    except ValueError as exc:
        return _not_ready(str(exc))

    events = read_scoped_execution_events(
        database,
        strategy_id=RSI_EXTREME_REVERSAL,
        bundle_id=preview.bundle_id,
        signal_id=preview.primary_signal_id,
    )
    consumed_slots = min(2, len(consumed_contract_keys(events)))
    bundle = build_rsi_reversal_bundle(
        signal,
        instrument_key=instrument_key,
        entry_slots_consumed=consumed_slots,
    )
    detected_at = _as_ist(bundle.detected_at)
    fresh_until = _as_ist(bundle.fresh_until)
    now = pd.Timestamp.now(tz=IST)
    age_seconds = max(0.0, (now - detected_at).total_seconds()) if detected_at is not None else None
    fresh = bool(fresh_until is not None and now <= fresh_until)

    attempts = list(database.read_signal_attempts(instrument_key, trading_date) or [])
    matching_rsi = [
        row for row in attempts
        if str(row.get("signal_id") or "") == bundle.primary_signal_id
        and strategy_owned(row, RSI_EXTREME_REVERSAL)
    ]
    duplicate = len(matching_rsi) > 1

    if duplicate:
        lifecycle_state = "DUPLICATE"
        final_outcome = "HOLD"
        reason = "The same RSI stable signal identity appears more than once in explicitly RSI-owned records."
        rule = "Deduplication is scoped to RSI_EXTREME_REVERSAL plus canonical event identity."
    elif consumed_slots >= bundle.entry_slots_allowed:
        lifecycle_state = "CONSUMED"
        final_outcome = "HOLD"
        reason = "Both RSI contract-entry slots have been consumed by this RSI bundle."
        rule = "Consumption is scoped by strategy ID, bundle ID and contract identity."
    elif not fresh:
        lifecycle_state = "STALE"
        final_outcome = "HOLD"
        reason = "The RSI bundle is outside its recorded freshness window."
        rule = "Stale bundle state is reported without changing production execution behavior."
    elif consumed_slots == 1:
        lifecycle_state = "PARTIALLY_CONSUMED"
        final_outcome = "FORWARD"
        reason = "One RSI entry slot remains available for this RSI bundle."
        rule = "RSI bundle capacity progresses 0/2 → 1/2 → 2/2."
    else:
        lifecycle_state = "FRESH"
        final_outcome = "FORWARD"
        reason = "A fresh RSI-owned bundle has two available contract-entry slots."
        rule = "Only confirmed RSI reversal evidence is included in this bundle."

    lifecycle_rows = [
        {
            "state": str(event.get("state") or event.get("status") or "Unavailable"),
            "bundle_id": _text(event.get("bundle_id")),
            "contract_or_order": _text(
                event.get("contract_instrument_key") or event.get("instrument_key")
                or event.get("instrument_token") or event.get("tradingsymbol")
                or event.get("order_id")
            ),
            "consumes_slot": "YES" if str(event.get("state") or event.get("status") or "").upper() in CONSUMING_STATES else "NO",
            "ownership_scope": _text(event.get("ownership_scope")),
            "timestamp": _text(event.get("timestamp")),
        }
        for event in events
    ]
    raw_rows = [
        {"field": "Signal ID", "value": bundle.primary_signal_id or "Unavailable"},
        {"field": "Source engine", "value": RSI_SOURCE},
        {"field": "Detection timestamp", "value": _text(signal.get("detected_at"))},
        {"field": "Direction", "value": bundle.direction},
        {"field": "RSI armed value", "value": _text(signal.get("rsi_armed_value"))},
        {"field": "RSI confirmation value", "value": _text(signal.get("rsi_confirmation_value"))},
        {"field": "Cross-back timestamp", "value": _text(signal.get("rsi_crossback_timestamp") or signal.get("confirmation_timestamp"))},
        {"field": "Signal age", "value": f"{age_seconds:.1f} seconds" if age_seconds is not None else "Unavailable"},
    ]
    normalization_rows = [
        {"field": "Strategy owner", "value": "RSI Extreme Reversal"},
        {"field": "Strategy ID", "value": bundle.strategy_id},
        {"field": "Normalized direction", "value": bundle.direction},
        {"field": "Normalized intent", "value": f"BUY {bundle.option_side}"},
        {"field": "Option side", "value": bundle.option_side},
        {"field": "Canonical event identity", "value": bundle.canonical_event_identity},
    ]
    freshness_rows = [
        {"check": "Bundle created from confirmed RSI signal", "status": "PASS", "detail": bundle.detected_at},
        {"check": "Within recorded fresh-until", "status": "PASS" if fresh else "WAIT", "detail": bundle.fresh_until},
        {"check": "Duplicate within RSI strategy", "status": "YES" if duplicate else "NO", "detail": f"Explicit RSI-owned matches={len(matching_rsi)}"},
        {"check": "Entry slots remaining", "status": str(bundle.entry_slots_allowed - consumed_slots), "detail": f"{consumed_slots} of {bundle.entry_slots_allowed} consumed"},
    ]
    bundle_rows = [
        {"field": "Strategy owner", "value": "RSI Extreme Reversal"},
        {"field": "Bundle ID", "value": bundle.bundle_id},
        {"field": "Primary signal", "value": bundle.primary_signal_id},
        {"field": "Primary setup", "value": bundle.primary_setup_type},
        {"field": "Direction", "value": bundle.direction},
        {"field": "Option side", "value": bundle.option_side},
        {"field": "Trigger level", "value": f"{bundle.trigger_level:,.2f}"},
        {"field": "Invalidation level", "value": f"{bundle.invalidation_level:,.2f}"},
        {"field": "Created at", "value": bundle.detected_at},
        {"field": "Fresh until", "value": bundle.fresh_until},
        {"field": "Entry capacity", "value": f"{consumed_slots} of {bundle.entry_slots_allowed} consumed"},
        {"field": "Execution allowed", "value": "NO — SHADOW/READ-ONLY"},
    ]

    return {
        "signal_state": "CONFIRMED",
        "normalized_intent": f"BUY {bundle.option_side}",
        "bundle_state": lifecycle_state,
        "final_outcome": final_outcome,
        "signal_id": bundle.primary_signal_id or "Not created",
        "bundle_id": bundle.bundle_id,
        "strategy_owner": "RSI Extreme Reversal",
        "signal_age": f"{age_seconds:.1f} sec" if age_seconds is not None else "Unavailable",
        "entry_capacity": f"{consumed_slots} of {bundle.entry_slots_allowed} consumed",
        "next_step": (
            f"Select the best two eligible {bundle.option_side} contracts."
            if final_outcome == "FORWARD" and consumed_slots == 0
            else f"Select one remaining eligible {bundle.option_side} contract."
            if final_outcome == "FORWARD"
            else "Wait for a new independent RSI bundle."
        ),
        "raw_rows": raw_rows,
        "normalization_rows": normalization_rows,
        "freshness_rows": freshness_rows,
        "bundle_rows": bundle_rows,
        "lifecycle_rows": lifecycle_rows,
        "decision_reason": reason,
        "applied_rule": rule,
        "refreshed_at": detected_at,
    }
