from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import os
from typing import Any, Mapping

import pandas as pd

from red_bar_lab.operations.red_bar_v2_ui_snapshot import (
    persist_red_bar_v2_ui_snapshot,
    read_red_bar_v2_ui_snapshot,
)
from red_bar_lab.services.red_bar_v2_futures_replay_service import (
    run_monitored_red_bar_v2_futures_replay,
)
from red_bar_lab.services.red_bar_v2_live_shadow import (
    submit_latest_live_canonical_shadow,
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
    completed_1m_close: float | None = None
    completed_1m_rsi: float | None = None
    completed_1m_timestamp: str | None = None


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


def _num(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ordered_candles(frame: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    work = frame.copy()
    timestamp_column = next(
        (
            name
            for name in ("timestamp", "date", "datetime", "time")
            if name in work.columns
        ),
        None,
    )
    if timestamp_column is not None:
        work[timestamp_column] = pd.to_datetime(
            work[timestamp_column], errors="coerce"
        )
        work = work.dropna(subset=[timestamp_column]).sort_values(timestamp_column)
    return work.reset_index(drop=True), timestamp_column


def _latest_completed_1m_candle(
    frame: pd.DataFrame,
    *,
    evaluation_time: datetime,
) -> tuple[float | None, float | None, str | None]:
    """Return the latest fully completed one-minute underlying close."""
    work, timestamp_column = _ordered_candles(frame)
    if work.empty or timestamp_column is None or "close" not in work.columns:
        return None, None, None
    timestamps = work[timestamp_column]
    cutoff = pd.Timestamp(evaluation_time).floor("min") - pd.Timedelta(minutes=1)
    try:
        if getattr(timestamps.dt, "tz", None) is not None and cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize(timestamps.dt.tz)
        elif getattr(timestamps.dt, "tz", None) is None and cutoff.tzinfo is not None:
            cutoff = cutoff.tz_localize(None)
    except (TypeError, AttributeError):
        return None, None, None
    completed = work[timestamps <= cutoff]
    if completed.empty:
        return None, None, None
    row = completed.iloc[-1]
    timestamp = row.get(timestamp_column)
    return (
        _num(row.get("close")),
        _rsi14(completed),
        timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
    )


def _rsi14(frame: pd.DataFrame) -> float | None:
    if frame.empty or "close" not in frame.columns:
        return None
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(close) < 15:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(
        alpha=1.0 / 14.0,
        adjust=False,
        min_periods=14,
    ).mean()
    avg_loss = loss.ewm(
        alpha=1.0 / 14.0,
        adjust=False,
        min_periods=14,
    ).mean()
    last_gain = _num(avg_gain.iloc[-1])
    last_loss = _num(avg_loss.iloc[-1])
    if last_gain is None or last_loss is None:
        return None
    if last_loss == 0:
        return 100.0 if last_gain > 0 else 50.0
    rs = last_gain / last_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _latest_vwap(frame: pd.DataFrame) -> float | None:
    required = {"high", "low", "close", "volume"}
    if frame.empty or not required.issubset(frame.columns):
        return None
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    cumulative_volume = volume.cumsum()
    typical = (high + low + close) / 3.0
    vwap = (typical * volume).cumsum() / cumulative_volume.where(
        cumulative_volume != 0
    )
    valid = vwap.dropna()
    return _num(valid.iloc[-1]) if not valid.empty else None


def _reference_geometry(
    index_candles: pd.DataFrame,
    reference_timestamp: object,
) -> tuple[float | None, float | None, str | None]:
    if reference_timestamp in (None, ""):
        return None, None, None
    frame, timestamp_column = _ordered_candles(index_candles)
    if frame.empty or timestamp_column is None:
        return None, None, None
    target = pd.to_datetime(reference_timestamp, errors="coerce")
    if pd.isna(target):
        return None, None, None
    timestamps = frame[timestamp_column]
    try:
        if getattr(timestamps.dt, "tz", None) is not None and target.tzinfo is None:
            target = target.tz_localize(timestamps.dt.tz)
        elif getattr(timestamps.dt, "tz", None) is None and target.tzinfo is not None:
            target = target.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    distances = (timestamps - target).abs()
    if distances.empty or distances.isna().all():
        return None, None, None
    row = frame.loc[distances.idxmin()]
    return (
        _num(row.get("high")),
        _num(row.get("low")),
        row.get(timestamp_column).isoformat()
        if hasattr(row.get(timestamp_column), "isoformat")
        else str(row.get(timestamp_column)),
    )


def _live_market_snapshot_fields(
    *,
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    reference_timestamp: object = None,
) -> dict[str, object]:
    index_frame, index_timestamp_column = _ordered_candles(index_candles)
    futures_frame, futures_timestamp_column = _ordered_candles(futures_candles)

    index_close = (
        _num(index_frame.iloc[-1].get("close"))
        if not index_frame.empty
        else None
    )
    futures_close = (
        _num(futures_frame.iloc[-1].get("close"))
        if not futures_frame.empty
        else None
    )
    index_timestamp = (
        index_frame.iloc[-1].get(index_timestamp_column)
        if not index_frame.empty and index_timestamp_column
        else None
    )
    futures_timestamp = (
        futures_frame.iloc[-1].get(futures_timestamp_column)
        if not futures_frame.empty and futures_timestamp_column
        else None
    )
    reference_high, reference_low, matched_reference_timestamp = (
        _reference_geometry(index_frame, reference_timestamp)
    )
    reference_midpoint = (
        (reference_high + reference_low) / 2.0
        if reference_high is not None and reference_low is not None
        else None
    )
    return {
        "reference_high": reference_high,
        "reference_low": reference_low,
        "reference_midpoint": reference_midpoint,
        "reference_timestamp": matched_reference_timestamp,
        "index_close": index_close,
        "index_rsi": _rsi14(index_frame),
        "futures_close": futures_close,
        "futures_vwap": _latest_vwap(futures_frame),
        "index_timestamp": (
            index_timestamp.isoformat()
            if hasattr(index_timestamp, "isoformat")
            else str(index_timestamp) if index_timestamp is not None else None
        ),
        "futures_timestamp": (
            futures_timestamp.isoformat()
            if hasattr(futures_timestamp, "isoformat")
            else str(futures_timestamp) if futures_timestamp is not None else None
        ),
    }


def _prefer(existing: object, fallback: object) -> object:
    return existing if existing not in (None, "") else fallback


def _restore_live_candidate_when_replay_only_blocked(
    snapshot: Any,
    monitored: Any,
    *,
    active_v2_order_exists: bool,
) -> Any:
    """Ignore replay-synthetic active-trade state for live paper admission."""
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
    """Refresh the paper-mode V2 snapshot from current intraday data."""
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

    evaluated_at = datetime.now().astimezone()
    completed_close, completed_rsi, completed_timestamp = _latest_completed_1m_candle(
        index_candles,
        evaluation_time=evaluated_at,
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
    submit_latest_live_canonical_shadow(
        monitored=monitored,
        settings=settings,
        instrument_key=instrument_key,
        futures_instrument_key=futures_key,
        futures_expiry=(previous.futures_expiry if previous else None),
    )

    snapshot = read_red_bar_v2_ui_snapshot(settings.artifacts_root)
    if snapshot is not None:
        snapshot = _restore_live_candidate_when_replay_only_blocked(
            snapshot,
            monitored,
            active_v2_order_exists=active_v2_order_exists,
        )
        live = _live_market_snapshot_fields(
            index_candles=index_candles,
            futures_candles=futures_candles,
            reference_timestamp=(
                snapshot.reference_timestamp
                or getattr(monitored.replay, "reference_timestamp", None)
            ),
        )
        reference_high = _prefer(snapshot.reference_high, live["reference_high"])
        reference_low = _prefer(snapshot.reference_low, live["reference_low"])
        reference_midpoint = _prefer(
            snapshot.reference_midpoint,
            live["reference_midpoint"],
        )
        persist_red_bar_v2_ui_snapshot(
            replace(
                snapshot,
                mode="PAPER",
                execution_scope="PAPER_TRADING_ONLY",
                reference_high=reference_high,
                reference_low=reference_low,
                reference_midpoint=reference_midpoint,
                reference_timestamp=_prefer(
                    snapshot.reference_timestamp,
                    live["reference_timestamp"],
                ),
                index_close=_prefer(snapshot.index_close, live["index_close"]),
                index_rsi=_prefer(snapshot.index_rsi, live["index_rsi"]),
                futures_close=_prefer(
                    snapshot.futures_close,
                    live["futures_close"],
                ),
                futures_vwap=_prefer(
                    snapshot.futures_vwap,
                    live["futures_vwap"],
                ),
                index_timestamp=_prefer(
                    snapshot.index_timestamp,
                    live["index_timestamp"],
                ),
                futures_timestamp=_prefer(
                    snapshot.futures_timestamp,
                    live["futures_timestamp"],
                ),
                recorded_at=datetime.now().astimezone().isoformat(),
            ),
            artifacts_root=settings.artifacts_root,
        )

    return CurrentSessionV2Result(
        status=(
            "READY"
            if monitored.health.status == "READY"
            else monitored.health.status
        ),
        reason=monitored.health.reason,
        futures_instrument_key=futures_key,
        admitted_candidates=monitored.replay.admitted_candidates,
        closed_trades=monitored.replay.closed_trades,
        completed_1m_close=completed_close,
        completed_1m_rsi=completed_rsi,
        completed_1m_timestamp=completed_timestamp,
    )
