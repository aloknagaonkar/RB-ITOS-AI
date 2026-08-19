from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from red_bar_lab.intelligence.red_bar_v2_session_health import (
    RedBarV2SessionVwapHealth,
    build_session_vwap_source_health,
)
from red_bar_lab.operations.red_bar_v2_ui_snapshot import (
    build_red_bar_v2_ui_snapshot_from_replay,
    persist_red_bar_v2_ui_snapshot,
)
from red_bar_lab.operations.red_bar_v2_vwap_source import (
    persist_red_bar_v2_vwap_health,
)
from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
    replay_red_bar_v2_day_with_futures_vwap,
)
from red_bar_lab.services.red_bar_v2_historical_replay import (
    RedBarV2ReplayResult,
)
from red_bar_lab.services.red_bar_v2_lifecycle_validation import (
    ReplayEventEpisode,
    summarize_replay_event_episodes,
)


@dataclass(frozen=True)
class MonitoredRedBarV2FuturesReplayResult:
    replay: RedBarV2ReplayResult
    health: RedBarV2SessionVwapHealth
    health_path: Path
    event_episodes: tuple[ReplayEventEpisode, ...]


def run_monitored_red_bar_v2_futures_replay(
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    *,
    instrument_key: str,
    vwap_instrument_key: str,
    artifacts_root: str | Path,
    futures_symbol: str | None = None,
    futures_expiry: str | None = None,
    exit_timestamps: Iterable[datetime | pd.Timestamp] = (),
) -> MonitoredRedBarV2FuturesReplayResult:
    replay, evaluation_health = replay_red_bar_v2_day_with_futures_vwap(
        index_candles,
        futures_candles,
        instrument_key=instrument_key,
        vwap_instrument_key=vwap_instrument_key,
        exit_timestamps=exit_timestamps,
    )
    session_health = build_session_vwap_source_health(
        index_candles,
        futures_candles,
        instrument_key=instrument_key,
        vwap_instrument_key=vwap_instrument_key,
    )

    if evaluation_health.status != "READY" and session_health.status == "READY":
        session_health = RedBarV2SessionVwapHealth(
            **{
                **session_health.__dict__,
                "status": evaluation_health.status,
                "reason": evaluation_health.reason,
            }
        )

    persisted = persist_red_bar_v2_vwap_health(
        session_health,
        artifacts_root=artifacts_root,
        trading_date=replay.trading_date,
        futures_symbol=futures_symbol,
        futures_expiry=futures_expiry,
    )
    monitored = MonitoredRedBarV2FuturesReplayResult(
        replay=replay,
        health=session_health,
        health_path=persisted,
        event_episodes=summarize_replay_event_episodes(replay),
    )
    ui_snapshot = build_red_bar_v2_ui_snapshot_from_replay(
        monitored,
        futures_instrument_key=vwap_instrument_key,
        futures_symbol=futures_symbol,
        futures_expiry=futures_expiry,
    )
    persist_red_bar_v2_ui_snapshot(
        ui_snapshot,
        artifacts_root=artifacts_root,
    )
    return monitored
