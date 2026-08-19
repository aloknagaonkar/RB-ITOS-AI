from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_OPEN_TRADE_REQUIRED_COLUMNS = {
    "Order",
    "Option",
    "Entry",
    "Current",
    "Stop",
    "Target",
    "Status",
}


def _number(value: Any) -> float | None:
    try:
        if value in (None, "", "—"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def current_exit_level(row: Mapping[str, Any]) -> str:
    """Describe where an open option trade stands inside its exit policy."""
    entry = _number(row.get("Entry"))
    current = _number(row.get("Current"))
    stop = _number(row.get("Stop"))
    target1 = _number(row.get("Target"))

    if entry is None or current is None:
        return "WAITING FOR PRICE"
    if stop is not None and current <= stop:
        return "AT / BELOW STOP"
    if target1 is not None and current >= target1:
        return "TARGET 1 REACHED"
    if current >= entry:
        return "PROFIT ZONE"
    return "BETWEEN ENTRY AND STOP"


def enrich_open_trade_rows(rows: Any) -> Any:
    """Add exit progress to the existing Open Paper Position table rows.

    Other UI tables pass through unchanged. The match is intentionally strict
    so this additive display helper cannot alter unrelated diagnostics tables.
    """
    if rows is None:
        return []

    enriched = []
    for source in rows:
        if not isinstance(source, Mapping):
            enriched.append(source)
            continue

        row = dict(source)
        if not _OPEN_TRADE_REQUIRED_COLUMNS.issubset(row):
            enriched.append(row)
            continue

        entry = _number(row.get("Entry"))
        current = _number(row.get("Current"))
        move_pct = (
            round((current - entry) / entry * 100.0, 2)
            if entry not in (None, 0.0) and current is not None
            else None
        )

        ordered: dict[str, Any] = {}
        for key, value in row.items():
            ordered["Target 1" if key == "Target" else key] = value
            if key == "Current":
                ordered["Move %"] = move_pct
                ordered["Current Exit Level"] = current_exit_level(row)
        enriched.append(ordered)

    return enriched
