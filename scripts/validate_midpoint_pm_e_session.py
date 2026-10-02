#!/usr/bin/env python3
"""Read-only PM B/E counterfactual validation for the current NSE session.

The validator fetches the same completed NIFTY and front-future one-minute
candles used by the live shadow worker, but replays them through an isolated
coordinator with PM_E enabled.  Its audit is written to a temporary directory;
the live audit, configuration, services and orders are never modified.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from market_lab.domain import IST
from market_lab.midpoint_strategy.config import (
    MidpointShadowConfig,
    live_shadow_config_from_env,
)
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
)
from market_lab.upstox_live_shadow_sources_v1 import (
    UpstoxLiveShadowSourcesV1,
)


PM_EVENT_TYPES = {
    "PM_REFERENCE_LOCKED",
    "PM_MIDPOINT_BREAK",
    "PM_BOUNDARY_CLASSIFIED",
    "PM_B_WATCH_STARTED",
    "PM_B_CONFIRMATION_CHECK",
    "PM_B_ENTRY",
    "PM_E_ENTRY",
    "PM_ENTRY_REJECTED",
    "PM_ENTRY_BLOCKED",
    "PM_ENTRY_WINDOW_EXPIRED",
}


def _implemented_rules() -> dict[str, Any]:
    """Machine-readable registry of the currently implemented Midpoint rules."""
    return {
        "opening_references": {
            "construction": (
                "First RED and first GREEN completed 5-minute structures from "
                "09:20 onward; 09:15-09:19 is ignored."
            ),
            "red": {
                "direction": "BEARISH",
                "midpoint_break": "completed 1m close below midpoint",
                "boundary_break": "completed 1m close below reference low",
                "structural_terminal": "completed 1m close above midpoint",
            },
            "green": {
                "direction": "BULLISH",
                "midpoint_break": "completed 1m close above midpoint",
                "boundary_break": "completed 1m close above reference high",
                "structural_terminal": "completed 1m close below midpoint",
            },
        },
        "boundary_owner": {
            "full_candidate_a": (
                "If Candidate A already exists at the boundary, owner is "
                "OTHER_FRESH_A and no B/E entry is allowed."
            ),
            "candidate_a_vwap": {
                "bearish": (
                    "raw futures-minus-VWAP < -5 now and at least one value "
                    "during current-minus-5m through current was >= -5"
                ),
                "bullish": (
                    "raw futures-minus-VWAP > +5 now and at least one value "
                    "during current-minus-5m through current was <= +5"
                ),
            },
            "E": (
                "No full Candidate A at boundary and directional "
                "futures-VWAP difference > +5; immediate E entry."
            ),
            "B": (
                "No full Candidate A and directional futures-VWAP difference "
                "is not > +5; start delayed B watch."
            ),
        },
        "B_entry": {
            "window_minutes": 10,
            "requirements": [
                "same directional structure remains valid",
                "close remains beyond original boundary",
                "full Candidate A appears within the delayed window",
            ],
            "entry": "completed confirmation candle close",
        },
        "E_entry": {
            "requirements": [
                "confirmed midpoint close break",
                "confirmed original-boundary close break",
                "boundary owner classified E",
            ],
            "entry": "completed boundary-break candle close",
        },
        "BE_REARM": {
            "arm": "intrabar touch of original midpoint during active B/E generation",
            "release": "origin generation must structurally close",
            "trigger": (
                "later completed fresh close beyond original boundary; previous "
                "close must not already be beyond it"
            ),
            "classification": "run canonical B/E boundary owner again",
            "E_result": "immediate E_REARM_ENTRY",
            "B_result": "delayed B watch, then B_REARM_ENTRY only on confirmation",
            "other_result": "reject",
            "same_candle_reentry": False,
            "repeat": "every entered generation may arm exactly one next generation",
        },
        "PM_BE": {
            "reference": "exact completed 12:45-13:14 one-minute range",
            "sequence": [
                "first completed close below/above midpoint sets bearish/bullish direction",
                "both directional midpoint paths may arm before the first boundary is consumed",
                "completed close beyond same-direction PM low/high confirms boundary",
                "run canonical B/E boundary owner",
                "E enters immediately; B starts delayed Candidate-A watch",
            ],
            "midpoint_below": "bearish PM direction",
            "midpoint_above": "bullish PM direction",
            "E_result": "immediate PM_E_ENTRY",
            "B_result": "delayed watch then PM_B_ENTRY on confirmation",
            "entry_cutoff": "no new PM entry at or after 15:15",
            "single_use": True,
            "same_candle_reentry": False,
        },
        "shared_management": {
            "proof": (
                "first completed 1m bar whose favorable intrabar high/low "
                "excursion reaches at least +20 underlying points"
            ),
            "classifier_time": "exact proof timestamp plus 10 minutes",
            "RUNNER_STRENGTHENING": (
                "net close progress from +20 is >0 and directional "
                "futures-VWAP change from proof is >0"
            ),
            "NORMAL_B": "either runner-strengthening condition is not positive",
            "unproved": "retain structural midpoint backstop",
        },
        "RUNNER_DEGRADED_EXIT": {
            "route": "only exact proof+10 RUNNER_STRENGTHENING",
            "trigger": (
                "first completed close with positive giveback from running "
                "favorable excursion and negative prior-minute directional "
                "futures-VWAP change"
            ),
            "underlying_valuation": "DEGRADED_STARTED completed candle close",
            "option_valuation": "next exact option-minute open",
            "candidate_reentry": False,
        },
        "NORMAL_B_PROVED_THREE_TIER": {
            "route": "only exact proof+10 NORMAL_B",
            "tier1": "MFE <=30: no floor; structural midpoint backstop",
            "tier2": "MFE >30: static +15 close-profit floor",
            "tier3": (
                "MFE >45: floor=max(previous floor, highest closed profit "
                "since Tier 3 minus 10)"
            ),
            "floor_exit": "strict completed close below active floor at actual close",
            "target": "later intrabar +50 touch; assumed exact +50 research fill",
            "inactivity": (
                "after 30 minutes without a new MFE, schedule exit at the next "
                "exact completed-minute close"
            ),
            "reentry": False,
        },
        "legacy_runner_backstop": {
            "degraded_recovery": "completed close strictly retakes degraded target",
            "CAP20": (
                "first eligible rebreak below degraded target at least 10 minutes "
                "after recovery; rescue only when directional points <=20"
            ),
            "post_rescue_reentry_enabled": False,
        },
        "live_gates_expected": {
            "B": True,
            "E": True,
            "BE_REARM": True,
            "C": False,
            "D": False,
            "PM_E": False,
        },
        "safety": {
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        },
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate today's PM B/E rules without changing live state."
    )
    parser.add_argument(
        "--session-date",
        default=datetime.now(IST).date().isoformat(),
        help="Current NSE session date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--as-of",
        help=(
            "Optional timezone-aware replay cutoff. Defaults to current IST "
            "time. Example: 2026-09-30T14:15:00+05:30"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON report path.",
    )
    return parser.parse_args()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _event_time(event: dict[str, Any]) -> str | None:
    return (
        event.get("event_timestamp")
        or event.get("source_candle_timestamp")
        or event.get("timestamp")
    )


def _pm_stage(events: list[dict[str, Any]]) -> tuple[str, str]:
    by_type = {event.get("event_type"): event for event in events}
    if "PM_B_ENTRY" in by_type:
        return "ENTERED_PM_B", "PM boundary classified B and delayed confirmation entered."
    if "PM_E_ENTRY" in by_type:
        return "ENTERED_PM_E", "PM boundary classified E and entered immediately."
    if "PM_ENTRY_WINDOW_EXPIRED" in by_type:
        return "EXPIRED", "PM entry window ended at 15:15 without an entry."
    if "PM_ENTRY_BLOCKED" in by_type:
        event = by_type["PM_ENTRY_BLOCKED"]
        return "BLOCKED", str(event.get("reason") or "PM_ENTRY_BLOCKED")
    if "PM_ENTRY_REJECTED" in by_type:
        event = by_type["PM_ENTRY_REJECTED"]
        return "REJECTED", str(event.get("reason") or "PM_ENTRY_REJECTED")
    checks = [
        event for event in events
        if event.get("event_type") == "PM_B_CONFIRMATION_CHECK"
    ]
    if checks:
        event = checks[-1]
        return (
            "PM_B_WATCH",
            f"latest delayed B result={event.get('result')} reason={event.get('reason')}",
        )
    if "PM_B_WATCH_STARTED" in by_type:
        return "PM_B_WATCH", "PM boundary classified B; delayed confirmation is active."
    if "PM_BOUNDARY_CLASSIFIED" in by_type:
        event = by_type["PM_BOUNDARY_CLASSIFIED"]
        return (
            "CLASSIFIED_NO_ENTRY",
            f"owner={event.get('result')} with no PM entry event",
        )
    if "PM_MIDPOINT_BREAK" in by_type:
        return (
            "WAITING_BOUNDARY_BREAK",
            "PM direction is established; waiting for the same-direction boundary close.",
        )
    if "PM_REFERENCE_LOCKED" in by_type:
        return (
            "WAITING_MIDPOINT_BREAK",
            "12:45-13:14 PM range is locked; waiting for a close below/above midpoint.",
        )
    return (
        "REFERENCE_NOT_LOCKED",
        "The exact 12:45-13:14 completed-minute window was not available at the cutoff.",
    )


def _reference(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    locked = next(
        (event for event in events if event.get("event_type") == "PM_REFERENCE_LOCKED"),
        None,
    )
    if locked is None:
        return None
    evidence = locked.get("evidence") or {}
    return {
        "start": "12:45",
        "end": "13:14",
        "rows": evidence.get("reference_row_count"),
        "high": evidence.get("reference_high"),
        "low": evidence.get("reference_low"),
        "midpoint": evidence.get("reference_midpoint"),
    }


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    evidence = event.get("evidence") or {}
    return {
        "timestamp": _event_time(event),
        "event_type": event.get("event_type"),
        "direction": event.get("direction"),
        "result": event.get("result"),
        "reason": event.get("reason"),
        "underlying_price": event.get("underlying_price"),
        "futures_price": event.get("futures_price"),
        "futures_vwap": event.get("futures_vwap"),
        "candidate_a_at_boundary": evidence.get("candidate_a_at_boundary"),
        "midpoint_break_timestamp": evidence.get("midpoint_break_timestamp"),
        "boundary_break_timestamp": evidence.get("boundary_break_timestamp"),
        "order_sent": evidence.get("order_sent", False),
    }


def _parse_as_of(raw: str | None) -> datetime:
    if raw is None:
        return datetime.now(IST)
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise SystemExit("STOP: --as-of must include a timezone offset")
    return parsed.astimezone(IST)


def main() -> int:
    arguments = _arguments()
    session_date = date.fromisoformat(arguments.session_date)
    as_of = _parse_as_of(arguments.as_of)
    current_session = datetime.now(IST).date()
    if session_date != current_session:
        raise SystemExit(
            "STOP: this validator uses the Upstox intraday endpoints and only "
            f"supports the current session {current_session.isoformat()}"
        )
    if as_of.date() != session_date:
        raise SystemExit("STOP: --as-of date must equal --session-date")

    load_dotenv(".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token:
        raise SystemExit("STOP: UPSTOX_ACCESS_TOKEN is unavailable")

    live_config = live_shadow_config_from_env()
    replay_config = MidpointShadowConfig(
        family_c_enabled=False,
        be_rearm_enabled=True,
        pm_e_enabled=True,
        family_d_enabled=False,
        post_rescue_reentry_enabled=False,
    )
    replay_config.assert_safe()

    sources = UpstoxLiveShadowSourcesV1(token)
    try:
        with tempfile.TemporaryDirectory(prefix="midpoint-pm-e-validation-") as temp:
            audit_path = Path(temp) / "audit.jsonl"
            coordinator = MidpointLiveShadowCoordinatorV1(
                market_sources=sources,
                audit_path=audit_path,
                config=replay_config,
            )
            process_result = coordinator.process(as_of)
            all_events = _load_jsonl(audit_path)
            pm_events = [
                event
                for event in all_events
                if event.get("event_type") in PM_EVENT_TYPES
            ]
            stage, interpretation = _pm_stage(pm_events)
            candidate = (
                coordinator.state.pm_e_candidate
                if coordinator.state is not None
                else None
            )
            report = {
                "model": "MIDPOINT_PM_BE_CURRENT_SESSION_VALIDATION_V2",
                "session_date": session_date.isoformat(),
                "as_of": as_of.isoformat(),
                "data_source": "UPSTOX_INTRADAY_NIFTY_AND_FRONT_FUTURE_1M",
                "live_gate": {
                    "pm_e_enabled": live_config.pm_e_enabled,
                    "be_rearm_enabled": live_config.be_rearm_enabled,
                    "family_c_enabled": live_config.family_c_enabled,
                },
                "isolated_replay_gate": {
                    "pm_e_enabled": True,
                    "be_rearm_enabled": True,
                    "family_c_enabled": False,
                },
                "implemented_rules": _implemented_rules(),
                "process": process_result,
                "pm_reference": _reference(pm_events),
                "candidate_state": (
                    {
                        "state": candidate.state,
                        "direction": candidate.direction,
                        "bearish_midpoint_break_timestamp": (
                            candidate.bearish_midpoint_break_timestamp.isoformat()
                            if candidate.bearish_midpoint_break_timestamp else None
                        ),
                        "bullish_midpoint_break_timestamp": (
                            candidate.bullish_midpoint_break_timestamp.isoformat()
                            if candidate.bullish_midpoint_break_timestamp else None
                        ),
                        "boundary_break_timestamp": (
                            candidate.boundary_break_timestamp.isoformat()
                            if candidate.boundary_break_timestamp else None
                        ),
                    }
                    if candidate is not None else None
                ),
                "stage": stage,
                "interpretation": interpretation,
                "pm_events": [_compact_event(event) for event in pm_events],
                "safety": {
                    "observation_only": True,
                    "execution_enabled": False,
                    "paper_order_enabled": False,
                    "quantity": None,
                    "order_sent": False,
                    "live_audit_modified": False,
                    "services_restarted": False,
                },
            }
    finally:
        sources.close()

    output = arguments.output or Path(
        "data/live-observation/midpoint-strategy-v1/validation/"
        f"{session_date.isoformat()}-pm-e-validation.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(
        f"PM B/E SESSION {report['session_date']} as of {report['as_of']}"
    )
    print("live gate:", report["live_gate"])
    print("isolated replay:", report["isolated_replay_gate"])
    print("reference:", report["pm_reference"])
    print("stage:", report["stage"])
    print("interpretation:", report["interpretation"])
    print("events:", len(report["pm_events"]))
    for event in report["pm_events"]:
        print(
            event["timestamp"],
            event["event_type"],
            "direction=", event["direction"],
            "result=", event["result"],
            "reason=", event["reason"],
            "NIFTY=", event["underlying_price"],
        )
    print("safety:", report["safety"])
    print("output:", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
