from __future__ import annotations

from typing import Any


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _exit_level(row: dict[str, Any]) -> str:
    entry = _as_float(row.get("Entry"))
    current = _as_float(row.get("Current"))
    stop = _as_float(row.get("Stop"))
    target1 = _as_float(row.get("Target 1"))
    target2 = _as_float(row.get("Target 2"))

    if current is None:
        return "WAITING FOR PRICE"
    if stop is not None and current <= stop:
        return "AT / BELOW STOP"
    if target2 is not None and current >= target2:
        return "TARGET 2 REACHED"
    if target1 is not None and current >= target1:
        return "TARGET 1 REACHED"
    if entry is not None and current >= entry:
        return "PROFIT ZONE"
    if entry is not None:
        return "BETWEEN ENTRY AND STOP"
    return "WAITING FOR PRICE"


def install(active_trade_views_module: Any) -> None:
    """Add exit-policy progress columns to the existing Current Trades table."""
    if getattr(active_trade_views_module, "_exit_columns_installed", False):
        return

    original = active_trade_views_module._compact_trade_rows

    def wrapped(rows):
        base_rows = original(rows)
        enriched = []
        source_by_order = {
            str(row.get("order_id") or ""): row
            for row in rows
        }
        for base in base_rows:
            item = dict(base)
            source = source_by_order.get(str(item.get("Order") or ""), {})
            entry = _as_float(item.get("Entry"))
            current = _as_float(item.get("Current"))
            move_pct = (
                ((current - entry) / entry) * 100.0
                if entry not in (None, 0.0) and current is not None
                else None
            )
            item["Move %"] = round(move_pct, 2) if move_pct is not None else None
            item["Stop"] = source.get("stop_price")
            item["Target 1"] = source.get("target1_price")
            item["Target 2"] = source.get("target2_price")
            item["Current Exit Level"] = _exit_level(item)
            item["Exit Mode"] = source.get("exit_mode") or "ACTIVE POLICY"
            enriched.append(item)
        return enriched

    active_trade_views_module._compact_trade_rows = wrapped
    active_trade_views_module._exit_columns_installed = True
