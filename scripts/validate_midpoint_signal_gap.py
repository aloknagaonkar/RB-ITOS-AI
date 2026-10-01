#!/usr/bin/env python3
"""Explain a quiet Midpoint live interval and the first later signal.

The validator is read only.  It acquires the current session's one-minute
NIFTY and front-future candles once, causally replays the observation-only
coordinator into a separate audit file, and compares emitted replay events
with the immutable live audit.  No service, live audit, gate, order, or
quantity is changed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from market_lab.domain import IST
from market_lab.midpoint_strategy.config import live_shadow_config_from_env
from market_lab.midpoint_strategy.entry_health_live_v1 import entry_health_label
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
)
from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1


DEFAULT_AUDIT = Path("data/live-observation/midpoint-strategy-v1/audit.jsonl")
DEFAULT_OUTPUT_ROOT = Path(
    "data/live-observation/midpoint-strategy-v1/validation/signal-gap"
)
ENTRY_TYPES = {
    "B_ENTRY",
    "E_ENTRY",
    "C_ENTRY",
    "B_REARM_ENTRY",
    "E_REARM_ENTRY",
    "PM_B_ENTRY",
    "PM_E_ENTRY",
}
DECISION_TYPES = {
    "OPENING_REFERENCE_CREATED",
    "MIDPOINT_BREAK",
    "BOUNDARY_BREAK",
    "BOUNDARY_CLASSIFIED",
    "BOUNDARY_OWNER_OTHER",
    "B_WATCH_STARTED",
    "B_CONFIRMATION_CHECK",
    "E_ENTRY_BLOCKED",
    "E_SELECTED_BUT_DISABLED",
    "C_BOUNDARY_CLASSIFIED",
    "C_ENTRY_BLOCKED",
    "C_ENTRY_REJECTED",
    "BE_REARM_MIDPOINT_TOUCH_ARMED",
    "BE_REARM_BOUNDARY_CLASSIFIED",
    "BE_REARM_ENTRY_BLOCKED",
    "BE_REARM_ENTRY_REJECTED",
    "B_REARM_WATCH_STARTED",
    "B_REARM_CONFIRMATION_CHECK",
    "PM_REFERENCE_LOCKED",
    "PM_MIDPOINT_BREAK",
    "PM_BOUNDARY_BREAK",
    "PM_BOUNDARY_CLASSIFIED",
    "PM_B_WATCH_STARTED",
    "PM_B_CONFIRMATION_CHECK",
    "PM_ENTRY_BLOCKED",
    "PM_ENTRY_REJECTED",
    "PM_ENTRY_WINDOW_EXPIRED",
    "STRUCTURAL_TERMINAL",
    *ENTRY_TYPES,
}


class StaticSources:
    """Serve one acquired snapshot to every causal replay step."""

    def __init__(self, underlying: list[Any], futures: list[Any]) -> None:
        self.underlying = underlying
        self.futures = futures

    def nifty_intraday_1m(self, *, now: datetime) -> list[Any]:
        del now
        return self.underlying

    def nifty_futures_intraday_1m(self, *, now: datetime) -> list[Any]:
        del now
        return self.futures


def aware(value: Any) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError(f"AWARE_TIMESTAMP_REQUIRED_{value}")
    return result.astimezone(IST).replace(second=0, microsecond=0)


def candle_timestamp(candle: Any) -> datetime:
    return aware(candle.timestamp)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def in_interval(
    event: dict[str, Any], day: date, start: time, end: time
) -> bool:
    raw = event.get("event_timestamp") or event.get("source_candle_timestamp")
    if not raw:
        return False
    stamp = aware(raw)
    return stamp.date() == day and start <= stamp.time() <= end


def event_key(event: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(event.get("event_timestamp") or ""),
        str(event.get("event_type") or ""),
        str(event.get("direction") or ""),
        str(event.get("result") or ""),
    )


def relevant(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [row for row in events if row.get("event_type") in DECISION_TYPES],
        key=event_key,
    )


def gaps(minutes: list[datetime], start: datetime, end: datetime) -> list[str]:
    observed = set(minutes)
    output = []
    cursor = start
    while cursor <= end:
        if cursor not in observed:
            output.append(cursor.strftime("%H:%M"))
        cursor += timedelta(minutes=1)
    return output


def quiet_intervals(events: list[dict[str, Any]], minimum: int = 5) -> list[dict[str, Any]]:
    output = []
    ordered = relevant(events)
    for previous, current in zip(ordered, ordered[1:]):
        left = aware(previous["event_timestamp"])
        right = aware(current["event_timestamp"])
        silence = int((right - left).total_seconds() // 60) - 1
        if silence >= minimum:
            output.append(
                {
                    "after": event_key(previous),
                    "before": event_key(current),
                    "quiet_completed_minutes": silence,
                    "interpretation": (
                        "DATA_PRESENT_BUT_NO_STATE_TRANSITION"
                    ),
                }
            )
    return output


def entry_chain(events: list[dict[str, Any]], entry: dict[str, Any]) -> list[dict[str, Any]]:
    entry_at = aware(entry["event_timestamp"])
    earlier = [row for row in relevant(events) if aware(row["event_timestamp"]) <= entry_at]
    # A short bounded chain is enough to show the state transitions that led
    # to the entry without flooding the terminal with unrelated old events.
    return earlier[-12:]


def compact(event: dict[str, Any]) -> dict[str, Any]:
    evidence = event.get("evidence") or {}
    return {
        "timestamp": event.get("event_timestamp"),
        "event_type": event.get("event_type"),
        "family": event.get("family"),
        "direction": event.get("direction"),
        "result": event.get("result"),
        "reason": event.get("reason"),
        "nifty": event.get("underlying_price"),
        "midpoint": event.get("midpoint"),
        "boundary": event.get("original_boundary"),
        "futures": event.get("futures_price"),
        "futures_vwap": event.get("futures_vwap"),
        "candidate_a_at_boundary": evidence.get("candidate_a_at_boundary"),
        "raw_futures_vwap_diff": evidence.get("raw_futures_vwap_diff"),
        "generation": evidence.get("generation"),
    }


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def health_views(coordinator: MidpointLiveShadowCoordinatorV1) -> dict[str, Any]:
    raw = coordinator.latest_entry_health_raw
    if raw is None:
        return {"BULLISH": None, "BEARISH": None}
    output = {}
    for direction in ("BULLISH", "BEARISH"):
        snapshot = coordinator.entry_health.directional_snapshot(raw, direction)
        output[direction] = {**snapshot, **entry_health_label(snapshot)}
    return output


def reference_views(coordinator: MidpointLiveShadowCoordinatorV1) -> list[dict[str, Any]]:
    state = coordinator.state
    if state is None:
        return []
    output = []
    for key, rr in sorted(state.references.items()):
        watch = rr.runtime.watch
        lifecycle = rr.runtime.lifecycle
        if lifecycle is not None:
            lifecycle_state = lifecycle.state.value
        else:
            lifecycle_state = None
        output.append(
            {
                "key": key,
                "reference_type": rr.reference.reference_type,
                "direction": rr.reference.direction,
                "high": rr.reference.high,
                "low": rr.reference.low,
                "midpoint": rr.reference.midpoint,
                "boundary": rr.reference.boundary,
                "midpoint_seen": rr.midpoint_seen,
                "boundary_seen": rr.boundary_seen,
                "classified_family": rr.runtime.family.value,
                "watch_active": bool(watch and watch.active),
                "watch_boundary_timestamp": (
                    watch.boundary_break_timestamp if watch else None
                ),
                "lifecycle_state": lifecycle_state,
                "entry_timestamp": (
                    lifecycle.entry_timestamp.isoformat() if lifecycle else None
                ),
                "closed": rr.closed,
                "generation": rr.generation,
            }
        )
    return output


def minute_reason(
    emitted: list[dict[str, Any]],
    references: list[dict[str, Any]],
    active_reference: str | None,
) -> str:
    entry = next(
        (row for row in emitted if row.get("event_type") in ENTRY_TYPES), None
    )
    if entry is not None:
        return f"ENTRY_EMITTED:{entry.get('event_type')}"
    if emitted:
        return " | ".join(
            f"{row.get('event_type')}:{row.get('result')}:{row.get('reason')}"
            for row in emitted
        )
    if active_reference:
        return f"ACTIVE_TRADE_MANAGEMENT:{active_reference}"
    open_refs = [row for row in references if not row["closed"]]
    if not open_refs:
        return "WAITING_FOR_FIRST_POST_0915_5M_REFERENCE"
    statuses = []
    for row in open_refs:
        if row["lifecycle_state"]:
            status = f"MANAGING_{row['lifecycle_state']}"
        elif row["watch_active"]:
            status = "WAITING_FOR_B_DELAYED_CONFIRMATION"
        elif not row["midpoint_seen"]:
            status = "WAITING_FOR_CLOSE_BEYOND_MIDPOINT"
        elif not row["boundary_seen"]:
            status = "WAITING_FOR_CLOSE_BEYOND_BOUNDARY"
        else:
            status = "BOUNDARY_CONSUMED_NO_ACTIVE_ENTRY"
        statuses.append(f"{row['key']}={status}")
    return " | ".join(statuses) if statuses else "NO_NEW_STATE_TRANSITION"


def write_minute_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "timestamp", "nifty_open", "nifty_high", "nifty_low", "nifty_close",
        "futures_open", "futures_high", "futures_low", "futures_close",
        "futures_volume", "futures_vwap", "raw_futures_vwap_diff",
        "active_reference", "active_state", "reference_count",
        "event_types", "minute_outcome", "bull_health", "bull_support",
        "bear_health", "bear_support",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            health = row["health"]
            writer.writerow(
                {
                    "timestamp": row["timestamp"],
                    "nifty_open": row["nifty"]["open"],
                    "nifty_high": row["nifty"]["high"],
                    "nifty_low": row["nifty"]["low"],
                    "nifty_close": row["nifty"]["close"],
                    "futures_open": row["futures"]["open"],
                    "futures_high": row["futures"]["high"],
                    "futures_low": row["futures"]["low"],
                    "futures_close": row["futures"]["close"],
                    "futures_volume": row["futures"]["volume"],
                    "futures_vwap": row["futures"]["vwap"],
                    "raw_futures_vwap_diff": row["futures"]["raw_vwap_diff"],
                    "active_reference": row["active_reference"],
                    "active_state": row["active_state"],
                    "reference_count": len(row["references"]),
                    "event_types": ",".join(
                        str(event.get("event_type")) for event in row["events"]
                    ),
                    "minute_outcome": row["minute_outcome"],
                    "bull_health": (health["BULLISH"] or {}).get("health"),
                    "bull_support": (health["BULLISH"] or {}).get("support_count"),
                    "bear_health": (health["BEARISH"] or {}).get("health"),
                    "bear_support": (health["BEARISH"] or {}).get("support_count"),
                }
            )


def main() -> int:
    now = datetime.now(IST)
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-date", type=date.fromisoformat, default=now.date())
    parser.add_argument("--from-time", type=time.fromisoformat, default=time(9, 15))
    parser.add_argument("--to-time", type=time.fromisoformat)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    arguments = parser.parse_args()

    if arguments.session_date != now.date():
        raise SystemExit(
            "STOP: this live signal-gap validator supports today's intraday source only; "
            "use the historical session diagnostic for an earlier date"
        )
    to_time = arguments.to_time or now.time().replace(second=0, microsecond=0)
    if to_time < arguments.from_time:
        raise SystemExit("STOP: --to-time must not be earlier than --from-time")

    load_dotenv(".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN")
    if not token:
        raise SystemExit("STOP: UPSTOX_ACCESS_TOKEN missing")

    live_all = load_jsonl(arguments.audit)
    live_session_events = [
        row for row in live_all
        if str(row.get("session_date") or "") == arguments.session_date.isoformat()
    ]
    live_events = [
        row for row in live_session_events
        if in_interval(row, arguments.session_date, arguments.from_time, to_time)
    ]

    source = UpstoxLiveShadowSourcesV1(token)
    try:
        requested_as_of = datetime.combine(arguments.session_date, to_time, IST)
        underlying = source.nifty_intraday_1m(now=requested_as_of)
        futures = source.nifty_futures_intraday_1m(now=requested_as_of)
    finally:
        source.close()

    latest_allowed = datetime.combine(arguments.session_date, to_time, IST) - timedelta(minutes=1)
    underlying = [
        row for row in underlying
        if candle_timestamp(row).date() == arguments.session_date
        and candle_timestamp(row) <= latest_allowed
    ]
    futures = [
        row for row in futures
        if candle_timestamp(row).date() == arguments.session_date
        and candle_timestamp(row) <= latest_allowed
    ]
    underlying_minutes = sorted({candle_timestamp(row) for row in underlying})
    futures_minutes = sorted({candle_timestamp(row) for row in futures})
    common = sorted(set(underlying_minutes) & set(futures_minutes))
    replay_start = datetime.combine(arguments.session_date, time(9, 15), IST)
    requested_start = datetime.combine(arguments.session_date, arguments.from_time, IST)
    coverage_end = min(latest_allowed, common[-1]) if common else latest_allowed
    missing_underlying = gaps(underlying_minutes, replay_start, coverage_end)
    missing_futures = gaps(futures_minutes, replay_start, coverage_end)

    run_id = now.strftime("%Y%m%dT%H%M%S")
    output = arguments.output_root / f"{arguments.session_date}-{run_id}"
    output.mkdir(parents=True, exist_ok=False)
    replay_audit = output / "replay-audit.jsonl"

    # Ensure the optional OOS collector cannot write during this isolated replay.
    previous_collector = os.environ.get("MIDPOINT_V62_OOS_COLLECTOR_ENABLED")
    os.environ["MIDPOINT_V62_OOS_COLLECTOR_ENABLED"] = "0"
    try:
        config = live_shadow_config_from_env()
        coordinator = MidpointLiveShadowCoordinatorV1(
            market_sources=StaticSources(underlying, futures),
            audit_path=replay_audit,
            config=config,
        )
        minute_trace = []
        underlying_by_minute = {candle_timestamp(row): row for row in underlying}
        futures_by_minute = {candle_timestamp(row): row for row in futures}
        for minute in common:
            if minute < replay_start or minute > coverage_end:
                continue
            before = len(coordinator.engine.journal.read_all())
            process_result = coordinator.process(minute + timedelta(minutes=1))
            journal = coordinator.engine.journal.read_all()
            emitted = journal[before:]
            spot = underlying_by_minute[minute]
            future = futures_by_minute[minute]
            state = coordinator.state
            vwap_pair = state.futures_vwap.get(minute) if state else None
            futures_vwap = vwap_pair[1] if vwap_pair else None
            references = reference_views(coordinator)
            minute_trace.append(
                {
                    "timestamp": minute.isoformat(),
                    "nifty": {
                        "open": float(spot.open),
                        "high": float(spot.high),
                        "low": float(spot.low),
                        "close": float(spot.close),
                        "volume": float(spot.volume or 0.0),
                    },
                    "futures": {
                        "open": float(future.open),
                        "high": float(future.high),
                        "low": float(future.low),
                        "close": float(future.close),
                        "volume": float(future.volume or 0.0),
                        "vwap": futures_vwap,
                        "raw_vwap_diff": (
                            float(future.close) - futures_vwap
                            if futures_vwap is not None else None
                        ),
                    },
                    "processed_total": process_result["processed_total"],
                    "quarantined_late_minutes": process_result[
                        "quarantined_late_minutes"
                    ],
                    "quarantined_revised_futures_minutes": process_result[
                        "quarantined_revised_futures_minutes"
                    ],
                    "active_reference": process_result["active_reference_type"],
                    "active_state": process_result["active_state"],
                    "references": references,
                    "be_rearms": jsonable(state.be_rearm_meta if state else {}),
                    "pm_candidate": jsonable(state.pm_e_candidate if state else None),
                    "health": health_views(coordinator),
                    "events": [compact(row) for row in emitted],
                    "minute_outcome": minute_reason(
                        emitted, references, process_result["active_reference_type"]
                    ),
                }
            )
    finally:
        if previous_collector is None:
            os.environ.pop("MIDPOINT_V62_OOS_COLLECTOR_ENABLED", None)
        else:
            os.environ["MIDPOINT_V62_OOS_COLLECTOR_ENABLED"] = previous_collector

    replay_all = load_jsonl(replay_audit) if replay_audit.exists() else []
    replay_events = [
        row for row in replay_all
        if in_interval(row, arguments.session_date, arguments.from_time, to_time)
    ]
    live_counter = Counter(event_key(row) for row in relevant(live_events))
    replay_counter = Counter(event_key(row) for row in relevant(replay_events))
    only_live = list((live_counter - replay_counter).elements())
    only_replay = list((replay_counter - live_counter).elements())
    entries = [row for row in relevant(live_events) if row.get("event_type") in ENTRY_TYPES]
    if not entries:
        entries = [row for row in relevant(replay_events) if row.get("event_type") in ENTRY_TYPES]

    report = {
        "model": "MIDPOINT_LIVE_SIGNAL_GAP_VALIDATOR_V1",
        "session_date": arguments.session_date.isoformat(),
        "requested_interval": {
            "from": requested_start.isoformat(),
            "to": datetime.combine(arguments.session_date, to_time, IST).isoformat(),
            "latest_completed_minute": latest_allowed.isoformat(),
        },
        "data_coverage": {
            "underlying_minutes": len(underlying_minutes),
            "futures_minutes": len(futures_minutes),
            "common_minutes": len(common),
            "first_common": common[0].isoformat() if common else None,
            "last_common": common[-1].isoformat() if common else None,
            "missing_underlying_minutes": missing_underlying,
            "missing_futures_minutes": missing_futures,
            "continuous_through_requested_interval": (
                not missing_underlying and not missing_futures and coverage_end >= latest_allowed
            ),
        },
        "configuration": jsonable(config),
        "live_event_count": len(live_events),
        "replay_event_count": len(replay_events),
        "minute_trace_count": len(minute_trace),
        "decision_parity": {
            "passed": not only_live and not only_replay,
            "only_live": only_live,
            "only_replay": only_replay,
            "warning": (
                None if not only_live and not only_replay else
                "Live/replay difference may reflect revised broker candles; live audit remains authoritative."
            ),
        },
        "live_decision_events": [compact(row) for row in relevant(live_events)],
        "replay_decision_events": [compact(row) for row in relevant(replay_events)],
        "quiet_intervals": quiet_intervals(live_events or replay_events),
        "entries": [
            {
                "entry": compact(entry),
                "causal_chain": [
                    compact(row)
                    for row in entry_chain(
                        live_session_events if entry in live_events else replay_all,
                        entry,
                    )
                ],
            }
            for entry in entries
        ],
        "interpretation": [
            "A quiet UI interval is not a processing failure when one-minute data is continuous.",
            "No audit event is expected on minutes that do not change the strategy state.",
            "The entry causal chain identifies the exact midpoint, boundary, owner, and confirmation event.",
            "The immutable live audit is authoritative if later broker candles cause replay differences.",
        ],
        "safety": {
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
            "live_audit_modified": False,
        },
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    with (output / "minute-trace.jsonl").open("w") as handle:
        for row in minute_trace:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    with (output / "live-events.jsonl").open("w") as handle:
        for row in sorted(live_events, key=event_key):
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    write_minute_csv(output / "minute-trace.csv", minute_trace)

    print("MIDPOINT SIGNAL-GAP VALIDATION", arguments.session_date)
    print("interval:", arguments.from_time, "to", to_time)
    print("data:", report["data_coverage"])
    print("decision parity:", report["decision_parity"])
    print("\nMINUTE-BY-MINUTE PROCESSING")
    for row in minute_trace:
        stamp = aware(row["timestamp"])
        if stamp.time() < arguments.from_time or stamp.time() > to_time:
            continue
        print(
            stamp.strftime("%H:%M"),
            f"NIFTY O={row['nifty']['open']} H={row['nifty']['high']} "
            f"L={row['nifty']['low']} C={row['nifty']['close']}",
            f"FUT={row['futures']['close']} VWAP={row['futures']['vwap']} "
            f"DIFF={row['futures']['raw_vwap_diff']}",
            f"ACTIVE={row['active_reference']}:{row['active_state']}",
            f"EVENTS={[event['event_type'] for event in row['events']]}",
            f"OUTCOME={row['minute_outcome']}",
        )
    print("\nLIVE DECISION CHRONOLOGY")
    for row in report["live_decision_events"]:
        print(json.dumps(row, sort_keys=True))
    if not report["live_decision_events"]:
        print("  no live decision events in requested interval")
    print("\nQUIET INTERVALS")
    for row in report["quiet_intervals"]:
        print(json.dumps(row, sort_keys=True))
    if not report["quiet_intervals"]:
        print("  none >= 5 minutes between decision events")
    print("\nENTRY CHAINS")
    for item in report["entries"]:
        print("ENTRY", json.dumps(item["entry"], sort_keys=True))
        for row in item["causal_chain"]:
            print(" ", json.dumps(row, sort_keys=True))
    if not report["entries"]:
        print("  no entry through requested end time")
    print("\nOutput:", output / "report.json")
    print("Minute JSONL:", output / "minute-trace.jsonl")
    print("Minute CSV:", output / "minute-trace.csv")
    print("Immutable live-event copy:", output / "live-events.jsonl")
    print("Read only: live audit, services, gates, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
