#!/usr/bin/env python3
"""Read-only forensic validation of the current Midpoint live session."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
IMPORTANT = {
    "B_ENTRY",
    "E_ENTRY",
    "C_ENTRY",
    "PM_E_ENTRY",
    "PLUS20_PROOF",
    "RUNNER_CLASSIFICATION",
    "RUNNER_CLASSIFICATION_UNAVAILABLE",
    "MANAGEMENT_ROUTE_SELECTED",
    "NORMAL_B_PROVED_STARTED",
    "NORMAL_B_PROVED_TIER2",
    "NORMAL_B_PROVED_TIER3",
    "NORMAL_B_PROVED_EXIT_CANDIDATE",
    "DEGRADED_STARTED",
    "DEGRADED_EXIT_CANDIDATE_TRIGGERED",
    "STRUCTURAL_TERMINAL",
    "SESSION_END_UNRESOLVED",
}


def fetch(base: str, path: str, *, timeout: float = 30.0) -> tuple[object, dict]:
    started = time.perf_counter()
    url = base.rstrip("/") + path
    try:
        with urlopen(url, timeout=timeout) as response:
            body = response.read()
            result = json.loads(body)
            return result, {
                "url": url,
                "http_status": response.status,
                "elapsed_seconds": time.perf_counter() - started,
                "bytes": len(body),
                "error": None,
            }
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, {
            "url": url,
            "http_status": getattr(exc, "code", None),
            "elapsed_seconds": time.perf_counter() - started,
            "bytes": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }


def rows_from(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("events", "timeline", "rows", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def timestamp(row: dict) -> str:
    return str(
        row.get("event_timestamp")
        or row.get("timestamp")
        or row.get("source_candle_timestamp")
        or ""
    )


def session_rows(payloads: list[object], session_date: str) -> list[dict]:
    selected = {}
    for payload in payloads:
        for row in rows_from(payload):
            ts = timestamp(row)
            if row.get("session_date") != session_date and not ts.startswith(session_date):
                continue
            key = row.get("event_id") or (
                ts,
                row.get("event_type"),
                row.get("reference_type"),
                row.get("result"),
            )
            selected[str(key)] = row
    return sorted(selected.values(), key=lambda row: (timestamp(row), str(row.get("event_type"))))


def pair_segments(events: list[dict]) -> list[tuple[dict, list[dict]]]:
    entries = [
        index for index, row in enumerate(events)
        if row.get("event_type") in {"B_ENTRY", "E_ENTRY", "C_ENTRY", "PM_E_ENTRY"}
    ]
    output = []
    for sequence, index in enumerate(entries):
        end = entries[sequence + 1] if sequence + 1 < len(entries) else len(events)
        output.append((events[index], events[index:end]))
    return output


def first(segment: list[dict], event_types: set[str]) -> dict | None:
    return next((row for row in segment if row.get("event_type") in event_types), None)


def summarize_trade(entry: dict, segment: list[dict]) -> dict:
    proof = first(segment, {"PLUS20_PROOF"})
    classifier = first(segment, {"RUNNER_CLASSIFICATION"})
    unavailable = first(segment, {"RUNNER_CLASSIFICATION_UNAVAILABLE"})
    route = first(segment, {"MANAGEMENT_ROUTE_SELECTED"})
    normal_exit = first(segment, {"NORMAL_B_PROVED_EXIT_CANDIDATE"})
    degraded = first(segment, {"DEGRADED_STARTED"})
    degraded_exit = first(segment, {"DEGRADED_EXIT_CANDIDATE_TRIGGERED"})
    terminal = first(segment, {"STRUCTURAL_TERMINAL", "SESSION_END_UNRESOLVED"})
    exact_classifier = None
    if proof and classifier:
        exact_classifier = (
            datetime.fromisoformat(classifier["event_timestamp"])
            == datetime.fromisoformat(proof["event_timestamp"]) + timedelta(minutes=10)
        )
    exit_event = normal_exit or degraded_exit or terminal
    return {
        "family": entry.get("family"),
        "direction": entry.get("direction"),
        "entry_timestamp": entry.get("event_timestamp"),
        "entry_price": entry.get("underlying_price"),
        "entry_boundary": entry.get("original_boundary"),
        "midpoint": entry.get("midpoint"),
        "plus20_timestamp": proof.get("event_timestamp") if proof else None,
        "plus20_directional_points_close": proof.get("directional_points") if proof else None,
        "classifier_timestamp": classifier.get("event_timestamp") if classifier else None,
        "classifier_result": classifier.get("result") if classifier else None,
        "classifier_exact_proof_plus_10": exact_classifier,
        "classifier_unavailable": unavailable is not None,
        "management_route": route.get("result") if route else None,
        "degraded_timestamp": degraded.get("event_timestamp") if degraded else None,
        "candidate_exit_event": exit_event.get("event_type") if exit_event else None,
        "candidate_exit_timestamp": exit_event.get("event_timestamp") if exit_event else None,
        "candidate_exit_points": exit_event.get("directional_points") if exit_event else None,
        "candidate_exit_reason": exit_event.get("reason") if exit_event else None,
        "current_or_final_state": (
            exit_event.get("state_after") if exit_event else segment[-1].get("state_after")
        ),
    }


def main() -> int:
    now = datetime.now(IST)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8123/api/live-shadow/midpoint-strategy",
    )
    parser.add_argument("--session-date", default=now.date().isoformat())
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    payloads = {}
    transport = {}
    for name, path in (
        ("status", "/status"),
        ("timeline", "/timeline?limit=2000"),
        ("events", "/events?limit=5000"),
    ):
        payloads[name], transport[name] = fetch(arguments.base_url, path)

    if payloads["status"] is None:
        print(json.dumps({"transport": transport}, indent=2))
        raise SystemExit("STOP: Midpoint status endpoint unavailable")

    events = session_rows(
        [payloads["timeline"], payloads["events"]], arguments.session_date
    )
    trades = [summarize_trade(entry, segment) for entry, segment in pair_segments(events)]
    status = payloads["status"] if isinstance(payloads["status"], dict) else {}
    safety = status.get("safety") or {}
    safety_pass = (
        safety.get("observation_only") is True
        and safety.get("execution_enabled") is False
        and safety.get("paper_order_enabled") is False
        and safety.get("quantity") is None
    )
    timestamps = [timestamp(row) for row in events]
    chronology_pass = timestamps == sorted(timestamps)
    event_ids = [row.get("event_id") for row in events if row.get("event_id")]
    duplicate_ids = [key for key, count in Counter(event_ids).items() if count > 1]

    option_observation = None
    option_transport = None
    if trades:
        query = urlencode({
            "session_date": arguments.session_date,
            "as_of": now.replace(second=0, microsecond=0).isoformat(),
        })
        option_observation, option_transport = fetch(
            arguments.base_url, "/option-observation?" + query
        )

    report = {
        "model": "MIDPOINT_LIVE_SESSION_FORENSIC_V1",
        "session_date": arguments.session_date,
        "collected_at": now.isoformat(),
        "status": {
            "family_b_state": status.get("family_b_state"),
            "latest_event": status.get("latest_event"),
            "latest_entry": status.get("latest_entry"),
            "latest_plus20": status.get("latest_plus20"),
            "latest_classifier": status.get("latest_classifier"),
            "latest_degraded": status.get("latest_degraded"),
            "latest_normal_b_proved": status.get("latest_normal_b_proved"),
            "latest_normal_b_tier2": status.get("latest_normal_b_tier2"),
            "latest_normal_b_tier3": status.get("latest_normal_b_tier3"),
            "latest_normal_b_exit": status.get("latest_normal_b_exit"),
            "latest_terminal": status.get("latest_terminal"),
            "workspace": status.get("workspace"),
            "safety": safety,
        },
        "integrity": {
            "safety_pass": safety_pass,
            "chronology_pass": chronology_pass,
            "duplicate_event_ids": duplicate_ids,
            "event_count": len(events),
            "important_event_count": sum(
                row.get("event_type") in IMPORTANT for row in events
            ),
            "all_classifiers_exact_proof_plus_10": all(
                trade["classifier_exact_proof_plus_10"] is not False
                for trade in trades
            ),
        },
        "event_type_counts": dict(Counter(
            str(row.get("event_type")) for row in events
        )),
        "trades": trades,
        "important_events": [
            row for row in events if row.get("event_type") in IMPORTANT
        ],
        "option_observation": option_observation,
        "transport": {**transport, "option_observation": option_transport},
    }
    output = arguments.output or Path(
        "data/live-observation/midpoint-strategy-v1/validation/"
        f"{arguments.session_date}-live-validation.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print("MIDPOINT LIVE SESSION", arguments.session_date, "as of", now.strftime("%H:%M:%S IST"))
    print("state:", report["status"]["family_b_state"])
    print("events:", len(events), "trades:", len(trades))
    print("integrity:", report["integrity"])
    for index, trade in enumerate(trades, start=1):
        print(f"TRADE {index}", json.dumps(trade, sort_keys=True))
    print("transport:")
    for name, result in report["transport"].items():
        print(" ", name, result)
    print("output:", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
