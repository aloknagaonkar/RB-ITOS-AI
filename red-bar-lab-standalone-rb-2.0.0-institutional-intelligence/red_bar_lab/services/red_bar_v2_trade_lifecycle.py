from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_trade_lifecycle(
    *,
    signal_id: str,
    state_events: Iterable[Mapping[str, object]],
    queue_rows: Iterable[Mapping[str, object]],
    orders: Iterable[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Build one read-only, time-ordered paper-trade lifecycle projection."""
    timeline: list[dict[str, object]] = []
    for event in state_events:
        if str(event.get("signal_id") or "") != signal_id:
            continue
        timeline.append({
            "timestamp": event.get("timestamp"),
            "stage": "EXECUTION_EVENT",
            "event": event.get("state"),
            "status": event.get("state"),
            "contract": None,
            "order_id": event.get("order_id"),
            "price": None,
            "reason": event.get("detail"),
        })
    for queue in queue_rows:
        if str(queue.get("signal_id") or "") != signal_id:
            continue
        timeline.append({
            "timestamp": queue.get("created_at"),
            "stage": "RESERVATION_BOUNDARY",
            "event": "QUEUE_CREATED",
            "status": queue.get("status"),
            "contract": queue.get("candidate_symbol"),
            "order_id": queue.get("order_id"),
            "price": None,
            "reason": queue.get("reason"),
        })
        if queue.get("updated_at") != queue.get("created_at"):
            timeline.append({
                "timestamp": queue.get("updated_at"),
                "stage": "RESERVATION_BOUNDARY",
                "event": "QUEUE_UPDATED",
                "status": queue.get("status"),
                "contract": queue.get("candidate_symbol"),
                "order_id": queue.get("order_id"),
                "price": None,
                "reason": queue.get("reason"),
            })
    for order in orders:
        if str(order.get("signal_id") or "") != signal_id:
            continue
        timeline.append({
            "timestamp": order.get("entry_timestamp"),
            "stage": "PAPER_EXECUTION",
            "event": "PAPER_ENTRY",
            "status": "OPENED",
            "contract": order.get("tradingsymbol"),
            "order_id": order.get("order_id"),
            "price": order.get("entry_price"),
            "reason": order.get("entry_reason"),
        })
        if order.get("exit_timestamp"):
            timeline.append({
                "timestamp": order.get("exit_timestamp"),
                "stage": "PAPER_EXECUTION",
                "event": "PAPER_EXIT",
                "status": order.get("status"),
                "contract": order.get("tradingsymbol"),
                "order_id": order.get("order_id"),
                "price": order.get("exit_price"),
                "reason": order.get("exit_reason"),
            })

    timeline.sort(
        key=lambda row: (
            parsed.timestamp()
            if (parsed := _timestamp(row.get("timestamp"))) is not None
            else float("-inf")
        ),
    )
    previous: datetime | None = None
    for row in timeline:
        current = _timestamp(row.get("timestamp"))
        row["elapsed_from_previous_ms"] = (
            round((current - previous).total_seconds() * 1000.0, 3)
            if current is not None and previous is not None
            else None
        )
        if current is not None:
            previous = current
    return tuple(timeline)


def build_position_snapshot(
    orders: Iterable[Mapping[str, object]],
    *,
    signal_id: str,
) -> tuple[dict[str, object], ...]:
    """Project current protection and terminal state for correlated orders."""
    return tuple(
        {
            "Order ID": row.get("order_id"),
            "Contract": row.get("tradingsymbol"),
            "Status": row.get("status"),
            "Entry time": row.get("entry_timestamp"),
            "Entry price": row.get("entry_price"),
            "Current price": row.get("current_price"),
            "Peak gain points": row.get("mfe_points"),
            "Adverse points": row.get("mae_points"),
            "Protected stop": row.get("stop_price"),
            "Breakeven armed": bool(row.get("breakeven_armed")),
            "Trailing active": bool(row.get("trailing_active")),
            "Trailing stop": row.get("trailing_stop_price"),
            "Exit action": row.get("exit_action"),
            "Exit detail": row.get("exit_detail"),
            "Exit time": row.get("exit_timestamp"),
            "Exit price": row.get("exit_price"),
            "Exact exit reason": row.get("exit_reason"),
            "Realized P&L": row.get("realized_pnl"),
        }
        for row in orders
        if str(row.get("signal_id") or "") == signal_id
    )


__all__ = ["build_position_snapshot", "build_trade_lifecycle"]
