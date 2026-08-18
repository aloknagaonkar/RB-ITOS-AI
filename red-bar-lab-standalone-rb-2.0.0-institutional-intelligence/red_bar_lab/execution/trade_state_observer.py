from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


class TradeLifecycleState(str, Enum):
    FLAT = "FLAT"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CONFLICT = "CONFLICT"


_PENDING_STATUSES = {
    "NEW",
    "PENDING",
    "SIGNALLED",
    "SIGNaled",
    "ENTRY_PENDING",
    "ORDER_PENDING",
    "SUBMITTED",
}
_ACTIVE_STATUSES = {
    "OPEN",
    "ACTIVE",
    "FILLED",
    "ENTERED",
    "ENTRY_FILLED",
    "PARTIALLY_FILLED",
}
_CLOSED_STATUSES = {
    "CLOSED",
    "EXITED",
    "COMPLETE",
    "COMPLETED",
    "STOPPED",
    "STOP_LOSS",
    "STOP_LOSS_HIT",
    "TARGET_HIT",
    "EOD_EXIT",
}
_NON_EXECUTED_TERMINAL_STATUSES = {
    "CANCELLED",
    "CANCELED",
    "REJECTED",
    "EXPIRED",
    "SKIPPED",
}


@dataclass(frozen=True)
class ObservedTrade:
    trade_id: str
    signal_id: str | None
    instrument_key: str | None
    option_side: str | None
    raw_status: str
    lifecycle_state: TradeLifecycleState
    entry_timestamp: datetime | str | None
    exit_timestamp: datetime | str | None
    sequence_timestamp: datetime | str | None
    source: Mapping[str, Any]


@dataclass(frozen=True)
class TradeStateSnapshot:
    lifecycle_state: TradeLifecycleState
    active_trade: ObservedTrade | None
    latest_executed_trade: ObservedTrade | None
    previous_trade_closed: bool
    has_pending_trade: bool
    active_trade_count: int
    pending_trade_count: int
    conflict_reason: str | None = None

    @property
    def is_flat(self) -> bool:
        return self.lifecycle_state in {TradeLifecycleState.FLAT, TradeLifecycleState.CLOSED}

    @property
    def can_admit_new_candidate(self) -> bool:
        return (
            self.active_trade_count == 0
            and self.pending_trade_count == 0
            and self.lifecycle_state != TradeLifecycleState.CONFLICT
            and self.previous_trade_closed
        )


def _value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def _normalise_status(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def classify_trade_status(status: Any, *, exit_timestamp: Any = None) -> TradeLifecycleState:
    normalized = _normalise_status(status)
    if exit_timestamp is not None or normalized in _CLOSED_STATUSES:
        return TradeLifecycleState.CLOSED
    if normalized in _ACTIVE_STATUSES:
        return TradeLifecycleState.ACTIVE
    if normalized in _PENDING_STATUSES:
        return TradeLifecycleState.PENDING
    if normalized in _NON_EXECUTED_TERMINAL_STATUSES or not normalized:
        return TradeLifecycleState.FLAT
    # Unknown statuses are intentionally conservative. They block admission
    # until their meaning is explicitly mapped instead of being treated as flat.
    return TradeLifecycleState.PENDING


def _sequence_value(trade: ObservedTrade) -> tuple[str, str]:
    timestamp = trade.sequence_timestamp
    return (str(timestamp or ""), trade.trade_id)


def observe_trade_state(
    rows: Iterable[Mapping[str, Any]],
    *,
    instrument_key: str | None = None,
) -> TradeStateSnapshot:
    """Build a deterministic, read-only view of the execution lifecycle.

    The observer never writes to the order store and never interprets a
    reversal as an exit. It only reports whether an order is pending, active,
    closed, or structurally conflicting.
    """
    observed: list[ObservedTrade] = []
    for index, row in enumerate(rows):
        row_instrument = _value(row, "instrument_key", "instrument", "underlying")
        if instrument_key is not None and row_instrument not in {None, instrument_key}:
            continue
        status = _normalise_status(_value(row, "status", "order_status", "trade_status"))
        exit_timestamp = _value(row, "exit_timestamp", "closed_at", "exit_time")
        entry_timestamp = _value(row, "entry_timestamp", "entered_at", "entry_time", "created_at")
        sequence_timestamp = _value(
            row,
            "updated_at",
            "exit_timestamp",
            "closed_at",
            "entry_timestamp",
            "entered_at",
            "created_at",
        )
        trade_id = str(_value(row, "trade_id", "order_id", "id") or f"ROW-{index}")
        observed.append(
            ObservedTrade(
                trade_id=trade_id,
                signal_id=_value(row, "signal_id"),
                instrument_key=row_instrument,
                option_side=_value(row, "option_side", "side", "contract_type"),
                raw_status=status,
                lifecycle_state=classify_trade_status(status, exit_timestamp=exit_timestamp),
                entry_timestamp=entry_timestamp,
                exit_timestamp=exit_timestamp,
                sequence_timestamp=sequence_timestamp,
                source=dict(row),
            )
        )

    active = sorted(
        (trade for trade in observed if trade.lifecycle_state == TradeLifecycleState.ACTIVE),
        key=_sequence_value,
    )
    pending = sorted(
        (trade for trade in observed if trade.lifecycle_state == TradeLifecycleState.PENDING),
        key=_sequence_value,
    )
    executed = sorted(
        (
            trade
            for trade in observed
            if trade.lifecycle_state in {TradeLifecycleState.ACTIVE, TradeLifecycleState.CLOSED}
        ),
        key=_sequence_value,
    )
    latest_executed = executed[-1] if executed else None

    if len(active) > 1:
        return TradeStateSnapshot(
            lifecycle_state=TradeLifecycleState.CONFLICT,
            active_trade=active[-1],
            latest_executed_trade=latest_executed,
            previous_trade_closed=False,
            has_pending_trade=bool(pending),
            active_trade_count=len(active),
            pending_trade_count=len(pending),
            conflict_reason="MULTIPLE_ACTIVE_TRADES",
        )

    if active:
        state = TradeLifecycleState.ACTIVE
    elif pending:
        state = TradeLifecycleState.PENDING
    elif latest_executed is not None:
        state = TradeLifecycleState.CLOSED
    else:
        state = TradeLifecycleState.FLAT

    previous_closed = latest_executed is None or latest_executed.lifecycle_state == TradeLifecycleState.CLOSED
    return TradeStateSnapshot(
        lifecycle_state=state,
        active_trade=active[-1] if active else None,
        latest_executed_trade=latest_executed,
        previous_trade_closed=previous_closed,
        has_pending_trade=bool(pending),
        active_trade_count=len(active),
        pending_trade_count=len(pending),
    )


def observe_paper_execution_orders(
    connection: Any,
    *,
    instrument_key: str | None = None,
) -> TradeStateSnapshot:
    """Read legacy paper orders through a DB-API connection without mutation."""
    cursor = connection.execute("SELECT * FROM paper_execution_orders")
    columns: Sequence[str] = [description[0] for description in cursor.description]
    rows = [dict(zip(columns, values)) for values in cursor.fetchall()]
    return observe_trade_state(rows, instrument_key=instrument_key)
