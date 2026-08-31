from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

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
    # Observational PCR context (overall/morning/combined) seen by the
    # cycle. Never consumed by strategy gates.
    pcr_context: Mapping[str, Any] | None = None


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


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def read_red_bar_v2_pcr_context(
    database: Any,
    underlying: str,
    trading_date: str,
) -> dict[str, Any]:
    """Read the observational PCR context for one cycle.

    Returns overall (current) PCR, morning fixed-level PCR and the
    combined cross-index PCR together with source metadata. All values
    degrade to None when data is unavailable; nothing here influences
    strategy gates.
    """
    context: dict[str, Any] = {
        "overall_pcr": None,
        "overall_direction": None,
        "morning_pcr": None,
        "combined_pcr": None,
        "combined_direction": None,
        "combined_coverage": None,
        "source_timestamp": None,
        "trading_date": trading_date,
    }
    path = getattr(database, "path", None)
    if not path:
        return context
    underlying_name = _underlying_name(underlying)
    row = None
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT overall_pcr, overall_direction, source_timestamp, "
                "payload_json FROM market_trend_research_pcr_5m_history "
                "WHERE underlying=? AND trading_date=? "
                "ORDER BY candle_close_timestamp DESC LIMIT 1",
                (underlying_name, trading_date),
            ).fetchone()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        row = None
    if row is not None:
        try:
            context["overall_pcr"] = float(row["overall_pcr"])
        except (TypeError, ValueError):
            context["overall_pcr"] = None
        context["overall_direction"] = row["overall_direction"]
        context["source_timestamp"] = row["source_timestamp"]
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            payload = {}
        if isinstance(payload, Mapping):
            context["morning_pcr"] = _optional_float(payload.get("morning_pcr"))
            context["combined_pcr"] = _optional_float(
                payload.get("combined_index_pcr")
            )
            combined_direction = payload.get("combined_direction")
            context["combined_direction"] = (
                str(combined_direction) if combined_direction else None
            )
            context["combined_coverage"] = _optional_float(
                payload.get("combined_coverage")
            )
    return context


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
    pcr_context = read_red_bar_v2_pcr_context(
        database=database,
        underlying=instrument_key,
        trading_date=trading_date,
    )
    pcr_value = pcr_context["overall_pcr"]
    morning_pcr_value = pcr_context["morning_pcr"]
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
        pcr_context=pcr_context,
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
