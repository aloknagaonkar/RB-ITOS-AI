"""Midpoint Trade Decision Research V1.

Consumes OPENING_RED_MIDPOINT_EVIDENCE_V1_1 output.

Goal
----
Use TRAIN only to derive a simple T+3 bearish evidence score, freeze it, then
validate the resulting TRADE_NOW / WAIT / CANCEL decision on OOS-A/B/C/D.

No P&L is calculated here. This module is classification research only.

Leakage discipline
------------------
* Thresholds and score cutoff are derived ONLY from TRAIN.
* OOS-A/B/C/D are validation only.
* E/F/G/H are forbidden.
* Only the T+3 snapshot is eligible for the decision.
* A midpoint reclaim is allowed to cause CANCEL only if the reclaim timestamp
  is <= the T+3 decision timestamp (information already known by then).
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

RESEARCH_VERSION = "MIDPOINT_TRADE_DECISION_RESEARCH_V1"
SOURCE_VERSION = "OPENING_RED_MIDPOINT_EVIDENCE_V1_1"

TRAIN_BLOCK = "TRAIN"
VALIDATION_BLOCKS = ("OOS_A", "OOS_B", "OOS_C", "OOS_D")
ALLOWED_BLOCKS = {TRAIN_BLOCK, *VALIDATION_BLOCKS}

CONTINUATION_LABELS = {"BREAK_AND_GO", "BREAK_AND_BASE_THEN_GO"}
RECLAIM_LABEL = "FALSE_BREAK_RECLAIM"

# Predeclared feature set. Signs are learned from TRAIN group medians, but no
# feature is selected/dropped based on OOS results.
FEATURES = (
    "spot_momentum_5m",
    "distance_from_reference_low_points",
    "closes_below_reference_low_pct",
    "consecutive_closes_below_reference_low",
    "new_close_low_count_since_break",
    "net_downside_progress_points",
    "downside_velocity_points_per_minute",
    "pe_5m_premium_change_pct",
    "ce_5m_oi_change_pct",
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("research JSON must contain an object")
    return payload


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def t3_snapshot(session: dict[str, Any]) -> dict[str, Any] | None:
    for snapshot in session.get("evidence_snapshots", []):
        if snapshot.get("offset_minutes") == 3:
            return snapshot
    return None


def validate_source(payload: dict[str, Any]) -> None:
    if payload.get("status") != "AVAILABLE":
        raise ValueError("source research status must be AVAILABLE")
    if payload.get("research_version") != SOURCE_VERSION:
        raise ValueError(
            f"expected {SOURCE_VERSION}, got {payload.get('research_version')!r}"
        )
    blocks = {str(x) for x in payload.get("development_blocks", [])}
    if blocks != ALLOWED_BLOCKS:
        raise ValueError(
            f"source blocks must be exactly {sorted(ALLOWED_BLOCKS)}, got {sorted(blocks)}"
        )
    guard = payload.get("leakage_guard") or {}
    for key in (
        "future_outcome_used_as_feature",
        "future_return_feature_used",
        "oos_e_f_g_h_used",
        "oos_h_used",
    ):
        if guard.get(key) is not False:
            raise ValueError(f"source leakage guard failed: {key}")


def train_rows(payload: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    rows = []
    for session in payload.get("sessions", []):
        if session.get("block") != TRAIN_BLOCK:
            continue
        if session.get("outcome_label") not in CONTINUATION_LABELS | {RECLAIM_LABEL}:
            continue
        snap = t3_snapshot(session)
        if snap:
            rows.append((session, snap))
    return rows


def derive_feature_specs(
    rows: Sequence[tuple[dict[str, Any], dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    continuation = [
        snap for session, snap in rows if session.get("outcome_label") in CONTINUATION_LABELS
    ]
    reclaim = [
        snap for session, snap in rows if session.get("outcome_label") == RECLAIM_LABEL
    ]
    if not continuation or not reclaim:
        raise ValueError("TRAIN needs both continuation and reclaim examples")

    specs: dict[str, dict[str, Any]] = {}
    for feature in FEATURES:
        c_values = [x for snap in continuation if (x := finite(snap.get(feature))) is not None]
        r_values = [x for snap in reclaim if (x := finite(snap.get(feature))) is not None]
        if not c_values or not r_values:
            raise ValueError(f"TRAIN missing usable values for {feature}")

        c_med = statistics.median(c_values)
        r_med = statistics.median(r_values)
        direction = "LOWER_IS_BEARISH" if c_med < r_med else "HIGHER_IS_BEARISH"
        threshold = (c_med + r_med) / 2.0
        specs[feature] = {
            "continuation_median_train": c_med,
            "reclaim_median_train": r_med,
            "favorable_direction": direction,
            "threshold_train_only": threshold,
        }
    return specs


def feature_pass(value: float | None, spec: dict[str, Any]) -> bool:
    if value is None:
        return False
    if spec["favorable_direction"] == "LOWER_IS_BEARISH":
        return value <= float(spec["threshold_train_only"])
    return value >= float(spec["threshold_train_only"])


def score_snapshot(
    snapshot: dict[str, Any], specs: dict[str, dict[str, Any]]
) -> tuple[int, int, dict[str, bool | None]]:
    score = 0
    available = 0
    detail: dict[str, bool | None] = {}
    for feature in FEATURES:
        value = finite(snapshot.get(feature))
        if value is None:
            detail[feature] = None
            continue
        available += 1
        passed = feature_pass(value, specs[feature])
        detail[feature] = passed
        score += int(passed)
    return score, available, detail


def choose_score_cutoff_train_only(
    rows: Sequence[tuple[dict[str, Any], dict[str, Any]]],
    specs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Choose cutoff on TRAIN only.

    Objective order:
    1) at least 3 TRADE_NOW examples;
    2) highest continuation precision;
    3) higher continuation recall;
    4) higher cutoff (more conservative).
    """
    scored = []
    for session, snap in rows:
        score, available, _ = score_snapshot(snap, specs)
        scored.append((session["outcome_label"], score, available))

    candidates = []
    for cutoff in range(1, len(FEATURES) + 1):
        selected = [
            label for label, score, available in scored
            if available == len(FEATURES) and score >= cutoff
        ]
        if len(selected) < 3:
            continue
        true_count = sum(label in CONTINUATION_LABELS for label in selected)
        precision = true_count / len(selected)
        all_cont = sum(label in CONTINUATION_LABELS for label, _, _ in scored)
        recall = true_count / all_cont if all_cont else 0.0
        candidates.append(
            {
                "cutoff": cutoff,
                "selected_count": len(selected),
                "continuation_count": true_count,
                "precision": precision,
                "recall": recall,
            }
        )
    if not candidates:
        raise ValueError("unable to derive TRAIN score cutoff")
    best = max(candidates, key=lambda x: (x["precision"], x["recall"], x["cutoff"]))
    return {"selected": best, "all_candidates": candidates}


def decision_for_session(
    session: dict[str, Any],
    specs: dict[str, dict[str, Any]],
    cutoff: int,
) -> dict[str, Any] | None:
    snapshot = t3_snapshot(session)
    if not snapshot:
        return None
    if session.get("outcome_label") not in CONTINUATION_LABELS | {RECLAIM_LABEL}:
        return None

    decision_ts = parse_dt(snapshot.get("timestamp"))
    reclaim_ts = parse_dt(session.get("midpoint_reclaim_timestamp"))

    score, available, detail = score_snapshot(snapshot, specs)

    known_reclaim = bool(
        reclaim_ts is not None
        and decision_ts is not None
        and reclaim_ts <= decision_ts
    )

    if known_reclaim:
        decision = "CANCEL"
    elif available == len(FEATURES) and score >= cutoff:
        decision = "TRADE_NOW"
    else:
        decision = "WAIT"

    return {
        "block": session["block"],
        "session_date": session["session_date"],
        "actual_outcome": session["outcome_label"],
        "decision_timestamp": snapshot["timestamp"],
        "decision": decision,
        "score": score,
        "feature_count_available": available,
        "score_cutoff": cutoff,
        "known_midpoint_reclaim_by_decision_time": known_reclaim,
        "feature_passes": detail,
    }


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"count": len(rows), "decisions": {}}
    for decision in ("TRADE_NOW", "WAIT", "CANCEL"):
        selected = [row for row in rows if row["decision"] == decision]
        continuation = sum(row["actual_outcome"] in CONTINUATION_LABELS for row in selected)
        reclaim = sum(row["actual_outcome"] == RECLAIM_LABEL for row in selected)
        out["decisions"][decision] = {
            "count": len(selected),
            "continuation_count": continuation,
            "reclaim_count": reclaim,
            "continuation_rate": continuation / len(selected) if selected else None,
            "reclaim_rate": reclaim / len(selected) if selected else None,
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TRAIN-frozen T+3 midpoint TRADE/WAIT/CANCEL research"
    )
    parser.add_argument("--research", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source = load_json(Path(args.research))
    validate_source(source)

    train = train_rows(source)
    specs = derive_feature_specs(train)
    cutoff_info = choose_score_cutoff_train_only(train, specs)
    cutoff = int(cutoff_info["selected"]["cutoff"])

    rows = []
    for session in source.get("sessions", []):
        row = decision_for_session(session, specs, cutoff)
        if row:
            rows.append(row)

    by_block = {
        block: summarize([row for row in rows if row["block"] == block])
        for block in (TRAIN_BLOCK, *VALIDATION_BLOCKS)
    }

    payload = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_research_version": SOURCE_VERSION,
        "decision_checkpoint": "T_PLUS_3_MINUTES_AFTER_LOW_BREAK",
        "research_status": "TRAIN_FROZEN_DECISION_RULE_VALIDATED_ON_OOS_A_D",
        "feature_specs_train_only": specs,
        "score_cutoff_train_only": cutoff_info,
        "overall_summary": summarize(rows),
        "block_summaries": by_block,
        "leakage_guard": {
            "thresholds_derived_from_train_only": True,
            "score_cutoff_derived_from_train_only": True,
            "oos_a_b_c_d_used_for_threshold_selection": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "decision_uses_t3_or_earlier_data_only": True,
            "midpoint_reclaim_can_cancel_only_if_known_by_t3": True,
            "pnl_used_for_rule_selection": False,
        },
        "important_note": (
            "This is still research. TRADE_NOW means evidence-supported candidate, "
            "not an executable order. Exact PE P&L comes only after validation."
        ),
        "rows": rows,
    }

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": payload["status"],
        "research_version": RESEARCH_VERSION,
        "score_cutoff": cutoff,
        "overall_summary": payload["overall_summary"],
        "block_summaries": by_block,
        "output": str(path),
    }, indent=2))


if __name__ == "__main__":
    main()
