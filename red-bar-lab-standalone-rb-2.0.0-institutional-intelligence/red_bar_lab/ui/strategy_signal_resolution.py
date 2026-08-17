from __future__ import annotations

from datetime import datetime
from typing import Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.execution.directional_regime_policy import (
    evaluate_directional_regime_policy,
)
from red_bar_lab.execution.directional_regime_reference import (
    DirectionalRegimeReferenceService,
)
from red_bar_lab.execution.dri_opportunity_context import resolve_opposite_red_bar
from red_bar_lab.execution.rsi_extreme_reversal import RsiExtremeReversalEngine


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


def _safe_execution_events(database, signal_id: str) -> list[dict[str, object]]:
    if not signal_id or not hasattr(database, "read_execution_state_events"):
        return []
    try:
        return list(database.read_execution_state_events(signal_id=signal_id, limit=100) or [])
    except Exception:
        return []


def _consumption_state(database, signal_id: str) -> tuple[bool, str]:
    events = _safe_execution_events(database, signal_id)
    if not events:
        return False, "No persisted execution-state event was found for this signal."
    consumed_states = {
        "QUEUED", "APPROVED", "ORDER_OPENED", "POSITION_OPENED", "EXECUTED",
        "FILLED", "OPEN", "CLOSED", "EXITED",
    }
    states = [str(row.get("state") or row.get("status") or "").upper() for row in events]
    consumed = any(state in consumed_states for state in states)
    return consumed, (
        "A persisted downstream execution event exists."
        if consumed else "Execution events exist, but none prove that an entry was created."
    )


def _relationship(primary_direction: str, other_direction: object, available: bool) -> str:
    if not available:
        return "UNAVAILABLE"
    other = str(other_direction or "").upper()
    if other not in {"BULLISH", "BEARISH"}:
        return "NEUTRAL"
    return "SUPPORTS" if other == primary_direction else "OPPOSES"


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
        for item in RsiExtremeReversalEngine().detect(
            candles,
            instrument_key=instrument_key,
        )
    ]
    signal = _latest(signals, ("confirmation_timestamp", "detected_at"))
    if not signal:
        return {
            "signal_state": "NOT AVAILABLE",
            "normalized_intent": "OBSERVE / WAIT",
            "bundle_state": "NOT CREATED",
            "final_outcome": "OBSERVE",
            "signal_id": "Not created",
            "signal_age": "Unavailable",
            "consumed": "No",
            "supporting_count": "0",
            "opposing_count": "0",
            "next_step": "Wait for a confirmed RSI reversal signal.",
            "raw_rows": [],
            "normalization_rows": [],
            "freshness_rows": [],
            "bundle_rows": [],
            "conflict_rows": [],
            "decision_reason": "No confirmed RSI reversal signal is available for normalization.",
            "applied_rule": "No signal; observe only.",
            "refreshed_at": None,
        }

    signal_id = str(signal.get("signal_id") or "")
    direction = str(signal.get("direction") or "").upper()
    option_side = "CE" if direction == "BULLISH" else "PE" if direction == "BEARISH" else "NONE"
    detected_at = _as_ist(signal.get("detected_at") or signal.get("confirmation_timestamp"))
    fresh_until = _as_ist(signal.get("fresh_until"))
    now = pd.Timestamp.now(tz=IST)
    age_seconds = max(0.0, (now - detected_at).total_seconds()) if detected_at is not None else None
    fresh = bool(fresh_until is not None and now <= fresh_until)
    consumed, consumed_detail = _consumption_state(database, signal_id)

    attempts = list(database.read_signal_attempts(instrument_key, trading_date) or [])
    same_id_count = sum(1 for row in attempts if str(row.get("signal_id") or "") == signal_id)
    duplicate = same_id_count > 1
    if duplicate:
        signal_state = "DUPLICATE"
    elif consumed:
        signal_state = "CONSUMED"
    elif fresh:
        signal_state = "FRESH"
    else:
        signal_state = "STALE"

    red_bar_rows = [
        row for row in attempts
        if str(row.get("signal_source") or row.get("source") or "").upper() != RSI_SOURCE
    ]
    latest_red_bar = _latest(red_bar_rows, ("confirmation_timestamp", "cross_timestamp"))
    red_bar_relationship = _relationship(direction, latest_red_bar.get("direction"), bool(latest_red_bar))
    opposite_red_bar = resolve_opposite_red_bar(signal=signal, signals=attempts)
    if opposite_red_bar:
        red_bar_relationship = "OPPOSES"

    try:
        dri = DirectionalRegimeReferenceService(
            runs_root=settings.runs_root,
            maximum_age_minutes=30,
        ).evaluate(
            signal_direction=direction,
            instrument_key=instrument_key,
            at_time=signal.get("confirmation_timestamp") or signal.get("detected_at"),
        )
        dri_status = str(dri.status or "UNAVAILABLE").upper()
        dri_relationship = {
            "ALIGNED": "SUPPORTS",
            "PARTIAL_ALIGNMENT": "SUPPORTS",
            "CONFLICT": "OPPOSES",
            "NEUTRAL": "NEUTRAL",
        }.get(dri_status, "UNAVAILABLE")
        dri_policy = evaluate_directional_regime_policy(dri_status)
    except Exception as exc:
        dri = None
        dri_relationship = "UNAVAILABLE"
        dri_policy = evaluate_directional_regime_policy("UNAVAILABLE")
        dri_status = f"UNAVAILABLE: {type(exc).__name__}"

    relationships = [red_bar_relationship, dri_relationship]
    supporting = sum(value == "SUPPORTS" for value in relationships)
    opposing = sum(value == "OPPOSES" for value in relationships)

    if duplicate:
        final_outcome = "HOLD"
        reason = "The stable RSI signal identity appears more than once in persisted signal attempts."
        rule = "Duplicate signals are not forwarded as new trading intentions."
    elif consumed:
        final_outcome = "HOLD"
        reason = "This RSI signal already has downstream execution-state evidence."
        rule = "Consumed signals are managed through their existing queue or position."
    elif dri_policy.block_execution:
        final_outcome = "HOLD"
        reason = "A fresh Directional Regime bundle conflicts with the RSI direction."
        rule = dri_policy.reason
    else:
        final_outcome = "FORWARD"
        reason = "The confirmed RSI signal is normalized and no production DRI conflict policy blocks it."
        rule = dri_policy.reason

    event_identity = " | ".join([
        RSI_SOURCE,
        instrument_key,
        direction or "UNAVAILABLE",
        _text(signal.get("rsi_armed_timestamp")),
        _text(signal.get("confirmation_timestamp")),
    ])

    raw_rows = [
        {"field": "Signal ID", "value": _text(signal_id)},
        {"field": "Source engine", "value": RSI_SOURCE},
        {"field": "Detection timestamp", "value": _text(signal.get("detected_at"))},
        {"field": "Direction", "value": direction or "Unavailable"},
        {"field": "RSI armed value", "value": _text(signal.get("rsi_armed_value"))},
        {"field": "RSI confirmation value", "value": _text(signal.get("rsi_confirmation_value"))},
        {"field": "Signal age", "value": f"{age_seconds:.1f} seconds" if age_seconds is not None else "Unavailable"},
    ]
    normalization_rows = [
        {"field": "Normalized direction", "value": direction or "WAIT"},
        {"field": "Normalized intent", "value": f"BUY {option_side}" if option_side in {"CE", "PE"} else "OBSERVE / WAIT"},
        {"field": "Option side", "value": option_side},
        {"field": "Confidence", "value": "Production signal confirmed"},
        {"field": "Source", "value": RSI_SOURCE},
        {"field": "Stable event identity", "value": event_identity},
    ]
    freshness_rows = [
        {"check": "Within signal fresh-until", "status": "PASS" if fresh else "WAIT", "detail": _text(signal.get("fresh_until"))},
        {"check": "Already consumed", "status": "YES" if consumed else "NO", "detail": consumed_detail},
        {"check": "Duplicate stable signal ID", "status": "YES" if duplicate else "NO", "detail": f"Persisted matches={same_id_count}"},
        {"check": "Final lifecycle state", "status": signal_state, "detail": "Read-only classification; opening this page does not consume the signal."},
    ]
    bundle_rows = [
        {"member": "RSI reversal", "signal_id": signal_id, "direction": direction, "relationship": "PRIMARY", "timestamp": _text(signal.get("detected_at"))},
        {"member": "Directional regime", "signal_id": _text(getattr(dri, "bundle_id", None)), "direction": _text(getattr(dri, "bundle_direction", None)), "relationship": dri_relationship, "timestamp": _text(getattr(dri, "detected_at", None))},
        {"member": "Red Bar", "signal_id": _text(latest_red_bar.get("signal_id")), "direction": _text(latest_red_bar.get("direction")), "relationship": red_bar_relationship, "timestamp": _text(latest_red_bar.get("confirmation_timestamp"))},
    ]
    conflict_rows = [
        {"engine": "Directional Regime", "relationship": dri_relationship, "state": dri_status, "reason": _text(getattr(dri, "reason", None))},
        {"engine": "Red Bar", "relationship": red_bar_relationship, "state": "LATEST PERSISTED SIGNAL" if latest_red_bar else "UNAVAILABLE", "reason": "Opposite newer Red Bar is observational for the RSI path; DRI production policy remains the blocking conflict authority."},
    ]

    return {
        "signal_state": signal_state,
        "normalized_intent": f"BUY {option_side}" if option_side in {"CE", "PE"} else "OBSERVE / WAIT",
        "bundle_state": "DRI BUNDLE AVAILABLE" if getattr(dri, "bundle_id", None) else "COMPARISON ONLY",
        "final_outcome": final_outcome,
        "signal_id": signal_id or "Not created",
        "signal_age": f"{age_seconds:.1f} sec" if age_seconds is not None else "Unavailable",
        "consumed": "Yes" if consumed else "No",
        "supporting_count": str(supporting),
        "opposing_count": str(opposing),
        "next_step": "Select the best two eligible option contracts." if final_outcome == "FORWARD" else "Wait for the blocking state to clear or manage the existing signal lifecycle.",
        "raw_rows": raw_rows,
        "normalization_rows": normalization_rows,
        "freshness_rows": freshness_rows,
        "bundle_rows": bundle_rows,
        "conflict_rows": conflict_rows,
        "decision_reason": reason,
        "applied_rule": rule,
        "refreshed_at": detected_at,
    }
