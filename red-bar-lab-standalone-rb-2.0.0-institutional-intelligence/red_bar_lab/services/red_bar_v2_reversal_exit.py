from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot


REVERSAL_EXIT_REASON = "AUTO_RED_BAR_V2_CONFIRMED_REVERSAL"
_OPEN_STATUSES = {"OPEN", "ACTIVE", "PENDING", "APPROVED", "EXECUTING"}


@dataclass(frozen=True)
class RedBarV2ReversalExitResult:
    status: str
    reason: str
    confirmed_direction: str | None = None
    conflicting_orders: int = 0
    exited_orders: int = 0
    errors: tuple[str, ...] = ()


def confirmed_live_direction(
    snapshot: RedBarV2UISnapshot | None,
) -> str | None:
    """Return the current confirmed Red Bar V2 direction.

    A reversal already admitted by the V2 strategy is authoritative for the
    forced-exit transition. Recomputing direction from a hard RSI-50 split can
    disagree with the strategy's own confirmed reversal rules and leave the
    prior option side open after the strategy has moved to the opposite side.

    For backward-compatible snapshots without an admitted reversal, retain the
    conservative raw RSI, futures-VWAP, and midpoint alignment fallback.
    """
    if snapshot is None:
        return None
    if str(snapshot.alignment_status or "").upper() != "READY":
        return None
    if str(snapshot.trend_strength or "").upper() != "CONFIRMED":
        return None

    admitted_direction = str(snapshot.direction or "").upper()
    reversal_admitted = (
        str(snapshot.reversal_status or "").upper() == "REVERSAL_ADMITTED"
        and snapshot.admission_allowed is True
        and admitted_direction in {"BULLISH", "BEARISH"}
    )
    if reversal_admitted:
        return admitted_direction

    required = (
        snapshot.index_close,
        snapshot.index_rsi,
        snapshot.futures_close,
        snapshot.futures_vwap,
        snapshot.reference_midpoint,
    )
    if any(value is None for value in required):
        return None

    bullish = bool(
        float(snapshot.index_rsi) >= 50.0
        and float(snapshot.futures_close) > float(snapshot.futures_vwap)
        and float(snapshot.index_close) > float(snapshot.reference_midpoint)
    )
    bearish = bool(
        float(snapshot.index_rsi) < 50.0
        and float(snapshot.futures_close) < float(snapshot.futures_vwap)
        and float(snapshot.index_close) < float(snapshot.reference_midpoint)
    )
    if bullish:
        return "BULLISH"
    if bearish:
        return "BEARISH"
    return None


def _is_conflicting_order(
    order: Mapping[str, Any],
    confirmed_direction: str,
) -> bool:
    if str(order.get("execution_strategy_source") or "").upper() != "RED_BAR_V2":
        return False
    if str(order.get("status") or "").upper() not in _OPEN_STATUSES:
        return False
    option_type = str(order.get("option_type") or "").upper()
    return (
        confirmed_direction == "BULLISH" and option_type == "PE"
    ) or (
        confirmed_direction == "BEARISH" and option_type == "CE"
    )


def execute_confirmed_reversal_exits(
    *,
    snapshot: RedBarV2UISnapshot | None,
    open_orders: Iterable[Mapping[str, Any]],
    close_position: Callable[[str, str], Any],
) -> RedBarV2ReversalExitResult:
    """Close conflicting Red Bar V2 paper positions through the paper engine.

    The caller supplies the stable paper-engine close function. No broker order
    API is used and no database row is directly rewritten by this service.
    """
    direction = confirmed_live_direction(snapshot)
    if direction is None:
        return RedBarV2ReversalExitResult(
            status="NO_ACTION",
            reason="V2_CONFIRMED_REVERSAL_UNAVAILABLE",
        )

    conflicting = [
        dict(order)
        for order in open_orders
        if _is_conflicting_order(order, direction)
    ]
    if not conflicting:
        return RedBarV2ReversalExitResult(
            status="NO_ACTION",
            reason="NO_CONFLICTING_RED_BAR_V2_POSITION",
            confirmed_direction=direction,
        )

    exited = 0
    errors: list[str] = []
    for order in conflicting:
        order_id = str(order.get("order_id") or "")
        if not order_id:
            errors.append("MISSING_ORDER_ID")
            continue
        try:
            close_position(order_id, REVERSAL_EXIT_REASON)
            exited += 1
        except Exception as exc:  # fail closed and preserve remaining positions
            errors.append(f"{order_id}:{type(exc).__name__}:{exc}")

    return RedBarV2ReversalExitResult(
        status=("EXITED" if exited and not errors else "PARTIAL" if exited else "ERROR"),
        reason=(
            REVERSAL_EXIT_REASON
            if exited and not errors
            else "REVERSAL_EXIT_PARTIAL"
            if exited
            else "REVERSAL_EXIT_FAILED"
        ),
        confirmed_direction=direction,
        conflicting_orders=len(conflicting),
        exited_orders=exited,
        errors=tuple(errors),
    )
