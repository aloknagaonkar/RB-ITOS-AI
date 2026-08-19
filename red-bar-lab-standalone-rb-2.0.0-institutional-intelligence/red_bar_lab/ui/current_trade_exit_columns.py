from __future__ import annotations

from typing import Any

from red_bar_lab.execution.exit_engine import PaperExitEngine


def _protection_stage(health) -> str:
    if health.trailing_active:
        return "TRAILING ACTIVE"
    if health.profit_lock_active:
        return "PROFIT LOCK ACTIVE"
    if health.breakeven_armed:
        return "BREAKEVEN ARMED"
    return "HARD STOP ONLY"


def install(active_trade_views_module: Any) -> None:
    """Add only essential protection fields to the Current Trades table."""
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
            health = exit_engine.evaluate(
                position=source,
                exit_mode=str(
                    source.get("exit_mode") or "STANDARD_MULTI_FACTOR"
                ),
            )

            item["Trailing Stop"] = health.trailing_stop
            item["Stage"] = _protection_stage(health)
            item["New Protection"] = health.effective_stop
            enriched.append(item)

        return enriched

    active_trade_views_module._compact_trade_rows = wrapped
    active_trade_views_module._exit_columns_installed = True
