"""Causal historical health overlay for Midpoint replay sessions.

The overlay is presentation/research evidence only.  It never rewrites the
immutable strategy audit and it reuses the exact live health calculator.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from .entry_health_live_v1 import (
    MidpointEntryHealthLiveV1,
    entry_health_label,
    evaluate_t5_candidates,
)


MODEL = "MIDPOINT_HISTORICAL_HEALTH_OVERLAY_V1"

ENTRY_TYPES = {
    "A_ENTRY", "B_ENTRY", "E_ENTRY", "C_ENTRY", "PM_B_ENTRY", "PM_E_ENTRY",
    "B_REARM_ENTRY", "E_REARM_ENTRY",
}
TERMINAL_TYPES = {
    "STRUCTURAL_TERMINAL", "CAP20_SHADOW_EXIT", "CAP20_RESCUE_TRIGGERED",
}

_EVENT_ORDER = {
    "PRE_ENTRY_HEALTH_SNAPSHOT": 0,
    "ENTRY_HEALTH_SNAPSHOT": 1,
    "CONTINUOUS_HEALTH_CHECK": 2,
    "T5_PROVED_BYPASS": 3,
    "T5_HEALTH_CHECK": 3,
}


def _iso(value: Any) -> datetime:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        raise ValueError("historical health requires timezone-aware timestamps")
    return moment.replace(second=0, microsecond=0)


def _number(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return float(value)
    return None


def _event_id(day: str, event_type: str, timestamp: str, lane: tuple[Any, ...]) -> str:
    raw = "|".join((MODEL, day, event_type, timestamp, *(str(x) for x in lane)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _lane(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("direction"),
        row.get("reference_type"),
        row.get("family"),
        row.get("event_timestamp"),
    )


def _health_event(
    *,
    entry: dict[str, Any],
    timestamp: datetime,
    event_type: str,
    raw: dict[str, Any] | None,
    source_timestamp: datetime | None,
    source_basis: str,
    underlying_close: float | None,
    futures_close: float | None,
    futures_vwap: float | None,
    extra: dict[str, Any] | None = None,
    result: str | None = None,
    reason: str = "CAUSAL_HISTORICAL_DIRECTIONAL_HEALTH",
) -> dict[str, Any]:
    direction = str(entry.get("direction") or "")
    snapshot = (
        {"available": False, "warmup_bars": None}
        if raw is None
        else MidpointEntryHealthLiveV1.directional_snapshot(raw, direction)
    )
    label = entry_health_label(snapshot)
    evidence = {
        **snapshot,
        **label,
        "snapshot_timestamp": source_timestamp.isoformat() if source_timestamp else None,
        "snapshot_basis": source_basis,
        "historical_overlay": True,
        "baseline_lifecycle_unchanged": True,
        "candidate_only": True,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "quantity": None,
        "order_sent": False,
        **(extra or {}),
    }
    lane = _lane(entry)
    entry_price = _number(entry, "underlying_price")
    points = None
    if entry_price is not None and underlying_close is not None:
        points = (
            underlying_close - entry_price
            if direction == "BULLISH"
            else entry_price - underlying_close
            if direction == "BEARISH"
            else None
        )
    return {
        "event_id": _event_id(str(entry.get("session_date")), event_type, timestamp.isoformat(), lane),
        "session_date": entry.get("session_date"),
        "strategy": entry.get("strategy", "MIDPOINT_STRATEGY"),
        "version": entry.get("version", "shadow-v1"),
        "family": entry.get("family"),
        "event_timestamp": timestamp.isoformat(),
        "source_candle_timestamp": timestamp.isoformat(),
        "event_type": event_type,
        "direction": direction,
        "state_before": entry.get("state_after") or "ACTIVE",
        "state_after": entry.get("state_after") or "ACTIVE",
        "result": result or label["health"],
        "reason": reason,
        "underlying_price": underlying_close,
        "directional_points": points,
        "reference_type": entry.get("reference_type"),
        "reference_high": entry.get("reference_high"),
        "reference_low": entry.get("reference_low"),
        "midpoint": entry.get("midpoint"),
        "original_boundary": entry.get("original_boundary"),
        "futures_price": futures_close,
        "futures_vwap": futures_vwap,
        "directional_vwap_value": (
            None
            if futures_close is None or futures_vwap is None
            else (futures_close - futures_vwap) * (1 if direction == "BULLISH" else -1)
        ),
        "evidence": evidence,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "quantity": None,
    }


def calculate_raw_health_series(
    minute_rows: list[dict[str, Any]],
    *,
    engine: MidpointEntryHealthLiveV1 | None = None,
) -> tuple[dict[datetime, dict[str, Any]], MidpointEntryHealthLiveV1]:
    """Calculate sequential raw indicators using completed minutes only."""
    health = engine or MidpointEntryHealthLiveV1()
    output: dict[datetime, dict[str, Any]] = {}
    for row in sorted(minute_rows, key=lambda item: _iso(item["timestamp"])):
        timestamp = _iso(row["timestamp"])
        open_ = _number(row, "underlying_open", "open")
        high = _number(row, "underlying_high", "high")
        low = _number(row, "underlying_low", "low")
        close = _number(row, "underlying_close", "close")
        futures_close = _number(row, "futures_close")
        futures_vwap = _number(row, "futures_vwap")
        if None in (open_, high, low, close, futures_close, futures_vwap):
            continue
        output[timestamp] = health.update(
            timestamp=timestamp,
            open_=float(open_),
            high=float(high),
            low=float(low),
            close=float(close),
            futures_open=_number(row, "futures_open"),
            futures_close=float(futures_close),
            futures_vwap=float(futures_vwap),
            futures_volume=_number(row, "futures_volume", "volume"),
        )
    return output, health


def build_historical_health_overlay(
    *,
    minute_rows: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    engine: MidpointEntryHealthLiveV1 | None = None,
) -> tuple[list[dict[str, Any]], MidpointEntryHealthLiveV1]:
    """Return entry/T+5/continuous health without mutating strategy events."""
    raw_by_time, health_engine = calculate_raw_health_series(minute_rows, engine=engine)
    audit = sorted(enumerate(audit_rows), key=lambda item: (_iso(item[1]["event_timestamp"]), item[0]))
    events_by_time: dict[datetime, list[dict[str, Any]]] = {}
    for _, event in audit:
        events_by_time.setdefault(_iso(event["event_timestamp"]), []).append(event)

    active: dict[tuple[Any, ...], dict[str, Any]] = {}
    plus20: dict[tuple[Any, ...], datetime] = {}
    output: list[dict[str, Any]] = []
    prior_raw: dict[str, dict[str, Any] | None] = {"value": None}
    prior_timestamp: dict[str, datetime | None] = {"value": None}

    for timestamp in sorted(raw_by_time):
        raw = raw_by_time[timestamp]
        minute_events = events_by_time.get(timestamp, [])
        underlying_close = float(raw["close"])
        futures_close = raw.get("futures_close")
        futures_vwap = raw.get("futures_vwap")

        # Existing trades observe the completed close before terminal handling.
        for lane, entry in list(active.items()):
            output.append(_health_event(
                entry=entry,
                timestamp=timestamp,
                event_type="CONTINUOUS_HEALTH_CHECK",
                raw=raw,
                source_timestamp=timestamp,
                source_basis="COMPLETED_ONE_MINUTE_CANDLE",
                underlying_close=underlying_close,
                futures_close=futures_close,
                futures_vwap=futures_vwap,
            ))
            target = _iso(entry["event_timestamp"]) + timedelta(minutes=5)
            if timestamp == target:
                proof_now = any(
                    str(event.get("event_type") or "").upper() == "PLUS20_PROOF"
                    and event.get("direction") == entry.get("direction")
                    and event.get("reference_type") == entry.get("reference_type")
                    for event in minute_events
                )
                proof_at = timestamp if proof_now else plus20.get(lane)
                if proof_at is not None and proof_at <= target:
                    output.append(_health_event(
                        entry=entry, timestamp=timestamp,
                        event_type="T5_PROVED_BYPASS", raw=raw,
                        source_timestamp=timestamp,
                        source_basis="EXACT_ENTRY_PLUS5_COMPLETED_CLOSE",
                        underlying_close=underlying_close,
                        futures_close=futures_close, futures_vwap=futures_vwap,
                        extra={"plus20_timestamp": proof_at.isoformat()},
                        result="BYPASSED",
                        reason="PLUS20_ALREADY_PROVED_BEFORE_OR_AT_T5",
                    ))
                else:
                    decision = evaluate_t5_candidates(
                        MidpointEntryHealthLiveV1.directional_snapshot(raw, str(entry.get("direction")))
                    )
                    output.append(_health_event(
                        entry=entry, timestamp=timestamp,
                        event_type="T5_HEALTH_CHECK", raw=raw,
                        source_timestamp=timestamp,
                        source_basis="EXACT_ENTRY_PLUS5_COMPLETED_CLOSE",
                        underlying_close=underlying_close,
                        futures_close=futures_close, futures_vwap=futures_vwap,
                        extra=decision,
                    ))

        for event in minute_events:
            event_type = str(event.get("event_type") or "").upper()
            if event_type in ENTRY_TYPES:
                lane = _lane(event)
                active[lane] = event
                output.append(_health_event(
                    entry=event, timestamp=timestamp,
                    event_type="PRE_ENTRY_HEALTH_SNAPSHOT",
                    raw=prior_raw["value"],
                    source_timestamp=prior_timestamp["value"],
                    source_basis="PREVIOUS_COMPLETED_ONE_MINUTE_CANDLE",
                    underlying_close=(
                        None if prior_raw["value"] is None
                        else float(prior_raw["value"]["close"])
                    ),
                    futures_close=(
                        None if prior_raw["value"] is None
                        else prior_raw["value"].get("futures_close")
                    ),
                    futures_vwap=(
                        None if prior_raw["value"] is None
                        else prior_raw["value"].get("futures_vwap")
                    ),
                ))
                output.append(_health_event(
                    entry=event, timestamp=timestamp,
                    event_type="ENTRY_HEALTH_SNAPSHOT", raw=raw,
                    source_timestamp=timestamp,
                    source_basis="COMPLETED_ENTRY_CANDLE",
                    underlying_close=underlying_close,
                    futures_close=futures_close, futures_vwap=futures_vwap,
                ))
            elif event_type == "PLUS20_PROOF":
                candidates = [lane for lane, entry in active.items()
                              if entry.get("direction") == event.get("direction")
                              and entry.get("reference_type") == event.get("reference_type")]
                for lane in candidates:
                    plus20[lane] = timestamp
            elif event_type in TERMINAL_TYPES:
                candidates = [lane for lane, entry in active.items()
                              if entry.get("direction") == event.get("direction")
                              and entry.get("reference_type") == event.get("reference_type")]
                for lane in candidates:
                    active.pop(lane, None)
                    plus20.pop(lane, None)

        prior_raw["value"] = raw
        prior_timestamp["value"] = timestamp

    output.sort(key=lambda row: (
        row["event_timestamp"],
        _EVENT_ORDER.get(str(row.get("event_type") or ""), 99),
        row["event_id"],
    ))
    return output, health_engine
