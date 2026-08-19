from __future__ import annotations

from typing import Any

from red_bar_lab.execution.exit_engine import PaperExitEngine


def _protection_stage(health) -> str:
    if health.trailing_active:
        return "TRAILING"
    if health.profit_lock_active:
        return "PROFIT LOCK"
    if health.breakeven_armed:
        return "BREAKEVEN"
    return "HARD STOP"


def _price(value: object) -> str:
    if value in (None, ""):
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _new_protection(health) -> str:
    initial = health.initial_stop
    effective = health.effective_stop
    if initial is None and effective is None:
        return "—"
    if initial is None:
        return _price(effective)
    if effective is None:
        return _price(initial)
    return f"{_price(initial)} → {_price(effective)}"


def _insert_protection_after_pnl(
    row: dict[str, object],
    *,
    trailing_stop: float | None,
    stage: str,
    new_protection: str,
) -> dict[str, object]:
    ordered: dict[str, object] = {}
    inserted = False
    for key, value in row.items():
        ordered[key] = value
        if key == "P&L":
            ordered["Trailing Stop"] = trailing_stop
            ordered["Stage"] = stage
            ordered["New Protection"] = new_protection
            inserted = True

    if not inserted:
        ordered["Trailing Stop"] = trailing_stop
        ordered["Stage"] = stage
        ordered["New Protection"] = new_protection
    return ordered


def install(active_trade_views_module: Any) -> None:
    """Add only essential protection fields to the existing Current Trades row."""
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

            trailing_stop = (
                round(float(health.trailing_stop), 2)
                if health.trailing_stop is not None
                else None
            )
            enriched.append(
                _insert_protection_after_pnl(
                    item,
                    trailing_stop=trailing_stop,
                    stage=_protection_stage(health),
                    new_protection=_new_protection(health),
                )
            )

        return enriched

    active_trade_views_module._compact_trade_rows = wrapped
    active_trade_views_module._exit_columns_installed = True
