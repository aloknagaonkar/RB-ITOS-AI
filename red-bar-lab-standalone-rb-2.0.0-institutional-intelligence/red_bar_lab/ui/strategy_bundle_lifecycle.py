from __future__ import annotations

from typing import Mapping

from red_bar_lab.execution.bundles.bundle_model import (
    DIRECTIONAL_REGIME,
    RED_BAR,
    RSI_EXTREME_REVERSAL,
)

CONSUMING_STATES = frozenset({
    "QUEUED", "APPROVED", "ORDER_OPENED", "POSITION_OPENED", "EXECUTED",
    "FILLED", "OPEN", "CLOSED", "EXITED", "COMPLETE", "COMPLETED",
})

_SOURCE_BY_STRATEGY = {
    RSI_EXTREME_REVERSAL: {"RSI_EXTREME_REVERSAL", "RSI_EXTREME_REVERSAL_V1"},
    RED_BAR: {"RED_BAR", "REFERENCE_LEVEL", "NEXT_RED_CANDLE"},
    DIRECTIONAL_REGIME: {
        "DIRECTIONAL_REGIME",
        "DIRECTIONAL_REGIME_INTELLIGENCE",
        "EARLY_1M_DIRECTIONAL_REGIME",
    },
}


def record_strategy_id(record: Mapping[str, object]) -> str:
    explicit = str(record.get("strategy_id") or "").upper().strip()
    if explicit:
        return explicit
    source = str(
        record.get("execution_strategy_source")
        or record.get("signal_source")
        or record.get("source")
        or ""
    ).upper().strip()
    for strategy_id, sources in _SOURCE_BY_STRATEGY.items():
        if source in sources:
            return strategy_id
    return "UNKNOWN"


def strategy_owned(record: Mapping[str, object], strategy_id: str) -> bool:
    return record_strategy_id(record) == str(strategy_id).upper().strip()


def read_scoped_execution_events(
    database,
    *,
    strategy_id: str,
    bundle_id: str,
    signal_id: str,
    limit: int = 200,
) -> list[dict[str, object]]:
    if not signal_id or not hasattr(database, "read_execution_state_events"):
        return []
    try:
        events = list(
            database.read_execution_state_events(signal_id=signal_id, limit=limit) or []
        )
    except Exception:
        return []

    scoped: list[dict[str, object]] = []
    for original in events:
        row = dict(original)
        event_strategy = record_strategy_id(row)
        event_bundle = str(row.get("bundle_id") or "")

        if event_strategy != "UNKNOWN" and event_strategy != strategy_id:
            continue
        if event_bundle and event_bundle != bundle_id:
            continue

        # Legacy rows may lack both ownership fields. They remain visible only
        # through the matching strategy signal ID and are labelled as legacy.
        row["ownership_scope"] = (
            "EXPLICIT"
            if event_strategy == strategy_id and event_bundle == bundle_id
            else "STRATEGY_ONLY"
            if event_strategy == strategy_id
            else "LEGACY_SIGNAL_FALLBACK"
        )
        scoped.append(row)
    return scoped


def consumed_contract_keys(events: list[Mapping[str, object]]) -> set[str]:
    keys: set[str] = set()
    for index, event in enumerate(events, start=1):
        state = str(event.get("state") or event.get("status") or "").upper()
        if state not in CONSUMING_STATES:
            continue
        key = str(
            event.get("contract_instrument_key")
            or event.get("instrument_key")
            or event.get("instrument_token")
            or event.get("tradingsymbol")
            or event.get("order_id")
            or f"legacy-event-{index}"
        )
        keys.add(key)
    return keys
