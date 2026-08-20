from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import os
from typing import Any, Mapping

from red_bar_lab.operations.red_bar_v2_ui_snapshot import (
    persist_red_bar_v2_ui_snapshot,
    read_red_bar_v2_ui_snapshot,
)
from red_bar_lab.services.red_bar_v2_futures_replay_service import (
    run_monitored_red_bar_v2_futures_replay,
)


_ACTIVE_ORDER_STATUSES = {
    "OPEN",
    "ACTIVE",
    "PENDING",
    "APPROVED",
    "EXECUTING",
    "PARTIALLY_FILLED",
}
_REPLAY_ONLY_BLOCK_CODES = {
    "ACTIVE_TRADE_BLOCK",
    "PREVIOUS_TRADE_NOT_CLOSED",
}


@dataclass(frozen=True)
class CurrentSessionV2Result:
    status: str
    reason: str
    futures_instrument_key: str | None = None
    admitted_candidates: int = 0
    closed_trades: int = 0


def _active_v2_order_exists(rows: list[Mapping[str, Any]]) -> bool:
    for row in rows:
        if str(row.get("execution_strategy_source") or "").upper() != "RED_BAR_V2":
            continue
        if str(row.get("status") or "").upper() in _ACTIVE_ORDER_STATUSES:
            return True
    return False


def _latest_allowed_admission(events: Any) -> Any | None:
    for event in reversed(list(events or ())):
        if str(getattr(event, "event_type", "")) != "CANDIDATE_ADMISSION":
            continue
        if getattr(event, "candidate_allowed", None) is True:
            return event
    return None


def _restore_live_candidate_when_replay_only_blocked(
    snapshot: Any,
    monitored: Any,
    *,
    active_v2_order_exists: bool,
) -> Any:
    """Ignore replay-synthetic active-trade state for live paper admission.

    Historical replay intentionally models an admitted candidate as an active
    trade until an exit fixture appears. During current-session paper trading,
    persisted paper orders are the execution authority. Therefore a replay-only
    ACTIVE_TRADE_BLOCK must not suppress a fresh candidate when no real V2
    paper order is active.

    Only admission metadata is restored. Live market timestamps, prices, RSI,
    VWAP, and alignment fields already written by the current-session context
    must remain authoritative for the paper-signal freshness gate.
    """
    if active_v2_order_exists:
        return snapshot
    if str(getattr(snapshot, "admission_code", "") or "") not in _REPLAY_ONLY_BLOCK_CODES:
        return snapshot

    event = _latest_allowed_admission(getattr(monitored.replay, "events", ()))
    if event is None:
        return snapshot

    details = getattr(event, "details", None)
    if not isinstance(details, Mapping):
        details = {}
    conditions = details.get("conditions")
    if not isinstance(conditions, Mapping):
        conditions = {}

    return replace(
        snapshot,
        directional_state=str(
            details.get("state")
            or (
                f"CONFIRMED_{getattr(event, 'direction', '')}"
                if details.get("trend_strength") == "CONFIRMED"
                else f"PROVISIONAL_{getattr(event, 'direction', '')}"
            )
        ),
        direction=getattr(event, "direction", None),
        option_side=getattr(event, "option_side", None),
        trade_status="FLAT",
        trade_id=None,
        admission_allowed=True,
        admission_code=str(getattr(event, "admission_code", None) or "V2_ADMITTED"),
        admission_reason=str(
            details.get("admission_reason")
            or "Fresh V2 candidate restored because no real active paper order exists."
        ),
        trend_strength=(
            str(details.get("trend_strength"))
            if details.get("trend_strength")
            else None
        ),
        midpoint_aligned=(
            conditions.get("midpoint_aligned")
            if isinstance(conditions.get("midpoint_aligned"), bool)
            else None
        ),
    )


def evaluate_current_session_red_bar_v2(
    *,
    upstox: Any,
    database: Any,
    settings: Any,
    instrument_key: str,
) -> CurrentSessionV2Result:
    """Refresh the paper-mode V2 snapshot from current intraday data.

    The futures contract is resolved from an explicit environment override or
    the most recent validated V2 snapshot. No broker order API is called here.
    """
    previous = read_red_bar_v2_ui_snapshot(settings.artifacts_root)
    futures_key = (
        os.getenv("NIFTY_FUTURES_INSTRUMENT_KEY", "").strip()
        or (previous.futures_instrument_key if previous else None)
    )
    if not futures_key:
        return CurrentSessionV2Result(
            status="BLOCKED",
            reason="NIFTY_FUTURES_INSTRUMENT_KEY_UNAVAILABLE",
        )

    index_candles = upstox.intraday_candles(instrument_key, interval_minutes=1)
    futures_candles = upstox.intraday_candles(futures_key, interval_minutes=1)
    if index_candles.empty:
        return CurrentSessionV2Result(
            status="WAITING",
            reason="INDEX_INTRADAY_UNAVAILABLE",
            futures_instrument_key=futures_key,
        )
    if futures_candles.empty:
        return CurrentSessionV2Result(
            status="WAITING",
            reason="FUTURES_INTRADAY_UNAVAILABLE",
            futures_instrument_key=futures_key,
        )

    order_rows = list(database.read_paper_execution_orders("PAPER-STD"))
    active_v2_order_exists = _active_v2_order_exists(order_rows)
    exit_timestamps = []
    for row in order_rows:
        if str(row.get("execution_strategy_source") or "").upper() != "RED_BAR_V2":
            continue
        value = row.get("exit_timestamp")
        if value:
            exit_timestamps.append(value)

    monitored = run_monitored_red_bar_v2_futures_replay(
        index_candles,
        futures_candles,
        instrument_key=instrument_key,
        vwap_instrument_key=futures_key,
        artifacts_root=settings.artifacts_root,
        futures_symbol=(previous.futures_symbol if previous else None),
        futures_expiry=(previous.futures_expiry if previous else None),
        exit_timestamps=exit_timestamps,
    )

    snapshot = read_red_bar_v2_ui_snapshot(settings.artifacts_root)
    if snapshot is not None:
        snapshot = _restore_live_candidate_when_replay_only_blocked(
            snapshot,
            monitored,
            active_v2_order_exists=active_v2_order_exists,
        )
        persist_red_bar_v2_ui_snapshot(
            replace(
                snapshot,
                mode="PAPER",
                execution_scope="PAPER_TRADING_ONLY",
                recorded_at=datetime.now().astimezone().isoformat(),
            ),
            artifacts_root=settings.artifacts_root,
        )

    return CurrentSessionV2Result(
        status="READY" if monitored.health.status == "READY" else monitored.health.status,
        reason=monitored.health.reason,
        futures_instrument_key=futures_key,
        admitted_candidates=monitored.replay.admitted_candidates,
        closed_trades=monitored.replay.closed_trades,
    )
