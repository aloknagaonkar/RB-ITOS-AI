from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping


_OPEN_STATUSES = {"OPEN", "ACTIVE", "PENDING", "APPROVED", "EXECUTING"}


@dataclass(frozen=True)
class RedBarV2RsiExitResult:
    status: str
    reason: str
    completed_rsi: float | None = None
    conflicting_orders: int = 0
    exited_orders: int = 0
    errors: tuple[str, ...] = ()


def _exit_reason(order: Mapping[str, Any], rsi: float) -> str | None:
    if str(order.get("execution_strategy_source") or "").upper() != "RED_BAR_V2":
        return None
    if str(order.get("status") or "").upper() not in _OPEN_STATUSES:
        return None
    option_type = str(order.get("option_type") or "").upper()
    if option_type == "PE" and rsi > 45.0:
        return "AUTO_RSI_ABOVE_45"
    if option_type == "CE" and rsi < 55.0:
        return "AUTO_RSI_BELOW_55"
    return None


def execute_rsi_threshold_exits(
    *,
    completed_1m_rsi: float | None,
    completed_1m_timestamp: str | None,
    open_orders: Iterable[Mapping[str, Any]],
    close_position: Callable[[str, str], Any],
) -> RedBarV2RsiExitResult:
    """Exit V2 positions from completed one-minute RSI threshold recovery."""
    if completed_1m_rsi is None or not completed_1m_timestamp:
        return RedBarV2RsiExitResult("NO_ACTION", "COMPLETED_1M_RSI_UNAVAILABLE")
    rsi = float(completed_1m_rsi)
    triggered: list[tuple[dict[str, Any], str]] = []
    for raw_order in open_orders:
        order = dict(raw_order)
        reason = _exit_reason(order, rsi)
        if reason is not None:
            triggered.append((order, reason))
    if not triggered:
        return RedBarV2RsiExitResult(
            "NO_ACTION", "RSI_POSITION_THRESHOLD_HELD", completed_rsi=rsi
        )

    exited = 0
    errors: list[str] = []
    for order, reason in triggered:
        order_id = str(order.get("order_id") or "")
        if not order_id:
            errors.append("MISSING_ORDER_ID")
            continue
        try:
            close_position(order_id, reason)
            exited += 1
        except Exception as exc:
            errors.append(f"{order_id}:{type(exc).__name__}:{exc}")
    return RedBarV2RsiExitResult(
        status="EXITED" if exited and not errors else "PARTIAL" if exited else "ERROR",
        reason="RED_BAR_V2_RSI_THRESHOLD_EXIT",
        completed_rsi=rsi,
        conflicting_orders=len(triggered),
        exited_orders=exited,
        errors=tuple(errors),
    )


__all__ = ["RedBarV2RsiExitResult", "execute_rsi_threshold_exits"]
