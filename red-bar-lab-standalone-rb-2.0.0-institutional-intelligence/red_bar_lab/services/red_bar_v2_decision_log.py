"""Golden-day decision log for Red Bar V2: one file, the whole day, in order.

The replay answers "what did the strategy decide". This module adds the two
missing columns — the risk plan written before each entry, and the outcome
recorded after each exit — and emits everything as one ordered, deterministic
log. Re-running a day must reproduce the log byte for byte; any difference is
a behaviour change, and the reader decides whether it was intended.

The log is built from three sources, in pipeline order:

1. the futures-aware V2 replay, which owns the state machine and the
   admission gates (untouched),
2. the risk-plan builder, which turns each admitted entry into a sized,
   stopped plan or a machine-readable rejection,
3. the exit policy, which walks the index one-minute bars forward from the
   entry and produces the outcome row.

The stop reads off the index; the entry and every R-multiple are index
quantities. Option premium is deliberately out of scope here: measuring index
R first, then comparing it to premium P&L, is how the basis gap gets quantified
instead of guessed.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time
from typing import Any

import pandas as pd

from red_bar_lab.domain.red_bar_v2 import (
    ExitReason,
    RiskPlan,
    TradeOutcome,
    TriggerResolution,
)
from red_bar_lab.services.red_bar_v2_derived_exits import (
    MISSING_EVIDENCE,
    OPEN_AT_END,
    DerivedExit,
    _align_to_index,
    _to_datetime,
    replay_frame,
    resolve_red_bar_v2_derived_exits,
)
from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
    replay_red_bar_v2_day_with_futures_vwap,
)

DECISION_LOG_SCHEMA = "rbv2.decision_log.v1"

_ENTRY_EVENT = "CANDIDATE_ADMISSION"
_FLAT_STATUS = OPEN_AT_END


_GEOMETRY_FIELDS = (
    "entry_type",
    "trend_strength",
    "governing_reference",
    "zone_position",
    "midpoint_distance_points",
    "working_body_ratio",
)


def _event_row(event: Any) -> dict[str, object]:
    """One gate row, plus the geometry that says which level it was judged on.

    A gate row without the geometry cannot be read: PASS on a Red Bar entry and
    PASS on a working-reference entry mean different things, and the difference
    is only recoverable from ``governing_reference`` and the zone. Absent keys
    are carried as None so every EVENT row has the same shape across days.
    """
    row: dict[str, object] = {
        "kind": "EVENT",
        "timestamp": event.timestamp.isoformat(),
        "event_type": event.event_type,
        "direction": event.direction,
        "admission_code": event.admission_code,
        "candidate_allowed": event.candidate_allowed,
        "trade_id": event.trade_id,
    }
    details = event.details or {}
    for field in _GEOMETRY_FIELDS:
        row[field] = details.get(field)
    return row


def _plan_row(plan: RiskPlan) -> dict[str, object]:
    return {
        "kind": "PLAN",
        "timestamp": plan.entry_timestamp.isoformat(),
        "direction": plan.direction.value,
        "entry_price": plan.entry_price,
        "stop_price": plan.stop_price,
        "target_price": plan.target_price,
        "risk_points": plan.risk_points,
        "reward_multiple": plan.reward_multiple,
        "trigger": plan.trigger.value,
        "trigger_timestamp": plan.trigger_timestamp.isoformat(),
        "trail_activation_price": plan.trail_activation_price,
        "trail_distance_points": plan.trail_distance_points,
        "session_flat_time": plan.session_flat_time.isoformat(),
        "quantity_lots": plan.quantity_lots,
    }


def _outcome_row(outcome: TradeOutcome) -> dict[str, object]:
    """Flatten an outcome into plain JSON types.

    `asdict` keeps `datetime` and enum members intact, which would make the log
    unserialisable and its timestamps incomparable with the ISO strings every
    other row carries.
    """
    row = asdict(outcome)
    row["direction"] = outcome.direction.value
    row["trigger"] = outcome.trigger.value
    row["exit_reason"] = outcome.exit_reason.value
    row["entry_timestamp"] = outcome.entry_timestamp.isoformat()
    row["exit_timestamp"] = outcome.exit_timestamp.isoformat()
    return row


def _trade_record(
    trade_id: str, entry_timestamp: datetime, derived: DerivedExit
) -> dict[str, object]:
    """One trade as the log carries it: the plan, the verdict, the outcome.

    ``status`` appears only when the session ended still holding the position, so
    a reader can tell "no outcome because the policy never closed it" from "no
    outcome because there was never a plan".
    """
    record: dict[str, object] = {
        "trade_id": trade_id,
        "entry_timestamp": entry_timestamp.isoformat(),
        "direction": derived.direction,
        "plan": _plan_row(derived.plan) if derived.plan is not None else None,
        "rejection": derived.rejection,
        "outcome": (
            _outcome_row(derived.outcome) if derived.outcome is not None else None
        ),
    }
    if derived.status == _FLAT_STATUS:
        record["status"] = _FLAT_STATUS
    return record


def build_golden_day_decision_log(
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    *,
    instrument_key: str,
    vwap_instrument_key: str,
    reward_multiple: float | None = None,
    minimum_risk_points: float | None = None,
    maximum_risk_points: float | None = None,
    trail_activation_r: float | None = None,
    session_flat_time: time | None = None,
    trigger_resolution: TriggerResolution = TriggerResolution.LATEST,
) -> dict[str, object]:
    """Replay one day and return the ordered decision log as plain data.

    Every policy knob is an explicit override; defaults come from the domain
    module so the log cannot silently diverge from the live policy.

    The day's exits are resolved first, then fed back into a final replay, so the
    event stream this reads has the policy's own exits in it. Before that, the
    replay had no way to retire a trade row and every day stopped at one entry --
    the plan and the outcome were computed here and thrown away.
    """
    resolution = resolve_red_bar_v2_derived_exits(
        index_candles,
        futures_candles,
        instrument_key=instrument_key,
        vwap_instrument_key=vwap_instrument_key,
        reward_multiple=reward_multiple,
        minimum_risk_points=minimum_risk_points,
        maximum_risk_points=maximum_risk_points,
        trail_activation_r=trail_activation_r,
        session_flat_time=session_flat_time,
        trigger_resolution=trigger_resolution,
    )
    replay, health = replay_red_bar_v2_day_with_futures_vwap(
        index_candles,
        futures_candles,
        instrument_key=instrument_key,
        vwap_instrument_key=vwap_instrument_key,
        exit_timestamps=resolution.exit_timestamps,
    )
    frame = replay_frame(index_candles)
    by_entry = resolution.by_entry()

    rows: list[dict[str, object]] = []
    trades: list[dict[str, object]] = []

    for event in replay.events:
        if event.event_type != _ENTRY_EVENT:
            rows.append(_event_row(event))
            continue

        trade_id = event.trade_id
        rows.append(_event_row(event))
        if not event.candidate_allowed or trade_id is None:
            continue

        entry_timestamp = _align_to_index(
            frame.index, _to_datetime(event.timestamp)
        )
        derived = by_entry.get(entry_timestamp)
        if derived is None:
            # The replay above ran on the same candles and the same exits as the
            # loop's last pass, so every admitted entry it emits was resolved.
            # A gap here means the two disagree, and no row would be honest.
            raise RuntimeError(
                f"no resolved exit for the entry admitted at {entry_timestamp}"
            )

        trades.append(_trade_record(trade_id, entry_timestamp, derived))
        if derived.rejection == MISSING_EVIDENCE:
            continue
        if derived.rejection is not None:
            rows.append({
                "kind": "REJECT",
                "timestamp": entry_timestamp.isoformat(),
                "trade_id": trade_id,
                "rejection": derived.rejection,
                "detail": derived.rejection_detail,
            })
            continue

        rows.append({"kind": "PLAN", "trade_id": trade_id, **_plan_row(derived.plan)})
        if derived.outcome is not None:
            rows.append({
                "kind": "EXIT",
                "timestamp": derived.exit_timestamp.isoformat(),
                "trade_id": trade_id,
                **_outcome_row(derived.outcome),
            })

    entries = [t for t in trades if t["plan"] is not None]
    rejections = [t for t in trades if t["rejection"] not in (None, MISSING_EVIDENCE)]
    outcomes = [t["outcome"] for t in entries if t["outcome"] is not None]
    total_r = round(sum(float(row["r_multiple"]) for row in outcomes), 4)
    by_reason: dict[str, int] = {}
    for row in outcomes:
        reason = ExitReason(row["exit_reason"]).value
        by_reason[reason] = by_reason.get(reason, 0) + 1

    return {
        "schema": DECISION_LOG_SCHEMA,
        "instrument_key": instrument_key,
        "vwap_instrument_key": vwap_instrument_key,
        "trading_date": replay.trading_date,
        "reference": {
            "timestamp": (
                replay.reference_timestamp.isoformat()
                if replay.reference_timestamp is not None
                else None
            ),
            "midpoint": replay.reference_midpoint,
        },
        "vwap_source_health": health.to_dict(),
        "rows": rows,
        "trades": trades,
        "summary": {
            "admitted_entries": len(entries),
            "plans_rejected": len(rejections),
            "outcomes_recorded": len(outcomes),
            "total_r": total_r,
            "exits_by_reason": dict(sorted(by_reason.items())),
            # How many passes the exit loop needed. One per resolved entry, plus
            # the pass that found nothing left to resolve.
            "resolution_passes": resolution.iterations,
        },
    }


def render_decision_log(log: dict[str, object]) -> str:
    """Render the log as stable, diffable text — one line per row."""
    lines = [
        f"SCHEMA {log['schema']}",
        f"DATE {log['trading_date']}  INDEX {log['instrument_key']}  FUTURES {log['vwap_instrument_key']}",
        (
            f"REFERENCE {log['reference']['timestamp']}  midpoint={log['reference']['midpoint']}"
        ),
        "",
    ]
    for row in log["rows"]:
        kind = row["kind"]
        stamp = row["timestamp"]
        if kind == "EVENT":
            verdict = "PASS" if row["candidate_allowed"] else "BLOCK"
            # Governing reference and zone are rendered inline because they
            # change what the verdict means: PASS against the Red Bar and PASS
            # against the deputy were reached through different gates.
            lines.append(
                f"{stamp}  GATE   {row['event_type']:<22} {verdict:<5}"
                f" {row['admission_code'] or '-':<28} dir={row['direction'] or '-'}"
                f" ref={row.get('governing_reference') or '-'}"
                f" zone={row.get('zone_position') or '-'}"
                f" trade={row['trade_id'] or '-'}"
            )
        elif kind == "PLAN":
            # A target is opt-in, so both the price and the multiple can be
            # absent. They are rendered as "-" rather than omitted: a fixed set
            # of columns is what makes two days' logs diffable line by line.
            target = row["target_price"]
            target_text = "-" if target is None else f"{float(target):.2f}"
            reward = row["reward_multiple"]
            reward_text = "-" if reward is None else f"{reward}"
            lines.append(
                f"{stamp}  PLAN   {row['direction']:<7} entry={row['entry_price']:.2f}"
                f" stop={row['stop_price']:.2f} target={target_text}"
                f" risk={row['risk_points']:.2f}R x{reward_text}"
                f" trigger={row['trigger']}@{row['trigger_timestamp']}"
            )
        elif kind == "REJECT":
            lines.append(
                f"{stamp}  REJECT {row['trade_id']} {row['rejection']}: {row['detail']}"
            )
        elif kind == "EXIT":
            sign = "+" if float(row["r_multiple"]) >= 0 else ""
            lines.append(
                f"{stamp}  EXIT   {row['trade_id']} {row['exit_reason']:<13}"
                f" exit={row['exit_price']:.2f} points={row['points']:+.2f}"
                f" R={sign}{row['r_multiple']:.4f}"
                f" mfe={row['mfe_points']:.2f} mae={row['mae_points']:.2f}"
                f" held={row['holding_minutes']:.0f}m"
            )
    summary = log["summary"]
    lines.append("")
    lines.append(
        f"SUMMARY entries={summary['admitted_entries']}"
        f" rejected={summary['plans_rejected']}"
        f" outcomes={summary['outcomes_recorded']}"
        f" total_R={summary['total_r']}"
        f" by_reason={summary['exits_by_reason']}"
    )
    return "\n".join(lines)
