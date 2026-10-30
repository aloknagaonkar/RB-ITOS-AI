"""Bullish reclaim research from the same opening red reference candle.

This module does NOT introduce a new green-candle strategy. It studies the
bullish reversal already implied by the user's original red-candle structure:

midpoint breaks down -> reference low breaks -> downside fails ->
original midpoint is reclaimed -> does price then continue upward?

The original midpoint/reference candle remains unchanged.
"""
from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from .opening_red_midpoint_evidence_v1 import (
    attach_context,
    exact_row_index,
    f,
    index_exact_rows,
    load_csv,
    parse_dt,
    positioning_atm_index,
    spot_features,
    underlying_by_session,
)

RESEARCH_VERSION = "MIDPOINT_BULLISH_RECLAIM_RESEARCH_V1"
SOURCE_VERSION = "OPENING_RED_MIDPOINT_EVIDENCE_V1_1"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
HORIZON_MINUTES = 30
FAST_MINUTES = 5
MIN_POINTS = 10.0
RANGE_FRACTION = 0.50


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


def first_close_at_or_above(rows, start, end, level):
    for row in rows:
        if row["timestamp"] < start:
            continue
        if row["timestamp"] > end:
            break
        if row["close"] >= level:
            return row["timestamp"]
    return None


def first_close_below(rows, start, end, level):
    for row in rows:
        if row["timestamp"] <= start:
            continue
        if row["timestamp"] > end:
            break
        if row["close"] < level:
            return row["timestamp"]
    return None


def classify_bullish(rows, reclaim_ts, midpoint, reference_high, reference_range):
    end = reclaim_ts + timedelta(minutes=HORIZON_MINUTES)
    continuation_points = max(MIN_POINTS, RANGE_FRACTION * reference_range)
    continuation_level = reference_high + continuation_points

    continuation_ts = first_close_at_or_above(
        rows, reclaim_ts, end, continuation_level
    )
    failed_ts = first_close_below(rows, reclaim_ts, end, midpoint)

    if continuation_ts is not None and (failed_ts is None or continuation_ts < failed_ts):
        minutes = int((continuation_ts - reclaim_ts).total_seconds() // 60)
        label = (
            "BULLISH_BREAK_AND_GO"
            if minutes <= FAST_MINUTES
            else "BULLISH_BASE_THEN_GO"
        )
    elif failed_ts is not None and (continuation_ts is None or failed_ts <= continuation_ts):
        label = "FAILED_BULLISH_RECLAIM"
        minutes = None
    else:
        label = "BULLISH_SIDEWAYS"
        minutes = None

    return {
        "bullish_outcome": label,
        "bullish_continuation_level": continuation_level,
        "bullish_continuation_timestamp": continuation_ts.isoformat() if continuation_ts else None,
        "failed_reclaim_timestamp": failed_ts.isoformat() if failed_ts else None,
        "minutes_to_bullish_continuation": minutes,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Bullish reversal research after midpoint reclaim"
    )
    parser.add_argument("--research", required=True)
    parser.add_argument("--block", action="append", required=True, type=parse_block)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source = json.loads(Path(args.research).read_text(encoding="utf-8"))
    if source.get("research_version") != SOURCE_VERSION:
        raise ValueError("expected V1.1 midpoint evidence source")
    if {b[0] for b in args.block} != ALLOWED_BLOCKS:
        raise ValueError("requires exactly TRAIN + OOS_A/B/C/D")

    source_sessions = {
        (s["block"], s["session_date"]): s
        for s in source.get("sessions", [])
        if s.get("low_break_timestamp") and s.get("midpoint_reclaim_timestamp")
    }

    rows_out = []
    block_counts = {}

    for block, underlying_path, evidence_path, positioning_path in args.block:
        urows = load_csv(underlying_path)
        erows = load_csv(evidence_path)
        prows = load_csv(positioning_path)

        by_session = underlying_by_session(urows)
        eidx = index_exact_rows(erows)
        pidx = positioning_atm_index(prows)

        count = 0
        for session_date, minute_rows in sorted(by_session.items()):
            session = source_sessions.get((block, session_date))
            if not session:
                continue

            reclaim_ts = parse_dt(session["midpoint_reclaim_timestamp"])
            midpoint = float(session["reference_midpoint"])
            high = float(session["reference_high"])
            ref_range = float(session["reference_range"])
            row_idx = exact_row_index(minute_rows)

            decision_ts = reclaim_ts + timedelta(minutes=3)
            price = spot_features(
                minute_rows,
                row_idx,
                decision_ts,
                midpoint,
                float(session["reference_low"]),
                0,
            )
            context = attach_context(
                session_date,
                decision_ts,
                eidx,
                pidx,
            )
            outcome = classify_bullish(
                minute_rows,
                reclaim_ts,
                midpoint,
                high,
                ref_range,
            )

            rows_out.append({
                "block": block,
                "session_date": session_date,
                "reference_midpoint": midpoint,
                "reference_high": high,
                "reclaim_timestamp": reclaim_ts.isoformat(),
                "decision_timestamp_t3": decision_ts.isoformat(),
                "bullish_signal_interpretation": "FAILED_BEARISH_BREAK_RECLAIM",
                "price_features_t3": price,
                "option_pcr_context_t3": context,
                **outcome,
            })
            count += 1
        block_counts[block] = count

    outcome_counts = {}
    for row in rows_out:
        outcome_counts[row["bullish_outcome"]] = (
            outcome_counts.get(row["bullish_outcome"], 0) + 1
        )

    payload = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_research_version": SOURCE_VERSION,
        "research_status": "BULLISH_REVERSAL_AFTER_FAILED_BEARISH_BREAK",
        "definition": {
            "same_original_red_reference_candle": True,
            "bullish_setup_starts_only_after_midpoint_reclaim": True,
            "t3_confirmation_snapshot": True,
            "bullish_continuation_level": (
                "reference_high + max(10 points, 0.50 * reference_range)"
            ),
            "failed_reclaim": "later 1m close below original midpoint before continuation",
        },
        "leakage_guard": {
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "future_outcome_used_as_t3_feature": False,
            "pcr_used_as_trade_rule": False,
            "oi_used_as_trade_rule": False,
            "research_emits_trade_order": False,
        },
        "event_count": len(rows_out),
        "block_event_counts": block_counts,
        "outcome_counts": outcome_counts,
        "rows": rows_out,
    }

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "event_count": len(rows_out),
        "block_event_counts": block_counts,
        "outcome_counts": outcome_counts,
        "output": str(path),
    }, indent=2))


if __name__ == "__main__":
    main()
