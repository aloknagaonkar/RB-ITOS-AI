"""Opening Candle Midpoint Reversal Framework V1.

Symmetric research framework for:

1) RED reference candle
   downside midpoint break -> low break
   -> bearish continuation OR bullish reclaim

2) GREEN reference candle
   upside midpoint break -> high break
   -> bullish continuation OR bearish reclaim

Research only. No order is emitted.

The first 09:15-09:19 five-minute candle is ignored. The first later RED
five-minute candle and first later GREEN five-minute candle are independent,
persistent session references.

Only TRAIN + OOS-A/B/C/D are permitted.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from .opening_red_midpoint_evidence_v1 import (
    IST,
    aggregate_5m,
    attach_context,
    ema,
    exact_row_index,
    f,
    index_exact_rows,
    load_csv,
    parse_dt,
    positioning_atm_index,
    underlying_by_session,
)

RESEARCH_VERSION = "OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}

OUTCOME_HORIZON_MINUTES = 30
FAST_CONTINUATION_MINUTES = 5
MIN_CONTINUATION_POINTS = 10.0
CONTINUATION_REFERENCE_RANGE_FRACTION = 0.50
DECISION_OFFSETS = (0, 1, 3, 5)


def parse_block(value: str) -> tuple[str, Path, Path, Path]:
    parts = value.split("|")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "--block must be NAME|UNDERLYING_CSV|EVIDENCE_CSV|POSITIONING_CSV"
        )
    name = parts[0].upper().replace("-", "_")
    if name not in ALLOWED_BLOCKS:
        raise argparse.ArgumentTypeError(f"unsupported/forbidden block {name}")
    return name, Path(parts[1]), Path(parts[2]), Path(parts[3])


def select_reference_bar(
    bars: Sequence[dict[str, Any]],
    colour: str,
) -> dict[str, Any] | None:
    """Ignore the opening 5m bar; return first later RED/GREEN bar."""
    wanted = colour.upper()
    if wanted not in {"RED", "GREEN"}:
        raise ValueError("colour must be RED or GREEN")

    for bar in bars:
        start = bar["start"]
        if start.hour == 9 and start.minute == 15:
            continue
        if wanted == "RED" and bar["close"] < bar["open"]:
            return bar
        if wanted == "GREEN" and bar["close"] > bar["open"]:
            return bar
    return None


def first_close_cross(
    rows: Sequence[dict[str, Any]],
    *,
    after: datetime,
    level: float,
    direction: str,
    end: datetime | None = None,
) -> datetime | None:
    """First close strictly across level after timestamp."""
    for row in rows:
        ts = row["timestamp"]
        if ts <= after:
            continue
        if end is not None and ts > end:
            break
        close = float(row["close"])
        if direction == "DOWN" and close < level:
            return ts
        if direction == "UP" and close > level:
            return ts
    return None


def _record_progress_count(closes: Sequence[float], direction: str) -> int:
    if not closes:
        return 0
    record = closes[0]
    count = 0
    for value in closes[1:]:
        if direction == "DOWN" and value < record:
            count += 1
            record = value
        elif direction == "UP" and value > record:
            count += 1
            record = value
    return count


def directional_snapshot_features(
    minute_rows: Sequence[dict[str, Any]],
    row_idx: dict[datetime, int],
    *,
    ts: datetime,
    break_ts: datetime,
    midpoint: float,
    boundary: float,
    direction: str,
) -> dict[str, Any]:
    """Current/backward-only normalized price features.

    Positive directional values always mean progress in the setup direction:
    DOWN for red breakdown and UP for green breakout.
    """
    i = row_idx.get(ts)
    if i is None:
        return {"price_status": "UNAVAILABLE"}

    closes = [float(row["close"]) for row in minute_rows]
    close = closes[i]
    sign = -1.0 if direction == "DOWN" else 1.0

    fast = ema(closes[: i + 1], 5)
    slow = ema(closes[: i + 1], 15)

    m1 = sign * (close - closes[i - 1]) if i >= 1 else None
    m5 = sign * (close - closes[i - 5]) if i >= 5 else None
    m15 = sign * (close - closes[i - 15]) if i >= 15 else None
    ema5 = fast[-1] if i >= 4 else None
    ema15 = slow[-1] if i >= 14 else None
    ema_spread_directional = (
        sign * (ema5 - ema15)
        if ema5 is not None and ema15 is not None
        else None
    )
    ema5_slope_directional = sign * (fast[-1] - fast[-4]) if i >= 4 else None

    observed = [
        row for row in minute_rows
        if break_ts <= row["timestamp"] <= ts
    ]
    obs_closes = [float(row["close"]) for row in observed]

    if direction == "DOWN":
        accepted = [x < boundary for x in obs_closes]
        midpoint_accepted = [x < midpoint for x in obs_closes]
        directional_progress = obs_closes[0] - obs_closes[-1] if obs_closes else None
        directional_distance_boundary = boundary - close
    else:
        accepted = [x > boundary for x in obs_closes]
        midpoint_accepted = [x > midpoint for x in obs_closes]
        directional_progress = obs_closes[-1] - obs_closes[0] if obs_closes else None
        directional_distance_boundary = close - boundary

    consecutive = 0
    for good in reversed(accepted):
        if good:
            consecutive += 1
        else:
            break

    minutes_since = int((ts - break_ts).total_seconds() // 60)
    velocity = (
        directional_progress / max(1, minutes_since)
        if directional_progress is not None
        else None
    )

    realized_vol = None
    if i >= 15:
        changes = [
            closes[j] - closes[j - 1]
            for j in range(i - 14, i + 1)
        ]
        realized_vol = statistics.pstdev(changes) if len(changes) >= 2 else None

    return {
        "price_status": "AVAILABLE_FULL" if i >= 15 else "AVAILABLE_PARTIAL",
        "setup_direction": direction,
        "spot": close,
        "directional_momentum_1m": m1,
        "directional_momentum_5m": m5,
        "directional_momentum_15m": m15,
        "directional_ema_5_minus_15": ema_spread_directional,
        "directional_ema_5_slope_3m": ema5_slope_directional,
        "realized_vol_15m": realized_vol,
        "directional_distance_beyond_boundary_points": directional_distance_boundary,
        "distance_from_midpoint_points": close - midpoint,
        "minutes_since_boundary_break": minutes_since,
        "directional_acceptance_pct": (
            100.0 * sum(accepted) / len(accepted) if accepted else None
        ),
        "midpoint_side_acceptance_pct": (
            100.0 * sum(midpoint_accepted) / len(midpoint_accepted)
            if midpoint_accepted
            else None
        ),
        "consecutive_closes_beyond_boundary": consecutive,
        "new_directional_close_extreme_count": _record_progress_count(
            obs_closes, direction
        ),
        "directional_progress_points": directional_progress,
        "directional_velocity_points_per_minute": velocity,
        "post_break_close_range_points": (
            max(obs_closes) - min(obs_closes) if obs_closes else None
        ),
    }


def classify_primary_path(
    minute_rows: Sequence[dict[str, Any]],
    *,
    break_ts: datetime,
    midpoint: float,
    boundary: float,
    reference_range: float,
    direction: str,
) -> dict[str, Any]:
    horizon_end = break_ts + timedelta(minutes=OUTCOME_HORIZON_MINUTES)
    extension = max(
        MIN_CONTINUATION_POINTS,
        CONTINUATION_REFERENCE_RANGE_FRACTION * reference_range,
    )

    if direction == "DOWN":
        continuation_level = boundary - extension
        continuation_ts = first_close_cross(
            minute_rows,
            after=break_ts - timedelta(seconds=1),
            level=continuation_level,
            direction="DOWN",
            end=horizon_end,
        )
        reclaim_ts = first_close_cross(
            minute_rows,
            after=break_ts - timedelta(seconds=1),
            level=midpoint,
            direction="UP",
            end=horizon_end,
        )
        prefix = "RED"
        continuation_name = "BEARISH"
        reclaim_name = "BULLISH"
    else:
        continuation_level = boundary + extension
        continuation_ts = first_close_cross(
            minute_rows,
            after=break_ts - timedelta(seconds=1),
            level=continuation_level,
            direction="UP",
            end=horizon_end,
        )
        reclaim_ts = first_close_cross(
            minute_rows,
            after=break_ts - timedelta(seconds=1),
            level=midpoint,
            direction="DOWN",
            end=horizon_end,
        )
        prefix = "GREEN"
        continuation_name = "BULLISH"
        reclaim_name = "BEARISH"

    if continuation_ts is not None and (
        reclaim_ts is None or continuation_ts < reclaim_ts
    ):
        minutes = int((continuation_ts - break_ts).total_seconds() // 60)
        speed = "BREAK_AND_GO" if minutes <= FAST_CONTINUATION_MINUTES else "BASE_THEN_GO"
        label = f"{prefix}_{continuation_name}_{speed}"
    elif reclaim_ts is not None and (
        continuation_ts is None or reclaim_ts <= continuation_ts
    ):
        label = f"{prefix}_BREAK_{reclaim_name}_RECLAIM"
        minutes = None
    else:
        label = f"{prefix}_UNRESOLVED_30M"
        minutes = None

    return {
        "primary_outcome": label,
        "continuation_level": continuation_level,
        "continuation_timestamp": (
            continuation_ts.isoformat() if continuation_ts else None
        ),
        "minutes_to_continuation": minutes,
        "reclaim_timestamp": reclaim_ts.isoformat() if reclaim_ts else None,
    }


def classify_reclaim_path(
    minute_rows: Sequence[dict[str, Any]],
    *,
    reclaim_ts: datetime,
    midpoint: float,
    opposite_boundary: float,
    reference_range: float,
    reclaim_direction: str,
) -> dict[str, Any]:
    """Classify continuation after reclaim in the opposite direction."""
    end = reclaim_ts + timedelta(minutes=OUTCOME_HORIZON_MINUTES)
    extension = max(
        MIN_CONTINUATION_POINTS,
        CONTINUATION_REFERENCE_RANGE_FRACTION * reference_range,
    )

    if reclaim_direction == "UP":
        target = opposite_boundary + extension
        target_ts = first_close_cross(
            minute_rows,
            after=reclaim_ts - timedelta(seconds=1),
            level=target,
            direction="UP",
            end=end,
        )
        failure_ts = first_close_cross(
            minute_rows,
            after=reclaim_ts,
            level=midpoint,
            direction="DOWN",
            end=end,
        )
        side = "BULLISH"
    else:
        target = opposite_boundary - extension
        target_ts = first_close_cross(
            minute_rows,
            after=reclaim_ts - timedelta(seconds=1),
            level=target,
            direction="DOWN",
            end=end,
        )
        failure_ts = first_close_cross(
            minute_rows,
            after=reclaim_ts,
            level=midpoint,
            direction="UP",
            end=end,
        )
        side = "BEARISH"

    if target_ts is not None and (failure_ts is None or target_ts < failure_ts):
        minutes = int((target_ts - reclaim_ts).total_seconds() // 60)
        speed = "BREAK_AND_GO" if minutes <= FAST_CONTINUATION_MINUTES else "BASE_THEN_GO"
        label = f"{side}_RECLAIM_{speed}"
    elif failure_ts is not None and (target_ts is None or failure_ts <= target_ts):
        label = f"FAILED_{side}_RECLAIM"
        minutes = None
    else:
        label = f"{side}_RECLAIM_UNRESOLVED_30M"
        minutes = None

    return {
        "reclaim_outcome": label,
        "reclaim_target_level": target,
        "reclaim_target_timestamp": target_ts.isoformat() if target_ts else None,
        "reclaim_failure_timestamp": failure_ts.isoformat() if failure_ts else None,
        "minutes_to_reclaim_continuation": minutes,
    }


def _reference_payload(bar: dict[str, Any], colour: str) -> dict[str, Any]:
    high = float(bar["high"])
    low = float(bar["low"])
    return {
        "reference_colour": colour,
        "reference_start": bar["start"].isoformat(),
        "reference_end": bar["end"].isoformat(),
        "reference_open": float(bar["open"]),
        "reference_high": high,
        "reference_low": low,
        "reference_close": float(bar["close"]),
        "reference_midpoint": (high + low) / 2.0,
        "reference_range": high - low,
    }


def build_event(
    *,
    block: str,
    session_date: str,
    minute_rows: Sequence[dict[str, Any]],
    bar: dict[str, Any],
    colour: str,
    evidence_idx: dict[tuple[str, datetime], dict[str, str]],
    atm_idx: dict[tuple[str, datetime], dict[str, str]],
) -> dict[str, Any]:
    ref = _reference_payload(bar, colour)
    midpoint = ref["reference_midpoint"]
    high = ref["reference_high"]
    low = ref["reference_low"]
    row_idx = exact_row_index(minute_rows)

    if colour == "RED":
        midpoint_direction = "DOWN"
        boundary_direction = "DOWN"
        boundary = low
        setup_direction = "DOWN"
        opposite_boundary = high
        reclaim_direction = "UP"
        setup_type = "RED_BREAK"
    else:
        midpoint_direction = "UP"
        boundary_direction = "UP"
        boundary = high
        setup_direction = "UP"
        opposite_boundary = low
        reclaim_direction = "DOWN"
        setup_type = "GREEN_BREAK"

    reference_end = bar["end"]
    midpoint_break_ts = first_close_cross(
        minute_rows,
        after=reference_end,
        level=midpoint,
        direction=midpoint_direction,
    )
    if midpoint_break_ts is None:
        return {
            "block": block,
            "session_date": session_date,
            "setup_type": setup_type,
            **ref,
            "status": "NO_MIDPOINT_BREAK",
            "snapshots": [],
        }

    boundary_break_ts = first_close_cross(
        minute_rows,
        after=midpoint_break_ts - timedelta(minutes=1),
        level=boundary,
        direction=boundary_direction,
    )
    if boundary_break_ts is None:
        return {
            "block": block,
            "session_date": session_date,
            "setup_type": setup_type,
            **ref,
            "status": "NO_BOUNDARY_BREAK",
            "midpoint_break_timestamp": midpoint_break_ts.isoformat(),
            "snapshots": [],
        }

    primary = classify_primary_path(
        minute_rows,
        break_ts=boundary_break_ts,
        midpoint=midpoint,
        boundary=boundary,
        reference_range=ref["reference_range"],
        direction=setup_direction,
    )

    snapshots = []
    for offset in DECISION_OFFSETS:
        ts = boundary_break_ts + timedelta(minutes=offset)
        features = directional_snapshot_features(
            minute_rows,
            row_idx,
            ts=ts,
            break_ts=boundary_break_ts,
            midpoint=midpoint,
            boundary=boundary,
            direction=setup_direction,
        )
        snapshots.append({
            "offset_minutes": offset,
            "timestamp": ts.isoformat(),
            "feature_cutoff_timestamp": ts.isoformat(),
            **features,
            **attach_context(session_date, ts, evidence_idx, atm_idx),
        })

    reclaim = {}
    reclaim_ts = parse_dt(primary["reclaim_timestamp"]) if primary["reclaim_timestamp"] else None
    reclaim_snapshots = []
    if reclaim_ts is not None:
        reclaim = classify_reclaim_path(
            minute_rows,
            reclaim_ts=reclaim_ts,
            midpoint=midpoint,
            opposite_boundary=opposite_boundary,
            reference_range=ref["reference_range"],
            reclaim_direction=reclaim_direction,
        )
        for offset in DECISION_OFFSETS:
            ts = reclaim_ts + timedelta(minutes=offset)
            reclaim_snapshots.append({
                "offset_minutes": offset,
                "timestamp": ts.isoformat(),
                "feature_cutoff_timestamp": ts.isoformat(),
                **directional_snapshot_features(
                    minute_rows,
                    row_idx,
                    ts=ts,
                    break_ts=reclaim_ts,
                    midpoint=midpoint,
                    boundary=midpoint,
                    direction=reclaim_direction,
                ),
                **attach_context(session_date, ts, evidence_idx, atm_idx),
            })

    return {
        "block": block,
        "session_date": session_date,
        "setup_type": setup_type,
        **ref,
        "status": "AVAILABLE",
        "midpoint_break_timestamp": midpoint_break_ts.isoformat(),
        "boundary_break_timestamp": boundary_break_ts.isoformat(),
        "primary_direction": setup_direction,
        **primary,
        "snapshots": snapshots,
        "reclaim_direction": reclaim_direction if reclaim_ts else None,
        "reclaim_analysis": reclaim if reclaim_ts else None,
        "reclaim_snapshots": reclaim_snapshots,
    }


def summarize(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    status = Counter(event["status"] for event in events)
    outcomes = Counter(
        event.get("primary_outcome")
        for event in events
        if event.get("primary_outcome")
    )
    reclaim_outcomes = Counter(
        (event.get("reclaim_analysis") or {}).get("reclaim_outcome")
        for event in events
        if (event.get("reclaim_analysis") or {}).get("reclaim_outcome")
    )
    return {
        "event_count": len(events),
        "status_counts": dict(status),
        "primary_outcome_counts": dict(outcomes),
        "reclaim_outcome_counts": dict(reclaim_outcomes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Symmetric RED/GREEN opening midpoint research framework"
    )
    parser.add_argument("--block", action="append", required=True, type=parse_block)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    supplied = {item[0] for item in args.block}
    if supplied != ALLOWED_BLOCKS:
        raise ValueError(
            "requires exactly TRAIN, OOS_A, OOS_B, OOS_C, OOS_D; "
            "E/F/G/H are forbidden"
        )

    all_events: list[dict[str, Any]] = []
    block_summaries: dict[str, Any] = {}

    for block, underlying_path, evidence_path, positioning_path in args.block:
        urows = load_csv(underlying_path)
        erows = load_csv(evidence_path)
        prows = load_csv(positioning_path)

        by_session = underlying_by_session(urows)
        evidence_idx = index_exact_rows(erows)
        atm_idx = positioning_atm_index(prows)

        block_events = []
        for session_date, minute_rows in sorted(by_session.items()):
            bars = aggregate_5m(minute_rows)

            red = select_reference_bar(bars, "RED")
            green = select_reference_bar(bars, "GREEN")

            if red is not None:
                event = build_event(
                    block=block,
                    session_date=session_date,
                    minute_rows=minute_rows,
                    bar=red,
                    colour="RED",
                    evidence_idx=evidence_idx,
                    atm_idx=atm_idx,
                )
                block_events.append(event)
                all_events.append(event)

            if green is not None:
                event = build_event(
                    block=block,
                    session_date=session_date,
                    minute_rows=minute_rows,
                    bar=green,
                    colour="GREEN",
                    evidence_idx=evidence_idx,
                    atm_idx=atm_idx,
                )
                block_events.append(event)
                all_events.append(event)

        block_summaries[block] = summarize(block_events)

    red_events = [e for e in all_events if e["setup_type"] == "RED_BREAK"]
    green_events = [e for e in all_events if e["setup_type"] == "GREEN_BREAK"]

    payload = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "research_status": "SYMMETRIC_STRUCTURE_RESEARCH_ONLY",
        "definitions": {
            "opening_5m_ignored": True,
            "red_reference": "first later 5m candle with close < open",
            "green_reference": "first later 5m candle with close > open",
            "reference_midpoint_persistent": True,
            "red_primary_path": "midpoint down -> low break -> PE continuation or CE reclaim",
            "green_primary_path": "midpoint up -> high break -> CE continuation or PE reclaim",
            "decision_offsets_minutes": list(DECISION_OFFSETS),
            "continuation_extension": "max(10 points, 0.50 * reference range)",
        },
        "summary": {
            "all": summarize(all_events),
            "red": summarize(red_events),
            "green": summarize(green_events),
        },
        "block_summaries": block_summaries,
        "leakage_guard": {
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "snapshots_use_exact_or_backward_data_only": True,
            "future_outcomes_used_as_features": False,
            "pcr_used_as_trade_rule": False,
            "oi_used_as_trade_rule": False,
            "volume_used_as_trade_rule": False,
            "research_emits_trade_order": False,
        },
        "events": all_events,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "summary": payload["summary"],
        "block_summaries": block_summaries,
        "output": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()
