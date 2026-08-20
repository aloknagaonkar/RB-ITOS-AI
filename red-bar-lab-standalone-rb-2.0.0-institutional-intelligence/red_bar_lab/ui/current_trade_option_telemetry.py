from __future__ import annotations

from typing import Any, Mapping


_NOT_AVAILABLE = "—"


def _number(value: object, digits: int = 2) -> str:
    if value in (None, ""):
        return _NOT_AVAILABLE
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return _NOT_AVAILABLE


def _integer(value: object) -> str:
    if value in (None, ""):
        return _NOT_AVAILABLE
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return _NOT_AVAILABLE


def _telemetry_columns(telemetry: Mapping[str, object]) -> dict[str, object]:
    return {
        "Delta": _number(telemetry.get("delta"), 3),
        "Strike PCR": _number(telemetry.get("pcr_oi"), 2),
        "Call OI": _integer(telemetry.get("call_oi_at_strike")),
        "Put OI": _integer(telemetry.get("put_oi_at_strike")),
        "IV": _number(telemetry.get("iv"), 2),
        "PCR Source": str(telemetry.get("pcr_source") or "NOT_AVAILABLE"),
        "Telemetry Updated": str(
            telemetry.get("observed_timestamp")
            or telemetry.get("created_at")
            or _NOT_AVAILABLE
        ),
    }


def install(active_trade_views_module: Any) -> None:
    """Show latest selected-strike PCR and Delta on active paper trades.

    The database is read once per order while attribution is prepared. The compact
    table wrapper reuses that attached snapshot and performs no provider/API calls.
    """
    if getattr(active_trade_views_module, "_option_telemetry_columns_installed", False):
        return

    original_compact = active_trade_views_module._compact_trade_rows

    def attributed_orders(database, orders):
        result = []
        for raw in orders:
            order = dict(raw)
            order_id = str(order.get("order_id") or "")
            telemetry = active_trade_views_module._safe_latest_telemetry(database, order_id)
            checkpoint = active_trade_views_module._safe_checkpoint(database, order)
            attribution = active_trade_views_module.build_strategy_attribution(
                order,
                checkpoint,
                telemetry,
            )
            result.append(
                {
                    **order,
                    "_attribution": attribution,
                    "_option_telemetry": dict(telemetry or {}),
                }
            )
        return result

    def compact_trade_rows(rows):
        base_rows = original_compact(rows)
        telemetry_by_order = {
            str(row.get("order_id") or ""): dict(row.get("_option_telemetry") or {})
            for row in rows
        }
        enriched = []
        for base in base_rows:
            item = dict(base)
            telemetry = telemetry_by_order.get(str(item.get("Order") or ""), {})
            ordered: dict[str, object] = {}
            inserted = False
            for key, value in item.items():
                ordered[key] = value
                if key == "P&L":
                    ordered.update(_telemetry_columns(telemetry))
                    inserted = True
            if not inserted:
                ordered.update(_telemetry_columns(telemetry))
            enriched.append(ordered)
        return enriched

    active_trade_views_module._attributed_orders = attributed_orders
    active_trade_views_module._compact_trade_rows = compact_trade_rows
    active_trade_views_module._option_telemetry_columns_installed = True


__all__ = ["install"]
