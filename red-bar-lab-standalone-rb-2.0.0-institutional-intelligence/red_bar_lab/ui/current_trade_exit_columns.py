from __future__ import annotations

from typing import Any

from red_bar_lab.execution.exit_engine import PaperExitEngine


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
    effective_stop = _as_float(
        row.get("Effective Stop") or row.get("Stop")
    )
    target1 = _as_float(row.get("Target 1"))
    target2 = _as_float(row.get("Target 2"))

    if current is None:
        return "WAITING FOR PRICE"
    if effective_stop is not None and current <= effective_stop:
        return "AT / BELOW EFFECTIVE STOP"
    if target2 is not None and current >= target2:
        return "TARGET 2 REACHED"
    if target1 is not None and current >= target1:
        return "TARGET 1 REACHED"
    if entry is not None and current >= entry:
        return "PROFIT ZONE"
    if entry is not None:
        return "BETWEEN ENTRY AND STOP"
    return "WAITING FOR PRICE"


def _protection_stage(health) -> str:
    if health.trailing_active:
        return "TRAILING ACTIVE"
    if health.profit_lock_active:
        return "PROFIT LOCK ACTIVE"
    if health.breakeven_armed:
        return "BREAKEVEN ARMED"
    return "HARD STOP ONLY"


def _trail_moved(health) -> str:
    initial = _as_float(health.initial_stop)
    effective = _as_float(health.effective_stop)
    trailing = _as_float(health.trailing_stop)

    if not health.trailing_active:
        return "NO — NOT ARMED"
    if trailing is None:
        return "NO — WAITING"
    if initial is None or initial <= 0:
        return "YES — TRAILING ACTIVE"
    if effective is not None and effective > initial:
        return f"YES +{effective - initial:.2f}"
    return "NO — STILL AT INITIAL STOP"


def install(active_trade_views_module: Any) -> None:
    """Add exact exit-engine protection state to the existing Current Trades table."""
    if getattr(active_trade_views_module, "_exit_columns_installed", False):
        return

    original = active_trade_views_module._compact_trade_rows
    exit_engine = PaperExitEngine()

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

            health = exit_engine.evaluate(
                position=source,
                exit_mode=str(
                    source.get("exit_mode") or "STANDARD_MULTI_FACTOR"
                ),
            )

            item["Move %"] = round(move_pct, 2) if move_pct is not None else None
            item["Initial Stop"] = health.initial_stop
            item["Effective Stop"] = health.effective_stop
            item["Protection Stage"] = _protection_stage(health)
            item["Trailing Active"] = "YES" if health.trailing_active else "NO"
            item["Trailing Stop"] = health.trailing_stop
            item["Trail Moved?"] = _trail_moved(health)
            item["Peak Price"] = health.peak_price
            item["Next Protection Trigger"] = health.next_trigger
            item["Target 1"] = health.target1
            item["Target 2"] = health.target2
            item["Current Exit Level"] = _exit_level(item)
            item["Exit Mode"] = source.get("exit_mode") or "STANDARD_MULTI_FACTOR"
            enriched.append(item)
        return enriched

    active_trade_views_module._compact_trade_rows = wrapped
    active_trade_views_module._exit_columns_installed = True
