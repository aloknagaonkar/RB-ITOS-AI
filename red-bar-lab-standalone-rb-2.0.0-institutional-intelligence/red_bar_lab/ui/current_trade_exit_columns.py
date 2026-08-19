from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from red_bar_lab.execution.exit_engine import PaperExitEngine


IST = ZoneInfo("Asia/Kolkata")


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


def _price_updated(source: dict[str, object]) -> str:
    raw = (
        source.get("price_updated_at")
        or source.get("current_price_timestamp")
        or source.get("quote_timestamp")
        or source.get("last_price_timestamp")
        or source.get("updated_at")
        or source.get("last_updated")
    )
    if raw in (None, ""):
        return "—"
    text = str(raw).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        else:
            parsed = parsed.astimezone(IST)
        return parsed.strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return text


def _insert_live_fields(
    row: dict[str, object],
    *,
    price_updated: str,
    trailing_stop: float | None,
    stage: str,
    new_protection: str,
) -> dict[str, object]:
    ordered: dict[str, object] = {}
    protection_inserted = False
    timestamp_inserted = False

    for key, value in row.items():
        ordered[key] = value
        if key == "Current":
            ordered["Price Updated"] = price_updated
            timestamp_inserted = True
        if key == "P&L":
            ordered["Trailing Stop"] = trailing_stop
            ordered["Stage"] = stage
            ordered["New Protection"] = new_protection
            protection_inserted = True

    if not timestamp_inserted:
        ordered["Price Updated"] = price_updated
    if not protection_inserted:
        ordered["Trailing Stop"] = trailing_stop
        ordered["Stage"] = stage
        ordered["New Protection"] = new_protection
    return ordered


def install(active_trade_views_module: Any) -> None:
    """Add compact live-price and protection fields to Current Trades rows."""
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
                _insert_live_fields(
                    item,
                    price_updated=_price_updated(source),
                    trailing_stop=trailing_stop,
                    stage=_protection_stage(health),
                    new_protection=_new_protection(health),
                )
            )

        return enriched

    active_trade_views_module._compact_trade_rows = wrapped
    active_trade_views_module._exit_columns_installed = True
