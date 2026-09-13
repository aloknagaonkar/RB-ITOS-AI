"""Four-arm midpoint decision research V1.

Consumes OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1_1 and derives four
independent TRAIN-only T+3 evidence rules:

1. RED -> bearish continuation        => PE
2. RED -> bullish reclaim             => CE
3. GREEN -> bullish continuation      => CE
4. GREEN -> bearish reclaim           => PE

Each arm emits standardized TRADE_NOW / WAIT / CANCEL research decisions.

Important:
- Thresholds and score cutoffs are derived only from TRAIN.
- OOS-A/B/C/D are validation only.
- E/F/G/H are forbidden.
- No P&L is used here.
- No executable order is emitted.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

RESEARCH_VERSION = "MIDPOINT_FOUR_ARM_DECISION_RESEARCH_V1"
SOURCE_VERSION = "OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1_1"

TRAIN_BLOCK = "TRAIN"
VALIDATION_BLOCKS = ("OOS_A", "OOS_B", "OOS_C", "OOS_D")
ALLOWED_BLOCKS = {TRAIN_BLOCK, *VALIDATION_BLOCKS}

DECISION_OFFSET = 3

# Fixed, symmetric feature family. Seven normalized price-structure features
# plus two side-aware option-confirmation features.
COMMON_FEATURES = (
    "directional_momentum_5m",
    "directional_distance_beyond_boundary_points",
    "directional_acceptance_pct",
    "consecutive_closes_beyond_boundary",
    "new_directional_close_extreme_count",
    "directional_progress_points",
    "directional_velocity_points_per_minute",
)

# Each arm maps source snapshot fields into standardized feature names.
ARM_CONFIGS: dict[str, dict[str, Any]] = {
    "RED_BEARISH_CONTINUATION": {
        "setup_type": "RED_BREAK_BEARISH_CONTINUATION",
        "source_setup_type": "RED_BREAK",
        "snapshot_kind": "PRIMARY",
        "option_side": "PE",
        "positive_outcomes": {
            "RED_BEARISH_BREAK_AND_GO",
            "RED_BEARISH_BASE_THEN_GO",
        },
        "negative_outcomes": {"RED_BREAK_BULLISH_RECLAIM"},
        "option_features": {
            "favored_option_premium_change_5m_pct": "pe_5m_premium_change_pct",
            "opposite_option_oi_change_5m_pct": "ce_5m_oi_change_pct",
        },
        "cancel_timestamp_field": "reclaim_timestamp",
        "minimum_train_trade_count": 3,
    },
    "RED_BULLISH_RECLAIM": {
        "setup_type": "RED_BREAK_BULLISH_RECLAIM",
        "source_setup_type": "RED_BREAK",
        "snapshot_kind": "RECLAIM",
        "option_side": "CE",
        "positive_outcomes": {
            "BULLISH_RECLAIM_BREAK_AND_GO",
            "BULLISH_RECLAIM_BASE_THEN_GO",
        },
        "negative_outcomes": {"FAILED_BULLISH_RECLAIM"},
        "option_features": {
            "favored_option_premium_change_5m_pct": "ce_5m_premium_change_pct",
            "opposite_option_oi_change_5m_pct": "pe_5m_oi_change_pct",
        },
        "cancel_timestamp_field": "reclaim_failure_timestamp",
        "minimum_train_trade_count": 2,
    },
    "GREEN_BULLISH_CONTINUATION": {
        "setup_type": "GREEN_BREAK_BULLISH_CONTINUATION",
        "source_setup_type": "GREEN_BREAK",
        "snapshot_kind": "PRIMARY",
        "option_side": "CE",
        "positive_outcomes": {
            "GREEN_BULLISH_BREAK_AND_GO",
            "GREEN_BULLISH_BASE_THEN_GO",
        },
        "negative_outcomes": {"GREEN_BREAK_BEARISH_RECLAIM"},
        "option_features": {
            "favored_option_premium_change_5m_pct": "ce_5m_premium_change_pct",
            "opposite_option_oi_change_5m_pct": "pe_5m_oi_change_pct",
        },
        "cancel_timestamp_field": "reclaim_timestamp",
        "minimum_train_trade_count": 3,
    },
    "GREEN_BEARISH_RECLAIM": {
        "setup_type": "GREEN_BREAK_BEARISH_RECLAIM",
        "source_setup_type": "GREEN_BREAK",
        "snapshot_kind": "RECLAIM",
        "option_side": "PE",
        "positive_outcomes": {
            "BEARISH_RECLAIM_BREAK_AND_GO",
            "BEARISH_RECLAIM_BASE_THEN_GO",
        },
        "negative_outcomes": {"FAILED_BEARISH_RECLAIM"},
        "option_features": {
            "favored_option_premium_change_5m_pct": "pe_5m_premium_change_pct",
            "opposite_option_oi_change_5m_pct": "ce_5m_oi_change_pct",
        },
        "cancel_timestamp_field": "reclaim_failure_timestamp",
        "minimum_train_trade_count": 2,
    },
}

STANDARD_FEATURES = COMMON_FEATURES + (
    "favored_option_premium_change_5m_pct",
    "opposite_option_oi_change_5m_pct",
)

REASON_CODES = {
    "directional_momentum_5m": "DIRECTIONAL_MOMENTUM_CONFIRMED",
    "directional_distance_beyond_boundary_points": "BOUNDARY_PENETRATION_CONFIRMED",
    "directional_acceptance_pct": "PRICE_ACCEPTANCE_CONFIRMED",
    "consecutive_closes_beyond_boundary": "CONSECUTIVE_CLOSES_CONFIRMED",
    "new_directional_close_extreme_count": "NEW_EXTREMES_CONFIRMED",
    "directional_progress_points": "DIRECTIONAL_PROGRESS_CONFIRMED",
    "directional_velocity_points_per_minute": "DIRECTIONAL_VELOCITY_CONFIRMED",
    "favored_option_premium_change_5m_pct": "FAVORED_OPTION_PREMIUM_CONFIRMED",
    "opposite_option_oi_change_5m_pct": "OPPOSITE_OPTION_OI_CONFIRMED",
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("source JSON must be an object")
    return payload


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def validate_source(payload: dict[str, Any]) -> None:
    if payload.get("status") != "AVAILABLE":
        raise ValueError("source framework status must be AVAILABLE")
    if payload.get("research_version") != SOURCE_VERSION:
        raise ValueError(
            f"expected {SOURCE_VERSION}, got {payload.get('research_version')!r}"
        )
    guard = payload.get("leakage_guard") or {}
    if guard.get("oos_e_f_g_h_used") is not False:
        raise ValueError("source leakage guard: E/F/G/H must be unused")
    if guard.get("oos_h_used") is not False:
        raise ValueError("source leakage guard: OOS-H must be unused")
    if guard.get("future_outcomes_used_as_features") is not False:
        raise ValueError("source leakage guard: future outcomes used as features")
    if guard.get("post_continuation_reclaims_excluded_from_reclaim_research") is not True:
        raise ValueError("source must exclude post-continuation reclaim contamination")


def snapshot_at(event: dict[str, Any], kind: str, offset: int) -> dict[str, Any] | None:
    key = "snapshots" if kind == "PRIMARY" else "reclaim_snapshots"
    for snapshot in event.get(key, []) or []:
        if snapshot.get("offset_minutes") == offset:
            return snapshot
    return None


def actual_outcome(event: dict[str, Any], kind: str) -> str | None:
    if kind == "PRIMARY":
        return event.get("primary_outcome")
    analysis = event.get("reclaim_analysis") or {}
    return analysis.get("reclaim_outcome")


def cancel_timestamp(event: dict[str, Any], kind: str, field: str) -> datetime | None:
    if kind == "PRIMARY":
        return parse_dt(event.get(field))
    return parse_dt((event.get("reclaim_analysis") or {}).get(field))


def extract_features(
    snapshot: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, float | None]:
    result = {name: finite(snapshot.get(name)) for name in COMMON_FEATURES}
    for standardized, source_name in config["option_features"].items():
        result[standardized] = finite(snapshot.get(source_name))
    return result


def eligible_events(
    payload: dict[str, Any],
    arm_name: str,
) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    config = ARM_CONFIGS[arm_name]
    positive = config["positive_outcomes"]
    negative = config["negative_outcomes"]
    rows = []

    for event in payload.get("events", []):
        if event.get("setup_type") != config["source_setup_type"]:
            continue

        if config["snapshot_kind"] == "RECLAIM" and not event.get("reclaim_path_eligible"):
            continue

        outcome = actual_outcome(event, config["snapshot_kind"])
        if outcome not in positive | negative:
            continue

        snap = snapshot_at(event, config["snapshot_kind"], DECISION_OFFSET)
        if snap is None:
            continue

        rows.append((event, snap, outcome))
    return rows


def derive_specs_train_only(
    train_rows: Sequence[tuple[dict[str, Any], dict[str, Any], str]],
    config: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    positive_snaps = [
        snap for _, snap, outcome in train_rows
        if outcome in config["positive_outcomes"]
    ]
    negative_snaps = [
        snap for _, snap, outcome in train_rows
        if outcome in config["negative_outcomes"]
    ]
    if not positive_snaps or not negative_snaps:
        raise ValueError("TRAIN requires both positive and negative examples")

    specs: dict[str, dict[str, Any]] = {}
    for feature in STANDARD_FEATURES:
        pos = [
            value
            for snap in positive_snaps
            if (value := extract_features(snap, config).get(feature)) is not None
        ]
        neg = [
            value
            for snap in negative_snaps
            if (value := extract_features(snap, config).get(feature)) is not None
        ]
        if not pos or not neg:
            raise ValueError(f"TRAIN missing feature values for {feature}")

        pmed = statistics.median(pos)
        nmed = statistics.median(neg)
        direction = "HIGHER_IS_FAVORABLE" if pmed >= nmed else "LOWER_IS_FAVORABLE"
        specs[feature] = {
            "positive_median_train": pmed,
            "negative_median_train": nmed,
            "favorable_direction": direction,
            "threshold_train_only": (pmed + nmed) / 2.0,
            "positive_available_count": len(pos),
            "negative_available_count": len(neg),
        }
    return specs


def feature_pass(value: float | None, spec: dict[str, Any]) -> bool:
    if value is None:
        return False
    threshold = float(spec["threshold_train_only"])
    if spec["favorable_direction"] == "HIGHER_IS_FAVORABLE":
        return value >= threshold
    return value <= threshold


def score_snapshot(
    snapshot: dict[str, Any],
    config: dict[str, Any],
    specs: dict[str, dict[str, Any]],
) -> tuple[int, int, dict[str, bool | None], dict[str, float | None]]:
    values = extract_features(snapshot, config)
    passes: dict[str, bool | None] = {}
    score = 0
    available = 0
    for feature in STANDARD_FEATURES:
        value = values.get(feature)
        if value is None:
            passes[feature] = None
            continue
        available += 1
        passed = feature_pass(value, specs[feature])
        passes[feature] = passed
        score += int(passed)
    return score, available, passes, values


def choose_cutoff_train_only(
    train_rows: Sequence[tuple[dict[str, Any], dict[str, Any], str]],
    config: dict[str, Any],
    specs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    scored = []
    for _, snap, outcome in train_rows:
        score, available, _, _ = score_snapshot(snap, config, specs)
        scored.append((outcome, score, available))

    all_positive = sum(outcome in config["positive_outcomes"] for outcome, _, _ in scored)
    min_selected = int(config["minimum_train_trade_count"])
    candidates = []

    for cutoff in range(1, len(STANDARD_FEATURES) + 1):
        selected = [
            outcome
            for outcome, score, available in scored
            if available == len(STANDARD_FEATURES) and score >= cutoff
        ]
        if len(selected) < min_selected:
            continue

        true_count = sum(outcome in config["positive_outcomes"] for outcome in selected)
        precision = true_count / len(selected)
        recall = true_count / all_positive if all_positive else 0.0
        candidates.append({
            "cutoff": cutoff,
            "selected_count": len(selected),
            "positive_count": true_count,
            "precision": precision,
            "recall": recall,
        })

    if not candidates:
        raise ValueError("unable to derive TRAIN-only score cutoff")

    best = max(
        candidates,
        key=lambda item: (
            item["precision"],
            item["recall"],
            item["cutoff"],
        ),
    )
    return {"selected": best, "all_candidates": candidates}


def arm_sample_warning(
    train_rows: Sequence[tuple[dict[str, Any], dict[str, Any], str]],
    config: dict[str, Any],
) -> dict[str, Any]:
    pos = sum(outcome in config["positive_outcomes"] for _, _, outcome in train_rows)
    neg = sum(outcome in config["negative_outcomes"] for _, _, outcome in train_rows)
    low = pos < 5 or neg < 5
    return {
        "train_positive_count": pos,
        "train_negative_count": neg,
        "low_sample_warning": low,
        "message": (
            "TRAIN sample is small; treat thresholds as exploratory and do not promote "
            "to execution."
            if low
            else "TRAIN sample is adequate for this development-stage classifier."
        ),
    }


def decision_row(
    event: dict[str, Any],
    snap: dict[str, Any],
    outcome: str,
    arm_name: str,
    config: dict[str, Any],
    specs: dict[str, dict[str, Any]],
    cutoff: int,
) -> dict[str, Any]:
    score, available, passes, values = score_snapshot(snap, config, specs)
    decision_ts = parse_dt(snap.get("timestamp"))
    cancel_ts = cancel_timestamp(
        event,
        config["snapshot_kind"],
        config["cancel_timestamp_field"],
    )
    known_cancel = (
        cancel_ts is not None
        and decision_ts is not None
        and cancel_ts <= decision_ts
    )

    if known_cancel:
        decision = "CANCEL"
        option_side = "NONE"
    elif available == len(STANDARD_FEATURES) and score >= cutoff:
        decision = "TRADE_NOW"
        option_side = config["option_side"]
    else:
        decision = "WAIT"
        option_side = "NONE"

    reason_codes = [
        REASON_CODES[feature]
        for feature, passed in passes.items()
        if passed is True
    ]
    if known_cancel:
        reason_codes = ["OPPOSITE_RECLAIM_OR_FAILURE_ALREADY_CONFIRMED"] + reason_codes
    elif decision == "WAIT":
        reason_codes = ["EVIDENCE_SCORE_BELOW_TRADE_THRESHOLD"] + reason_codes

    reference_time = event.get("reference_start")
    break_time = (
        event.get("boundary_break_timestamp")
        if config["snapshot_kind"] == "PRIMARY"
        else event.get("reclaim_timestamp")
    )

    return {
        "session_date": event.get("session_date"),
        "block": event.get("block"),
        "arm": arm_name,
        "setup_type": config["setup_type"],
        "reference_candle": {
            "colour": event.get("reference_colour"),
            "start": reference_time,
            "midpoint": event.get("reference_midpoint"),
            "high": event.get("reference_high"),
            "low": event.get("reference_low"),
        },
        "break_direction": snap.get("setup_direction"),
        "break_time": break_time,
        "decision_time": snap.get("timestamp"),
        "decision": decision,
        "option_side": option_side,
        "score": score,
        "score_max": len(STANDARD_FEATURES),
        "evidence_score_pct": 100.0 * score / len(STANDARD_FEATURES),
        "score_cutoff": cutoff,
        "reason_codes": reason_codes,
        "feature_values": values,
        "feature_passes": passes,
        "actual_outcome": outcome,
        "known_cancel_by_decision_time": known_cancel,
    }


def summarize(rows: Sequence[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"count": len(rows), "decisions": {}}
    for decision in ("TRADE_NOW", "WAIT", "CANCEL"):
        selected = [row for row in rows if row["decision"] == decision]
        positives = sum(
            row["actual_outcome"] in config["positive_outcomes"]
            for row in selected
        )
        negatives = sum(
            row["actual_outcome"] in config["negative_outcomes"]
            for row in selected
        )
        out["decisions"][decision] = {
            "count": len(selected),
            "positive_count": positives,
            "negative_count": negatives,
            "positive_rate": positives / len(selected) if selected else None,
            "negative_rate": negatives / len(selected) if selected else None,
        }
    return out


def build_arm(payload: dict[str, Any], arm_name: str) -> dict[str, Any]:
    config = ARM_CONFIGS[arm_name]
    rows = eligible_events(payload, arm_name)
    train_rows = [row for row in rows if row[0].get("block") == TRAIN_BLOCK]

    specs = derive_specs_train_only(train_rows, config)
    cutoff_info = choose_cutoff_train_only(train_rows, config, specs)
    cutoff = int(cutoff_info["selected"]["cutoff"])

    decisions = [
        decision_row(event, snap, outcome, arm_name, config, specs, cutoff)
        for event, snap, outcome in rows
    ]

    block_summaries = {
        block: summarize(
            [row for row in decisions if row["block"] == block],
            config,
        )
        for block in (TRAIN_BLOCK, *VALIDATION_BLOCKS)
    }

    return {
        "arm": arm_name,
        "setup_type": config["setup_type"],
        "trade_option_side": config["option_side"],
        "decision_checkpoint": "T_PLUS_3",
        "positive_outcomes": sorted(config["positive_outcomes"]),
        "negative_outcomes": sorted(config["negative_outcomes"]),
        "sample_assessment": arm_sample_warning(train_rows, config),
        "feature_specs_train_only": specs,
        "score_cutoff_train_only": cutoff_info,
        "overall_summary": summarize(decisions, config),
        "block_summaries": block_summaries,
        "rows": decisions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Four-arm TRAIN-frozen midpoint decision research"
    )
    parser.add_argument("--framework", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = load_json(Path(args.framework))
    validate_source(payload)

    arms = {
        arm_name: build_arm(payload, arm_name)
        for arm_name in ARM_CONFIGS
    }

    compact_summary = {
        arm_name: {
            "sample_assessment": arm["sample_assessment"],
            "selected_cutoff": arm["score_cutoff_train_only"]["selected"],
            "overall_summary": arm["overall_summary"],
            "block_summaries": arm["block_summaries"],
        }
        for arm_name, arm in arms.items()
    }

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_research_version": SOURCE_VERSION,
        "research_status": "FOUR_ARM_TRAIN_FROZEN_T3_DECISION_RESEARCH",
        "standard_output_schema": {
            "decision_values": ["TRADE_NOW", "WAIT", "CANCEL"],
            "option_side_values": ["PE", "CE", "NONE"],
            "required_fields": [
                "session_date",
                "block",
                "setup_type",
                "reference_candle",
                "break_direction",
                "break_time",
                "decision_time",
                "decision",
                "option_side",
                "score",
                "score_max",
                "evidence_score_pct",
                "reason_codes",
                "actual_outcome",
            ],
        },
        "feature_family": list(STANDARD_FEATURES),
        "arms": arms,
        "compact_summary": compact_summary,
        "leakage_guard": {
            "thresholds_derived_from_train_only": True,
            "score_cutoffs_derived_from_train_only": True,
            "oos_a_b_c_d_used_for_threshold_selection": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "decision_uses_t3_or_earlier_data_only": True,
            "known_reclaim_or_failure_can_cancel_only_if_timestamp_le_t3": True,
            "pnl_used_for_rule_selection": False,
            "research_emits_trade_order": False,
        },
        "next_phase_gate": (
            "Do not attach option P&L until each arm's OOS-A/B/C/D behavior is reviewed. "
            "Low-sample reclaim arms must remain research-only unless validation is convincing."
        ),
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": result["status"],
        "research_version": RESEARCH_VERSION,
        "compact_summary": compact_summary,
        "leakage_guard": result["leakage_guard"],
        "output": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()
