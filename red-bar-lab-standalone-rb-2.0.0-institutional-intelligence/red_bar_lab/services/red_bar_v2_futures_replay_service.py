from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    RedBarV2VwapSourceHealth,
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


@dataclass(frozen=True)
class MonitoredRedBarV2FuturesReplayResult:
    replay: RedBarV2ReplayResult
    health: RedBarV2VwapSourceHealth
    health_path: Path


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
    replay, health = replay_red_bar_v2_day_with_futures_vwap(
        index_candles,
        futures_candles,
        instrument_key=instrument_key,
        vwap_instrument_key=vwap_instrument_key,
        exit_timestamps=exit_timestamps,
    )
    persisted = persist_red_bar_v2_vwap_health(
        health,
        artifacts_root=artifacts_root,
        trading_date=replay.trading_date,
        futures_symbol=futures_symbol,
        futures_expiry=futures_expiry,
    )
    return MonitoredRedBarV2FuturesReplayResult(
        replay=replay,
        health=health,
        health_path=persisted,
    )
