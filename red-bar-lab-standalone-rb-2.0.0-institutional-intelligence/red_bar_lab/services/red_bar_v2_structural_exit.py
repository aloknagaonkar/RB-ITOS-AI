from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping

from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot


_OPEN_STATUSES = {"OPEN", "ACTIVE", "PENDING", "APPROVED", "EXECUTING"}


@dataclass(frozen=True)
class RedBarV2StructuralExitResult:
    status: str
    reason: str
    completed_close: float | None = None
    exited_orders: int = 0
    errors: tuple[str, ...] = ()


def _exit_reason(
    order: Mapping[str, Any], *, close: float, high: float, low: float
) -> str | None:
    if str(order.get("execution_strategy_source") or "").upper() != "RED_BAR_V2":
        return None
    if str(order.get("status") or "").upper() not in _OPEN_STATUSES:
        return None
    option_type = str(order.get("option_type") or "").upper()
    if option_type == "PE" and close > high:
        return "AUTO_REFERENCE_HIGH_INVALIDATION"
    if option_type == "CE" and close < low:
        return "AUTO_REFERENCE_LOW_INVALIDATION"
    return None


def execute_structural_stop_exits(
    *,
    snapshot: RedBarV2UISnapshot | None,
    completed_1m_close: float | None,
    completed_1m_timestamp: str | None,
    open_orders: Iterable[Mapping[str, Any]],
    close_position: Callable[[str, str], Any],
) -> RedBarV2StructuralExitResult:
    """Exit V2 positions after a completed 1m close beyond reference geometry."""
    if snapshot is None or snapshot.reference_high is None or snapshot.reference_low is None:
        return RedBarV2StructuralExitResult("NO_ACTION", "REFERENCE_GEOMETRY_UNAVAILABLE")
    if completed_1m_close is None or not completed_1m_timestamp:
        return RedBarV2StructuralExitResult("NO_ACTION", "COMPLETED_1M_CLOSE_UNAVAILABLE")
    try:
        reference_date = datetime.fromisoformat(
            str(snapshot.reference_timestamp).replace("Z", "+00:00")
        ).date()
        completed_date = datetime.fromisoformat(
            str(completed_1m_timestamp).replace("Z", "+00:00")
        ).date()
    except (TypeError, ValueError):
        return RedBarV2StructuralExitResult(
            "NO_ACTION", "REFERENCE_SESSION_UNAVAILABLE"
        )
    if reference_date != completed_date:
        return RedBarV2StructuralExitResult(
            "NO_ACTION", "REFERENCE_SESSION_MISMATCH"
        )

    close = float(completed_1m_close)
    high = float(snapshot.reference_high)
    low = float(snapshot.reference_low)
    exited = 0
    errors: list[str] = []
    triggered = False
    for raw_order in open_orders:
        order = dict(raw_order)
        reason = _exit_reason(order, close=close, high=high, low=low)
        if reason is None:
            continue
        triggered = True
        order_id = str(order.get("order_id") or "")
        if not order_id:
            errors.append("MISSING_ORDER_ID")
            continue
        try:
            close_position(order_id, reason)
            exited += 1
        except Exception as exc:
            errors.append(f"{order_id}:{type(exc).__name__}:{exc}")

    if not triggered:
        return RedBarV2StructuralExitResult(
            "NO_ACTION", "REFERENCE_BOUNDARY_HELD", completed_close=close
        )
    return RedBarV2StructuralExitResult(
        status="EXITED" if exited and not errors else "PARTIAL" if exited else "ERROR",
        reason="RED_BAR_V2_STRUCTURAL_STOP",
        completed_close=close,
        exited_orders=exited,
        errors=tuple(errors),
    )


__all__ = ["RedBarV2StructuralExitResult", "execute_structural_stop_exits"]
