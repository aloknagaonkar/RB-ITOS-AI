from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.execution.bundles import (
    DIRECTIONAL_REGIME,
    build_directional_regime_bundle,
)
from red_bar_lab.ui.strategy_bundle_lifecycle import (
    CONSUMING_STATES,
    consumed_contract_keys,
    read_scoped_execution_events,
)

IST = ZoneInfo("Asia/Kolkata")


def _safe_name(instrument_key: str) -> str:
    return instrument_key.replace("|", "_").replace(" ", "_").replace("/", "_").replace("\\", "_")


def _read_jsonl(path: Path, trading_date: str) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        timestamps = (
            row.get("detected_at"), row.get("timestamp"), row.get("updated_at"),
            row.get("created_at"), row.get("started_at"),
        )
        if any(str(value or "")[:10] == trading_date for value in timestamps):
            rows.append(row)
    return rows


def _latest(rows, fields):
    values = [dict(row) for row in rows]
    if not values:
        return {}
    return max(
        values,
        key=lambda row: next(
            (str(row.get(field) or "") for field in fields if row.get(field)),
            "",
        ),
    )


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            return ts.tz_localize(IST)
        return ts.tz_convert(IST)
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str:
    return "Unavailable" if value in (None, "") else str(value)


def build_dri_bundle_resolution(
    *, database, runs_root: str | Path, instrument_key: str, trading_date: str
) -> dict[str, object]:
    root = Path(runs_root)
    name = f"{_safe_name(instrument_key)}.jsonl"
    signals = _read_jsonl(root / "fresh_setup_signals_v43" / name, trading_date)
    bundles = _read_jsonl(root / "fresh_setup_bundles_v43" / name, trading_date)
    bundle_row = _latest(bundles, ("detected_at", "created_at", "timestamp"))
    if not bundle_row:
        return {
            "signal_state": "NOT AVAILABLE",
            "normalized_intent": "OBSERVE / WAIT",
            "bundle_state": "NOT CREATED",
            "final_outcome": "OBSERVE",
            "strategy_owner": "Directional Regime",
            "signal_id": "Not created",
            "bundle_id": "Not created",
            "legacy_bundle_id": "Not created",
            "signal_age": "Unavailable",
            "entry_capacity": "0 of 1 consumed",
            "decision_reason": "No persisted DRI bundle exists for the selected date.",
            "applied_rule": "Only persisted DRI regime-transition bundles are adapted.",
            "next_step": "Wait for the DRI transition pipeline to create a bundle.",
            "signal_rows": [], "bundle_rows": [], "lifecycle_rows": [],
            "refreshed_at": None,
        }

    signal_index = {
        str(row.get("signal_id") or ""): row
        for row in signals if str(row.get("signal_id") or "")
    }
    primary_id = str(bundle_row.get("primary_signal_id") or "")
    primary = signal_index.get(primary_id, {})
    supporting_ids = bundle_row.get("supporting_signal_ids") or []
    if isinstance(supporting_ids, str):
        supporting_ids = [item.strip() for item in supporting_ids.split(",") if item.strip()]
    supporting = [signal_index[item] for item in supporting_ids if item in signal_index]

    # Build once to obtain the strategy-scoped DRI-BND identity before reading
    # lifecycle events. This remains an in-memory adapter over legacy storage.
    preview = build_directional_regime_bundle(
        bundle_row,
        instrument_key=instrument_key,
        primary_signal=primary,
        supporting_signals=supporting,
        entry_slots_consumed=0,
    )
    events = read_scoped_execution_events(
        database,
        strategy_id=DIRECTIONAL_REGIME,
        bundle_id=preview.bundle_id,
        signal_id=preview.primary_signal_id,
    )
    consumed = min(preview.entry_slots_allowed, len(consumed_contract_keys(events)))
    bundle = build_directional_regime_bundle(
        bundle_row,
        instrument_key=instrument_key,
        primary_signal=primary,
        supporting_signals=supporting,
        entry_slots_consumed=consumed,
    )

    detected_at = _timestamp(bundle.detected_at)
    fresh_until = _timestamp(bundle.fresh_until)
    now = pd.Timestamp.now(tz=IST)
    fresh = bool(fresh_until is not None and now <= fresh_until)
    age = max(0.0, (now - detected_at).total_seconds()) if detected_at is not None else None

    canonical_matches = [
        row for row in bundles
        if str(row.get("primary_signal_id") or "") == bundle.primary_signal_id
        and str(row.get("direction") or "").upper() == bundle.direction
        and str(row.get("detected_at") or row.get("created_at") or "") == str(bundle_row.get("detected_at") or bundle_row.get("created_at") or "")
    ]
    duplicate = len(canonical_matches) > 1

    if duplicate:
        state, outcome = "DUPLICATE", "HOLD"
        reason = "The same DRI transition/detection event appears more than once in DRI storage."
    elif consumed >= bundle.entry_slots_allowed:
        state, outcome = "CONSUMED", "HOLD"
        reason = "The DRI bundle entry capacity has been consumed."
    elif not fresh:
        state, outcome = "STALE", "HOLD"
        reason = "The DRI bundle is outside its recorded freshness window."
    else:
        state, outcome = "FRESH", "FORWARD"
        reason = "A fresh DRI-owned bundle is ready for DRI contract selection."

    signal_rows = [
        {"field": "Legacy bundle ID", "value": _text(bundle_row.get("bundle_id"))},
        {"field": "Transition ID", "value": _text(bundle_row.get("transition_id") or primary.get("transition_id"))},
        {"field": "Primary signal ID", "value": bundle.primary_signal_id or "Unavailable"},
        {"field": "Primary setup", "value": bundle.primary_setup_type},
        {"field": "Supporting DRI signals", "value": str(len(bundle.supporting_signal_ids))},
        {"field": "Direction", "value": bundle.direction},
    ]
    bundle_rows = [
        {"field": "Strategy owner", "value": "Directional Regime"},
        {"field": "Strategy ID", "value": bundle.strategy_id},
        {"field": "Bundle ID", "value": bundle.bundle_id},
        {"field": "Canonical event identity", "value": bundle.canonical_event_identity},
        {"field": "Option side", "value": bundle.option_side},
        {"field": "Trigger level", "value": _text(bundle.trigger_level)},
        {"field": "Invalidation level", "value": _text(bundle.invalidation_level)},
        {"field": "Created at", "value": bundle.detected_at},
        {"field": "Fresh until", "value": bundle.fresh_until},
        {"field": "Entry capacity", "value": f"{consumed} of {bundle.entry_slots_allowed} consumed"},
        {"field": "Production persistence", "value": "LEGACY DRI STORE — READ-ONLY ADAPTER"},
        {"field": "Execution allowed by this UI", "value": "NO — SHADOW/READ-ONLY"},
    ]
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
    return {
        "signal_state": "BUNDLED",
        "normalized_intent": f"BUY {bundle.option_side}",
        "bundle_state": state,
        "final_outcome": outcome,
        "strategy_owner": "Directional Regime",
        "signal_id": bundle.primary_signal_id or "Not created",
        "bundle_id": bundle.bundle_id,
        "legacy_bundle_id": _text(bundle_row.get("bundle_id")),
        "signal_age": f"{age:.1f} sec" if age is not None else "Unavailable",
        "entry_capacity": f"{consumed} of {bundle.entry_slots_allowed} consumed",
        "decision_reason": reason,
        "applied_rule": "DRI ownership is transition-scoped; RSI and Red Bar records are excluded.",
        "next_step": (
            f"Select the best eligible {bundle.option_side} contract for DRI."
            if outcome == "FORWARD" else "Wait for a new independent DRI bundle."
        ),
        "signal_rows": signal_rows,
        "bundle_rows": bundle_rows,
        "lifecycle_rows": lifecycle_rows,
        "refreshed_at": detected_at,
    }
