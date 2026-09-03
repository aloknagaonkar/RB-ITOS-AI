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
    Bar,
    Direction,
    ExitReason,
    RiskPlan,
    RiskPlanRejected,
    TradeOutcome,
    TriggerResolution,
    advance,
    build_risk_plan,
    find_stop_trigger,
    open_position,
)
from red_bar_lab.intelligence.market_context import session_vwap
from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
    replay_red_bar_v2_day_with_futures_vwap,
)
from red_bar_lab.strategy.red_bar_v2_working_reference import structure_failed

DECISION_LOG_SCHEMA = "rbv2.decision_log.v1"

_ENTRY_EVENT = "CANDIDATE_ADMISSION"
_FLAT_STATUS = "OPEN_AT_END"


def _to_datetime(value: Any) -> datetime:
    """Accept the datetime shapes the replay emits and return a bare datetime."""
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed
    raise TypeError(f"unsupported timestamp: {value!r}")


def _align_to_index(frame_index: pd.DatetimeIndex, stamp: datetime) -> datetime:
    """Match the frame clock: naive stays naive, aware is stripped after check."""
    if frame_index.tz is None:
        return stamp.replace(tzinfo=None)
    return stamp


def _five_minute_bars(frame: pd.DataFrame) -> list[Bar]:
    """Aggregate one-minute OHLCV into five-minute bars, stamped at slot start."""
    aggregated = frame.resample("5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["close"])
    return [
        Bar(
            timestamp=stamp.to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for stamp, row in aggregated.iterrows()
    ]


def _bars_known_at(frame: pd.DataFrame, entry_timestamp: datetime) -> list[Bar]:
    """Five-minute bars as they stood at the entry minute, last one partial.

    The entry fires on a one-minute close, so the 5-minute slot that crossed the
    reference level is still open when the stop is priced: an entry at 09:31 sits
    inside the 09:30-09:34 slot. Resampling the whole day first and then
    filtering by slot label -- which is what this used to do -- gave that slot
    its finished high and low, so a stop set at 09:31 could come from the 09:34
    low. The stop is the denominator of every R-multiple on the trade, so the
    lookahead did not just move one number, it rescaled the day's results.

    Truncating the frame instead keeps the slot but stops it at the entry, which
    is exactly what a live evaluator can see. In practice the crossing extreme is
    usually made by the crossing minute itself, so the stop is unchanged -- the
    difference is that it is now unchanged *because* of price the strategy had,
    not by luck.
    """
    return _five_minute_bars(frame.loc[frame.index <= entry_timestamp])


def _five_minute_vwap(futures_frame: pd.DataFrame) -> dict[datetime, float]:
    """Session VWAP sampled at each five-minute slot's close."""
    vwap = session_vwap(futures_frame)
    slots: dict[datetime, float] = {}
    for stamp, value in vwap.items():
        slot = stamp.floor("5min")
        latest = slots.get(slot)
        if latest is None or stamp > latest[0]:
            slots[slot] = (stamp, float(value))
    return {slot: value for slot, (_, value) in slots.items() if pd.notna(value)}


def _vwap_known_at(
    futures_frame: pd.DataFrame, entry_timestamp: datetime
) -> dict[datetime, float]:
    """Slot VWAPs as they stood at the entry minute.

    Session VWAP is cumulative from the open, so truncating the frame leaves
    every retained minute's value untouched and only stops the open slot from
    being sampled at a close that had not happened. See ``_bars_known_at``.
    """
    return _five_minute_vwap(futures_frame.loc[futures_frame.index <= entry_timestamp])


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


def _walk_to_outcome(
    plan: RiskPlan,
    index_bars_1m: list[Bar],
    entry_timestamp: datetime,
    governing_midpoint: float,
) -> tuple[dict[str, object] | None, datetime | None]:
    """Advance the position bar by bar until the policy closes it.

    `governing_midpoint` is the level the entry was taken against, so a close
    back through it is a structural break. The entry bar itself cannot break it:
    admission required that bar's close to be beyond the level already.
    """
    position = open_position(plan)
    outcome = None
    last_timestamp: datetime | None = None
    for bar in index_bars_1m:
        if bar.timestamp < entry_timestamp:
            continue
        last_timestamp = bar.timestamp
        position, closed = advance(
            position,
            bar,
            structure_failed=structure_failed(
                governing_midpoint,
                direction=plan.direction.value,
                close=bar.close,
            ),
        )
        if closed is not None:
            outcome = closed
            break
    if outcome is None:
        return None, last_timestamp
    return outcome, outcome.exit_timestamp


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
    """
    replay, health = replay_red_bar_v2_day_with_futures_vwap(
        index_candles,
        futures_candles,
        instrument_key=instrument_key,
        vwap_instrument_key=vwap_instrument_key,
    )
    frame = replay_frame(index_candles)
    futures_frame = replay_frame(futures_candles)
    index_bars_1m = [
        Bar(
            timestamp=stamp.to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for stamp, row in frame.iterrows()
    ]

    policy: dict[str, Any] = {}
    if reward_multiple is not None:
        policy["reward_multiple"] = reward_multiple
    if minimum_risk_points is not None:
        policy["minimum_risk_points"] = minimum_risk_points
    if maximum_risk_points is not None:
        policy["maximum_risk_points"] = maximum_risk_points
    if trail_activation_r is not None:
        policy["trail_activation_r"] = trail_activation_r
    if session_flat_time is not None:
        policy["session_flat_time"] = session_flat_time

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
        entry_price = event.details.get("index_close")
        reference_timestamp = event.details.get("reference_timestamp")
        reference_midpoint = event.details.get("reference_midpoint")
        if entry_price is None or reference_timestamp is None or reference_midpoint is None:
            trades.append({
                "trade_id": trade_id,
                "entry_timestamp": entry_timestamp.isoformat(),
                "direction": event.direction,
                "plan": None,
                "rejection": "MISSING_EVIDENCE",
                "outcome": None,
            })
            continue

        try:
            trigger = find_stop_trigger(
                direction=Direction(event.direction),
                # As known at the entry minute, not as the day finished. The
                # crossing slot is still open when the stop is priced.
                index_bars=_bars_known_at(frame, entry_timestamp),
                futures_bars=_bars_known_at(futures_frame, entry_timestamp),
                futures_vwap=_vwap_known_at(futures_frame, entry_timestamp),
                reference_midpoint=float(reference_midpoint),
                reference_timestamp=_align_to_index(
                    frame.index, _to_datetime(reference_timestamp)
                ),
                entry_timestamp=entry_timestamp,
                resolution=trigger_resolution,
            )
            plan = build_risk_plan(
                direction=Direction(event.direction),
                entry_timestamp=entry_timestamp,
                entry_price=float(entry_price),
                trigger_candle=trigger,
                **policy,
            )
        except RiskPlanRejected as rejected:
            trades.append({
                "trade_id": trade_id,
                "entry_timestamp": entry_timestamp.isoformat(),
                "direction": event.direction,
                "plan": None,
                "rejection": rejected.rejection.value,
                "outcome": None,
            })
            rows.append({
                "kind": "REJECT",
                "timestamp": entry_timestamp.isoformat(),
                "trade_id": trade_id,
                "rejection": rejected.rejection.value,
                "detail": rejected.detail,
            })
            continue

        trades.append({
            "trade_id": trade_id,
            "entry_timestamp": entry_timestamp.isoformat(),
            "direction": event.direction,
            "plan": _plan_row(plan),
            "rejection": None,
            "outcome": None,
        })
        rows.append({"kind": "PLAN", "trade_id": trade_id, **_plan_row(plan)})

        outcome, exit_timestamp = _walk_to_outcome(
            plan, index_bars_1m, entry_timestamp, float(reference_midpoint)
        )
        if outcome is not None:
            outcome_row = _outcome_row(outcome)
            trades[-1]["outcome"] = outcome_row
            rows.append({
                "kind": "EXIT",
                "timestamp": exit_timestamp.isoformat(),
                "trade_id": trade_id,
                **outcome_row,
            })
        else:
            trades[-1]["status"] = _FLAT_STATUS

    entries = [t for t in trades if t["plan"] is not None]
    rejections = [t for t in trades if t["rejection"] not in (None, "MISSING_EVIDENCE")]
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
        },
    }


def replay_frame(candles: pd.DataFrame) -> pd.DataFrame:
    """Normalise candles exactly as the replay does before touching them."""
    from red_bar_lab.services.red_bar_v2_historical_replay import _normalise

    return _normalise(candles)


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
