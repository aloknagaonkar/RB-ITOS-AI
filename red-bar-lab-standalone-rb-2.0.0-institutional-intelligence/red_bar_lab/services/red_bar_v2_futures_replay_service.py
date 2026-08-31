from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from red_bar_lab.config import UNDERLYINGS
from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    build_red_bar_v2_futures_snapshot,
)
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


def _latest_timestamp(frame: pd.DataFrame) -> pd.Timestamp | None:
    if frame is None or frame.empty:
        return None
    if "timestamp" in frame.columns:
        values = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True).dropna()
        return pd.Timestamp(values.max()) if not values.empty else None
    if isinstance(frame.index, pd.DatetimeIndex) and len(frame.index):
        return pd.Timestamp(frame.index.max())
    return None


def _extract_trading_date(frame: pd.DataFrame) -> str:
    """Best-effort: return the trading date of the last row in ``frame``
    as an ISO-8601 date string (YYYY-MM-DD). Returns "" when the frame
    is empty, the index is not datetime, and no ``timestamp`` column is
    available. Defensive against RangeIndex / int-only callers.
    """
    if frame is None or frame.empty:
        return ""
    if isinstance(frame.index, pd.DatetimeIndex):
        try:
            return pd.Timestamp(frame.index.max()).date().isoformat()
        except (TypeError, ValueError, AttributeError):
            pass
    for column_name in ("timestamp", "datetime", "candle_timestamp"):
        if column_name in frame.columns:
            try:
                series = pd.to_datetime(frame[column_name], errors="coerce")
                series = series.dropna()
                if not series.empty:
                    return pd.Timestamp(series.iloc[-1]).date().isoformat()
            except (TypeError, ValueError, AttributeError):
                continue
    return ""


def _underlying_name(value: str) -> str:
    """Map an instrument key to the underlying display name used by the
    market trend research PCR history table. Unknown values pass through
    unchanged so callers that already supply a display name keep working."""
    for display_name, key in UNDERLYINGS.items():
        if value == key:
            return display_name
    return value


def _read_latest_pcr_snapshot(
    database: Any,
    underlying: str,
    trading_date: str,
) -> tuple[float | None, float | None]:
    """Read the latest 5m PCR projection's current + morning PCR.

    Returns (current_pcr, morning_pcr). Either may be None if the
    market_trend_research_pcr_5m_history table doesn't have a row for
    the given underlying+trading_date or the payload is missing the
    morning_panel.
    """
    path = getattr(database, "path", None)
    if not path:
        return None, None
    underlying_key = _underlying_name(underlying)
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT payload_json FROM market_trend_research_pcr_5m_history "
                "WHERE underlying=? AND trading_date=? "
                "ORDER BY candle_close_timestamp DESC LIMIT 1",
                (underlying_key, trading_date),
            ).fetchone()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return None, None
    if row is None:
        return None, None
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        return None, None
    current = (payload.get("current_panel") or {}).get("aggregate") or {}
    morning_panel = payload.get("morning_panel") or {}
    morning = (morning_panel.get("aggregate") or {})
    current_pcr = current.get("pcr")
    morning_pcr = morning.get("pcr")
    return (
        float(current_pcr) if isinstance(current_pcr, (int, float)) else None,
        float(morning_pcr) if isinstance(morning_pcr, (int, float)) else None,
    )


def run_monitored_red_bar_v2_futures_replay(
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    *,
    database: Any,
    instrument_key: str,
    vwap_instrument_key: str,
    artifacts_root: str | Path,
    futures_symbol: str | None = None,
    futures_expiry: str | None = None,
    exit_timestamps: Iterable[datetime | pd.Timestamp] = (),
) -> MonitoredRedBarV2FuturesReplayResult:
    """Run monitored replay without acquiring live shadow-persistence authority."""
    trading_date = _extract_trading_date(index_candles)
    pcr_value, morning_pcr_value = _read_latest_pcr_snapshot(
        database=database,
        underlying=instrument_key,
        trading_date=trading_date,
    )
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

    latest_index_timestamp = _latest_timestamp(index_candles)
    if latest_index_timestamp is not None:
        live_context, live_health = build_red_bar_v2_futures_snapshot(
            index_candles,
            futures_candles,
            instrument_key=instrument_key,
            vwap_instrument_key=vwap_instrument_key,
            timeframe="1M",
            evaluation_time=latest_index_timestamp + pd.Timedelta(minutes=1),
            expected_timestamp=latest_index_timestamp,
            pcr_value=pcr_value,
            morning_pcr_value=morning_pcr_value,
        )
        if live_context is not None:
            ui_snapshot = replace(
                ui_snapshot,
                index_close=live_context.candle_close,
                index_rsi=live_context.rsi_value,
                futures_close=live_context.vwap_comparison_price,
                futures_vwap=live_context.vwap_value,
                index_timestamp=live_context.candle_timestamp.isoformat(),
                futures_timestamp=live_context.vwap_source_timestamp.isoformat(),
                alignment_status=live_health.status,
                last_evaluation_timestamp=(
                    latest_index_timestamp + pd.Timedelta(minutes=1)
                ).isoformat(),
            )

    persist_red_bar_v2_ui_snapshot(
        ui_snapshot,
        artifacts_root=artifacts_root,
    )
    return monitored
