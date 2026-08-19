from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import os
from typing import Any

from red_bar_lab.operations.red_bar_v2_ui_snapshot import (
    persist_red_bar_v2_ui_snapshot,
    read_red_bar_v2_ui_snapshot,
)
from red_bar_lab.services.red_bar_v2_futures_replay_service import (
    run_monitored_red_bar_v2_futures_replay,
)


@dataclass(frozen=True)
class CurrentSessionV2Result:
    status: str
    reason: str
    futures_instrument_key: str | None = None
    admitted_candidates: int = 0
    closed_trades: int = 0


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

    exit_timestamps = []
    for row in database.read_paper_execution_orders("PAPER-STD"):
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
