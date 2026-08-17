from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.execution.bundles import build_red_bar_bundle

IST = ZoneInfo("Asia/Kolkata")
CONSUMING_STATES = {
    "QUEUED", "APPROVED", "ORDER_OPENED", "POSITION_OPENED", "EXECUTED",
    "FILLED", "OPEN", "CLOSED", "EXITED", "COMPLETE", "COMPLETED",
}


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


def _consumed(database, signal_id: str) -> tuple[int, list[dict[str, str]]]:
    if not signal_id or not hasattr(database, "read_execution_state_events"):
        return 0, []
    try:
        events = list(database.read_execution_state_events(signal_id=signal_id, limit=100) or [])
    except Exception:
        return 0, []
    rows: list[dict[str, str]] = []
    consumed = False
    for event in events:
        state = str(event.get("state") or event.get("status") or "").upper()
        consumes = state in CONSUMING_STATES
        consumed = consumed or consumes
        rows.append({
            "state": state or "Unavailable",
            "order_id": _text(event.get("order_id")),
            "consumes_bundle": "YES" if consumes else "NO",
            "timestamp": _text(event.get("timestamp")),
        })
    return int(consumed), rows


def build_red_bar_bundle_resolution(
    *, database, instrument_key: str, trading_date: str, reference
) -> dict[str, object]:
    attempts = list(database.read_signal_attempts(instrument_key, trading_date) or [])
    signal = _latest(
        [row for row in attempts if row.get("confirmation_timestamp") and row.get("direction")],
        ("confirmation_timestamp", "cross_timestamp"),
    )
    if not signal or not reference:
        return {
            "signal_state": "NOT AVAILABLE",
            "normalized_intent": "OBSERVE / WAIT",
            "bundle_state": "NOT CREATED",
            "final_outcome": "OBSERVE",
            "strategy_owner": "Red Bar",
            "signal_id": "Not created",
            "bundle_id": "Not created",
            "signal_age": "Unavailable",
            "entry_capacity": "0 of 1 consumed",
            "decision_reason": "A confirmed Red Bar reference/cross event is unavailable.",
            "applied_rule": "Reference, midpoint cross and confirmed direction are required.",
            "next_step": "Wait for a confirmed Red Bar event.",
            "signal_rows": [],
            "bundle_rows": [],
            "lifecycle_rows": [],
            "refreshed_at": None,
        }

    signal_id = str(signal.get("signal_id") or "")
    consumed, lifecycle_rows = _consumed(database, signal_id)
    bundle = build_red_bar_bundle(
        signal,
        reference,
        instrument_key=instrument_key,
        entry_slots_consumed=consumed,
    )
    detected_at = _as_ist(bundle.detected_at)
    fresh_until = _as_ist(bundle.fresh_until)
    now = pd.Timestamp.now(tz=IST)
    fresh = bool(fresh_until is not None and now <= fresh_until)
    age = max(0.0, (now - detected_at).total_seconds()) if detected_at is not None else None

    if consumed:
        state, outcome = "CONSUMED", "HOLD"
        reason = "The independent Red Bar bundle has already produced downstream execution evidence."
    elif not fresh:
        state, outcome = "STALE", "HOLD"
        reason = "The Red Bar bundle is outside its recorded freshness window."
    else:
        state, outcome = "FRESH", "FORWARD"
        reason = "A fresh Red Bar-owned bundle is ready for Red Bar contract selection."

    signal_rows = [
        {"field": "Signal ID", "value": signal_id or "Unavailable"},
        {"field": "Reference timestamp", "value": _text(reference.get("source_timestamp"))},
        {"field": "Midpoint", "value": _text(reference.get("level_value") or reference.get("midpoint"))},
        {"field": "Cross timestamp", "value": _text(signal.get("cross_timestamp"))},
        {"field": "Confirmation timestamp", "value": _text(signal.get("confirmation_timestamp"))},
        {"field": "Direction", "value": bundle.direction},
    ]
    bundle_rows = [
        {"field": "Strategy owner", "value": "Red Bar"},
        {"field": "Strategy ID", "value": bundle.strategy_id},
        {"field": "Bundle ID", "value": bundle.bundle_id},
        {"field": "Canonical event identity", "value": bundle.canonical_event_identity},
        {"field": "Option side", "value": bundle.option_side},
        {"field": "Trigger level", "value": f"{bundle.trigger_level:,.2f}"},
        {"field": "Invalidation level", "value": f"{bundle.invalidation_level:,.2f}"},
        {"field": "Created at", "value": bundle.detected_at},
        {"field": "Fresh until", "value": bundle.fresh_until},
        {"field": "Entry capacity", "value": f"{consumed} of 1 consumed"},
        {"field": "Execution allowed", "value": "NO — SHADOW/READ-ONLY"},
    ]
    return {
        "signal_state": "CONFIRMED",
        "normalized_intent": f"BUY {bundle.option_side}",
        "bundle_state": state,
        "final_outcome": outcome,
        "strategy_owner": "Red Bar",
        "signal_id": signal_id or "Not created",
        "bundle_id": bundle.bundle_id,
        "signal_age": f"{age:.1f} sec" if age is not None else "Unavailable",
        "entry_capacity": f"{consumed} of 1 consumed",
        "decision_reason": reason,
        "applied_rule": "Only Red Bar reference, cross and confirmation evidence belongs to this bundle.",
        "next_step": (
            f"Select the best eligible {bundle.option_side} contract."
            if outcome == "FORWARD" else "Wait for a new independent Red Bar bundle."
        ),
        "signal_rows": signal_rows,
        "bundle_rows": bundle_rows,
        "lifecycle_rows": lifecycle_rows,
        "refreshed_at": detected_at,
    }
