from __future__ import annotations

from red_bar_lab.observability import record_strategy_subcheck

from dataclasses import dataclass, replace
from datetime import datetime
import os
from time import perf_counter
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
    build_latest_live_correlation_id,
    submit_latest_live_canonical_shadow,
)
from red_bar_lab.services.red_bar_v2_market_data_evidence import (
    CandlePullEvidence,
    build_candle_pull_evidence,
)
from red_bar_lab.utils import safe_float


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
    market_data_evidence: tuple[CandlePullEvidence, ...] = ()
    session_health: Mapping[str, Any] | None = None
    candidate_events_scanned: int = 0
    latest_admission: Mapping[str, Any] | None = None
    rule_state: Mapping[str, Any] | None = None


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
        safe_float(row.get("close")),
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
    last_gain = safe_float(avg_gain.iloc[-1])
    last_loss = safe_float(avg_loss.iloc[-1])
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
    return safe_float(valid.iloc[-1]) if not valid.empty else None


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
        safe_float(row.get("high")),
        safe_float(row.get("low")),
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
        safe_float(index_frame.iloc[-1].get("close"))
        if not index_frame.empty
        else None
    )
    futures_close = (
        safe_float(futures_frame.iloc[-1].get("close"))
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
        admission_timestamp=(
            event.timestamp.isoformat()
            if hasattr(event.timestamp, "isoformat")
            else str(event.timestamp)
        ),
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
    futures_instrument_key: str | None = None,
    futures_symbol: str | None = None,
    futures_expiry: str | None = None,
    require_resolved_futures: bool = False,
    run_id: str | None = None,
) -> CurrentSessionV2Result:
    """Refresh the paper-mode V2 snapshot from current intraday data."""
    previous = read_red_bar_v2_ui_snapshot(settings.artifacts_root)
    if require_resolved_futures and not str(futures_instrument_key or "").strip():
        return CurrentSessionV2Result(
            status="BLOCKED",
            reason="ACTIVE_NIFTY_FUTURES_CONTRACT_UNAVAILABLE",
        )
    futures_key = (
        str(futures_instrument_key or "").strip()
        or os.getenv("NIFTY_FUTURES_INSTRUMENT_KEY", "").strip()
        or (previous.futures_instrument_key if previous else None)
    )
    if not futures_key:
        return CurrentSessionV2Result(
            status="BLOCKED",
            reason="NIFTY_FUTURES_INSTRUMENT_KEY_UNAVAILABLE",
        )

    index_requested = datetime.now().astimezone()
    pull_started = perf_counter()
    index_candles = upstox.intraday_candles(instrument_key, interval_minutes=1)
    index_received = datetime.now().astimezone()
    index_evidence = build_candle_pull_evidence(
        index_candles,
        dataset="NIFTY_INDEX_1M",
        instrument_key=instrument_key,
        requested_at=index_requested,
        received_at=index_received,
        duration_ms=(perf_counter() - pull_started) * 1000.0,
    )
    futures_requested = datetime.now().astimezone()
    pull_started = perf_counter()
    futures_candles = upstox.intraday_candles(futures_key, interval_minutes=1)
    futures_received = datetime.now().astimezone()
    futures_evidence = build_candle_pull_evidence(
        futures_candles,
        dataset="NIFTY_FUTURES_1M",
        instrument_key=futures_key,
        requested_at=futures_requested,
        received_at=futures_received,
        duration_ms=(perf_counter() - pull_started) * 1000.0,
    )
    market_data_evidence = (index_evidence, futures_evidence)
    if index_candles.empty:
        return CurrentSessionV2Result(
            status="WAITING",
            reason="INDEX_INTRADAY_UNAVAILABLE",
            futures_instrument_key=futures_key,
            market_data_evidence=market_data_evidence,
        )
    if futures_candles.empty:
        return CurrentSessionV2Result(
            status="WAITING",
            reason="FUTURES_INTRADAY_UNAVAILABLE",
            futures_instrument_key=futures_key,
            market_data_evidence=market_data_evidence,
        )

    evaluated_at = datetime.now().astimezone()
    completed_close, completed_rsi, completed_timestamp = _latest_completed_1m_candle(
        index_candles,
        evaluation_time=evaluated_at,
    )
    record_strategy_subcheck(
        database,
        run_id=run_id,
        step_name="latest_completed_1m_candle",
        artifacts={
            "candle_close": completed_close,
            "candle_rsi_14": completed_rsi,
            "candle_timestamp": (
                completed_timestamp.isoformat()
                if completed_timestamp is not None
                and hasattr(completed_timestamp, "isoformat")
                else completed_timestamp
            ),
        },
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
        database=database,
        instrument_key=instrument_key,
        vwap_instrument_key=futures_key,
        artifacts_root=settings.artifacts_root,
        futures_symbol=(futures_symbol or (previous.futures_symbol if previous else None)),
        futures_expiry=(futures_expiry or (previous.futures_expiry if previous else None)),
        exit_timestamps=exit_timestamps,
    )
    # Surface the strategy's candidate scan as a sub-step. The
    # ``monitored`` object holds the events the strategy engine
    # produced (initial_displacement, reversal, midpoint_upgrade).
    candidate_events = list(getattr(monitored.replay, "events", []) or [])
    record_strategy_subcheck(
        database,
        run_id=run_id,
        step_name="candidate_scan",
        artifacts={
            "candidate_count": len(candidate_events),
            "candidate_event_types": sorted(
                {str(getattr(e, "event_type", "?")) for e in candidate_events}
            ),
        },
    )
    # Surface the most recent admission decision, if any.
    latest_admission = _latest_allowed_admission(candidate_events)
    if latest_admission is not None:
        # Pull the per-boolean conditions and decision metadata out
        # of the underlying ``RedBarV2DirectionDecision`` so we can
        # both surface them in the admission_decision artifact and
        # write one evidence row per boolean check.
        details = getattr(latest_admission, "details", None)
        if not isinstance(details, Mapping):
            details = {}
        conditions = details.get("conditions")
        if not isinstance(conditions, Mapping):
            conditions = {}
        event_type = str(getattr(latest_admission, "event_type", "—"))
        direction = str(getattr(latest_admission, "direction", "—"))
        option_side = getattr(latest_admission, "option_side", None)
        entry_type = (
            details.get("entry_type")
            if isinstance(details.get("entry_type"), str)
            else None
        )
        trend_strength = (
            details.get("trend_strength")
            if isinstance(details.get("trend_strength"), str)
            else None
        )
        reason_text = (
            details.get("admission_reason")
            or details.get("state")
            or "—"
        )
        # Write the consolidated admission-decision row.
        record_strategy_subcheck(
            database,
            run_id=run_id,
            step_name="admission_decision",
            artifacts={
                "event_type": event_type,
                "direction": direction,
                "option_side": option_side,
                "entry_type": entry_type,
                "trend_strength": trend_strength,
                "outcome": str(
                    getattr(latest_admission, "candidate_allowed", None)
                ),
                "candidate_score": getattr(latest_admission, "score", None),
                "reason": str(reason_text),
            },
        )
        # Write one row per gate. The 5 boolean gates are now:
        # - reference_ready (gating)
        # - context_fresh (gating)
        # - vwap_aligned (gating, combined with RedBar reference)
        # - midpoint_aligned (gating, alias for RedBar reference)
        # - rsi_aligned is now informational; we don't gate on it
        # ReplayEvent.details["conditions"] carries the per-gate booleans
        # from the admission evaluator. The flat fields (pcr_value, etc.)
        # are also placed on the ReplayEvent by the replay builder.
        conditions = (
            details.get("conditions")
            if isinstance(details.get("conditions"), Mapping)
            else {}
        )
        gate_map = {
            "reference_ready": (
                bool(conditions.get("reference_ready", False)),
                {
                    "passed": conditions.get("reference_ready", False),
                    "state": conditions.get("trade_state"),
                },
            ),
            "context_fresh": (
                bool(conditions.get("context_fresh", False)),
                {"passed": conditions.get("context_fresh", False)},
            ),
            "vwap_aligned": (
                bool(conditions.get("vwap_aligned", False)),
                {"passed": conditions.get("vwap_aligned", False)},
            ),
            "midpoint_aligned": (
                bool(conditions.get("midpoint_aligned", False)),
                {"passed": conditions.get("midpoint_aligned", False)},
            ),
            "rsi_informational": (
                True,  # informational; always "passed" in audit terms
                {
                    "passed": True,
                    "rsi_value": conditions.get("rsi_aligned"),
                },
            ),
        }
        for check_name, (passed, artifact) in gate_map.items():
            record_strategy_subcheck(
                database,
                run_id=run_id,
                step_name=f"check:{check_name}",
                status="OK" if passed else "ERROR",
                artifacts=artifact,
            )
        # Mid-session 12:45-1:15 rule (only fires if the rule is active)
        if details.get("mid_session_active", False):
            mid_passed = details.get("mid_session_passed")
            record_strategy_subcheck(
                database,
                run_id=run_id,
                step_name="check:mid_session",
                status=(
                    "OK"
                    if mid_passed is True
                    else "ERROR"
                    if mid_passed is False
                    else "RUNNING"
                ),
                artifacts={
                    "passed": mid_passed,
                    "reason": details.get("mid_session_reason"),
                    "candle_timestamp": str(details.get("context_timestamp")),
                },
            )
        # PCR (informational) — both current and morning, always shown
        # if the strategy engine recorded them.
        pcr_value = details.get("pcr_value")
        morning_pcr = details.get("morning_pcr_value")
        if pcr_value is not None or morning_pcr is not None:
            shift = None
            if (
                isinstance(pcr_value, (int, float))
                and isinstance(morning_pcr, (int, float))
            ):
                shift = round(float(pcr_value) - float(morning_pcr), 4)
            record_strategy_subcheck(
                database,
                run_id=run_id,
                step_name="check:pcr_informational",
                status="OK",
                artifacts={
                    "passed": True,
                    "current_pcr": pcr_value,
                    "morning_pcr": morning_pcr,
                    "shift": shift,
                },
            )
    correlation_id = build_latest_live_correlation_id(
        monitored=monitored,
        instrument_key=instrument_key,
    )
    submit_latest_live_canonical_shadow(
        monitored=monitored,
        settings=settings,
        instrument_key=instrument_key,
        futures_instrument_key=futures_key,
        futures_expiry=(futures_expiry or (previous.futures_expiry if previous else None)),
        run_id=run_id,
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
                correlation_id=correlation_id,
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
                futures_instrument_key=futures_key,
                futures_symbol=(futures_symbol or snapshot.futures_symbol),
                futures_expiry=(futures_expiry or snapshot.futures_expiry),
                recorded_at=datetime.now().astimezone().isoformat(),
            ),
            artifacts_root=settings.artifacts_root,
        )

    admission_summary: Mapping[str, Any] | None = None
    if latest_admission is not None:
        admission_details = getattr(latest_admission, "details", None)
        admission_details = (
            admission_details if isinstance(admission_details, Mapping) else {}
        )
        admission_summary = {
            "event_type": str(getattr(latest_admission, "event_type", "") or ""),
            "direction": str(getattr(latest_admission, "direction", "") or ""),
            "option_side": getattr(latest_admission, "option_side", None),
            "entry_type": admission_details.get("entry_type"),
            "trend_strength": admission_details.get("trend_strength"),
            "admission_code": str(
                getattr(latest_admission, "admission_code", "") or ""
            ),
            "admission_reason": str(admission_details.get("admission_reason") or ""),
            "candidate_allowed": bool(
                getattr(latest_admission, "candidate_allowed", False)
            ),
            "score": getattr(latest_admission, "score", None),
        }

    health = monitored.health
    health_to_dict = getattr(health, "to_dict", None)
    session_health: Mapping[str, Any] = (
        health_to_dict()
        if callable(health_to_dict)
        else {
            "status": getattr(health, "status", None),
            "reason": getattr(health, "reason", None),
        }
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
        market_data_evidence=market_data_evidence,
        session_health=session_health,
        candidate_events_scanned=len(candidate_events),
        latest_admission=admission_summary,
        rule_state=getattr(monitored.replay, "rule_state", None),
    )