"""Stable-feature midpoint state machine V3.2.

Purpose
-------
Refine V3.1 by reducing unstable checkpoint logic:

- T+1 is observation-only: OBSERVE_STRONG / OBSERVE_MIXED / OBSERVE_WEAK.
  It never confirms or cancels.
- T+3 is the only decision checkpoint.
- T+3 uses a smaller, structurally coherent feature set.
- Features must satisfy BOTH:
    1) structurally valid expected polarity, and
    2) minimum TRAIN effect size / median separation.
- TRAIN derives thresholds only.
- OOS_A/B/C/D validate unchanged.
- OOS_E/F/G/H are forbidden; H remains pristine.
- OI is confirmation quality only.
- No P&L, no order generation.

Research states at T+3
----------------------
CONFIRM_CONTINUATION
WAIT_BASE
CANCEL_BREAKOUT
RECLAIM_WATCH
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"
SOURCE_VERSION = "MIDPOINT_FAILURE_DIAGNOSTICS_V2_2"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}

# T+1 stays descriptive/observational only.
T1_OBSERVATION_FEATURES = (
    "momentum_5m_directional",
    "progress_points",
    "giveback_from_best_checkpoint_points",
    "acceptance_pct",
)

# Smaller stable T+3 feature set.
T3_FEATURES = (
    "acceptance_pct",
    "momentum_5m_directional",
    "progress_points",
    "giveback_from_best_checkpoint_points",
    "consecutive_closes",
    "velocity",
)

# Structural polarity is fixed by market meaning, not by noisy TRAIN reversals.
STRUCTURAL_POLARITY = {
    "acceptance_pct": "HIGHER_IS_BETTER",
    "momentum_5m_directional": "HIGHER_IS_BETTER",
    "progress_points": "HIGHER_IS_BETTER",
    "giveback_from_best_checkpoint_points": "LOWER_IS_BETTER",
    "consecutive_closes": "HIGHER_IS_BETTER",
    "velocity": "HIGHER_IS_BETTER",
}

# Minimum TRAIN median separation before a structurally valid feature may vote.
MIN_ABS_MEDIAN_GAP = {
    "acceptance_pct": 12.5,
    "momentum_5m_directional": 4.0,
    "progress_points": 2.0,
    "giveback_from_best_checkpoint_points": 1.5,
    "consecutive_closes": 1.0,
    "velocity": 0.75,
}

def load_json(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise ValueError("JSON root must be an object")
    return x

def finite(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None

def validate_source(x: dict[str, Any]) -> None:
    if x.get("research_version") != SOURCE_VERSION:
        raise ValueError(
            f"expected {SOURCE_VERSION}, got {x.get('research_version')!r}"
        )
    guard = x.get("leakage_guard") or {}
    if guard.get("oos_e_f_g_h_used") is not False:
        raise ValueError("source does not prove E/F/G/H excluded")
    if guard.get("oos_h_used") is not False:
        raise ValueError("source does not prove H excluded")
    blocks = {str(r.get("block")) for r in x.get("rows", [])}
    bad = blocks - ALLOWED_BLOCKS
    if bad:
        raise ValueError(f"forbidden blocks present: {sorted(bad)}")

def event_key(r: dict[str, Any]) -> tuple[Any, ...]:
    return (
        r.get("block"),
        r.get("session_date"),
        r.get("setup_type"),
        r.get("primary_outcome"),
    )

def values(rows: list[dict[str, Any]], feature: str) -> list[float]:
    out = []
    for r in rows:
        v = finite((r.get("price_features") or {}).get(feature))
        if v is not None:
            out.append(v)
    return out

def polarity_is_structurally_consistent(
    feature: str,
    continuation_median: float,
    reversal_median: float,
) -> bool:
    expected = STRUCTURAL_POLARITY[feature]
    if expected == "HIGHER_IS_BETTER":
        return continuation_median > reversal_median
    return continuation_median < reversal_median

def derive_t3_rules(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for direction in ("BEARISH", "BULLISH"):
        train = [
            r for r in rows
            if r.get("block") == "TRAIN"
            and r.get("direction") == direction
            and r.get("checkpoint_minutes") == 3
            and r.get("outcome_label") in {"CONTINUATION", "REVERSAL"}
        ]
        cont_rows = [r for r in train if r["outcome_label"] == "CONTINUATION"]
        rev_rows = [r for r in train if r["outcome_label"] == "REVERSAL"]

        rules = {}
        for feature in T3_FEATURES:
            cont = values(cont_rows, feature)
            rev = values(rev_rows, feature)
            if not cont or not rev:
                rules[feature] = {
                    "status": "UNAVAILABLE",
                    "reason": "missing_train_values",
                    "threshold": None,
                    "polarity": STRUCTURAL_POLARITY[feature],
                    "continuation_median": median(cont) if cont else None,
                    "reversal_median": median(rev) if rev else None,
                    "median_gap": None,
                }
                continue

            c = median(cont)
            r = median(rev)
            gap = c - r
            structurally_consistent = polarity_is_structurally_consistent(
                feature, c, r
            )
            enough_separation = abs(gap) >= MIN_ABS_MEDIAN_GAP[feature]

            if not structurally_consistent:
                status = "DIAGNOSTIC_ONLY"
                reason = "train_direction_conflicts_with_structural_polarity"
                threshold = None
            elif not enough_separation:
                status = "DIAGNOSTIC_ONLY"
                reason = "train_effect_size_below_minimum"
                threshold = None
            else:
                status = "ACTIVE"
                reason = "structurally_consistent_and_train_effect_sufficient"
                threshold = (c + r) / 2.0

            rules[feature] = {
                "status": status,
                "reason": reason,
                "threshold": threshold,
                "polarity": STRUCTURAL_POLARITY[feature],
                "continuation_median": c,
                "reversal_median": r,
                "median_gap": gap,
                "minimum_abs_median_gap": MIN_ABS_MEDIAN_GAP[feature],
            }

        out[direction] = {
            "features": rules,
            "active_features": [
                f for f, s in rules.items() if s["status"] == "ACTIVE"
            ],
            "diagnostic_only_features": [
                f for f, s in rules.items() if s["status"] == "DIAGNOSTIC_ONLY"
            ],
        }
    return out

def pass_feature(value: float | None, spec: dict[str, Any]) -> bool | None:
    if spec.get("status") != "ACTIVE":
        return None
    if value is None or spec.get("threshold") is None:
        return None
    if spec["polarity"] == "HIGHER_IS_BETTER":
        return value >= spec["threshold"]
    return value <= spec["threshold"]

def oi_quality(row: dict[str, Any]) -> str:
    level = str((row.get("oi") or {}).get("support_level") or "UNAVAILABLE")
    return level if level in {"STRONG", "SECONDARY", "NONE", "UNAVAILABLE"} else "UNAVAILABLE"

def observe_t1(row: dict[str, Any]) -> dict[str, Any]:
    pf = row.get("price_features") or {}
    momentum = finite(pf.get("momentum_5m_directional"))
    progress = finite(pf.get("progress_points"))
    giveback = finite(pf.get("giveback_from_best_checkpoint_points"))
    acceptance = finite(pf.get("acceptance_pct"))

    # No TRAIN thresholding here. This is descriptive only.
    favorable = 0
    adverse = 0

    if momentum is not None:
        favorable += momentum > 0
        adverse += momentum < 0
    if progress is not None:
        favorable += progress > 0
        adverse += progress < 0
    if giveback is not None:
        favorable += giveback == 0
        adverse += giveback > 0
    if acceptance is not None:
        favorable += acceptance >= 100.0
        adverse += acceptance <= 50.0

    if favorable >= 3 and adverse == 0:
        state = "OBSERVE_STRONG"
    elif adverse >= 2:
        state = "OBSERVE_WEAK"
    else:
        state = "OBSERVE_MIXED"

    return {
        "state": state,
        "favorable_observations": favorable,
        "adverse_observations": adverse,
        "oi_quality": oi_quality(row),
    }

def score_t3(row: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    direction = row["direction"]
    checkpoint = rules[direction]
    specs = checkpoint["features"]
    pf = row.get("price_features") or {}

    passes = {}
    for feature in T3_FEATURES:
        passes[feature] = pass_feature(finite(pf.get(feature)), specs[feature])

    known = [v for v in passes.values() if v is not None]
    passed = sum(v is True for v in known)
    available = len(known)

    return {
        "feature_passes": passes,
        "active_features": checkpoint["active_features"],
        "diagnostic_only_features": checkpoint["diagnostic_only_features"],
        "price_pass_count": passed,
        "price_feature_available_count": available,
        "price_pass_ratio": passed / available if available else None,
        "oi_quality": oi_quality(row),
    }

def classify_t3(row: dict[str, Any], scored: dict[str, Any]) -> str:
    pf = row.get("price_features") or {}
    ratio = scored["price_pass_ratio"]
    oi = scored["oi_quality"]

    acceptance = finite(pf.get("acceptance_pct"))
    momentum = finite(pf.get("momentum_5m_directional"))
    progress = finite(pf.get("progress_points"))
    giveback = finite(pf.get("giveback_from_best_checkpoint_points"))
    closes = finite(pf.get("consecutive_closes"))
    velocity = finite(pf.get("velocity"))

    if ratio is None:
        return "WAIT_BASE"

    # Clear rejection: weak acceptance + negative progress.
    if (
        acceptance is not None and acceptance <= 50.0
        and progress is not None and progress < 0.0
    ):
        return "CANCEL_BREAKOUT"

    # Reclaim watch requires multiple aligned failure symptoms.
    failure_symptoms = 0
    if progress is not None and progress < 0.0:
        failure_symptoms += 1
    if momentum is not None and momentum <= 0.0:
        failure_symptoms += 1
    if giveback is not None and giveback >= 5.0:
        failure_symptoms += 1
    if closes is not None and closes <= 1:
        failure_symptoms += 1
    if velocity is not None and velocity < 0.0:
        failure_symptoms += 1

    if failure_symptoms >= 3:
        return "RECLAIM_WATCH"

    # Strong price structure, supportive OI.
    if ratio >= 0.75 and oi in {"STRONG", "SECONDARY"}:
        return "CONFIRM_CONTINUATION"

    # Strong price structure but OI weak/unknown: stay patient.
    if ratio >= 0.75:
        return "WAIT_BASE"

    # Very weak stable-feature evidence.
    if ratio <= 0.25:
        return "CANCEL_BREAKOUT"

    return "WAIT_BASE"

def build_events(
    rows: list[dict[str, Any]],
    rules: dict[str, Any],
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if (
            r.get("checkpoint_minutes") in {1, 3}
            and r.get("outcome_label") in {"CONTINUATION", "REVERSAL"}
        ):
            groups[event_key(r)].append(r)

    events = []
    for group in groups.values():
        by_cp = {int(r["checkpoint_minutes"]): r for r in group}
        if 1 not in by_cp or 3 not in by_cp:
            continue

        t1 = by_cp[1]
        t3 = by_cp[3]
        t1_obs = observe_t1(t1)
        t3_score = score_t3(t3, rules)
        t3_state = classify_t3(t3, t3_score)

        events.append({
            "block": t3.get("block"),
            "session_date": t3.get("session_date"),
            "setup_type": t3.get("setup_type"),
            "direction": t3.get("direction"),
            "primary_outcome": t3.get("primary_outcome"),
            "outcome_label": t3.get("outcome_label"),
            "t1_observation_state": t1_obs["state"],
            "t1_observation": t1_obs,
            "t3_state": t3_state,
            "t3_score": t3_score,
            "exact_oi_transition_t1_to_t3": t3.get(
                "exact_oi_transition_t1_to_t3"
            ),
        })
    return events

def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for direction in ("BEARISH", "BULLISH"):
        d = [e for e in events if e["direction"] == direction]
        out[direction] = {
            "overall": {
                "count": len(d),
                "t1_observation_states": dict(Counter(
                    e["t1_observation_state"] for e in d
                )),
                "t3_states": dict(Counter(e["t3_state"] for e in d)),
            },
            "CONTINUATION": {},
            "REVERSAL": {},
            "by_block": {},
        }

        for label in ("CONTINUATION", "REVERSAL"):
            part = [e for e in d if e["outcome_label"] == label]
            out[direction][label] = {
                "count": len(part),
                "t1_observation_states": dict(Counter(
                    e["t1_observation_state"] for e in part
                )),
                "t3_states": dict(Counter(e["t3_state"] for e in part)),
            }

        for block in ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"):
            bp = [e for e in d if e["block"] == block]
            out[direction]["by_block"][block] = {}
            for label in ("CONTINUATION", "REVERSAL"):
                part = [e for e in bp if e["outcome_label"] == label]
                out[direction]["by_block"][block][label] = {
                    "count": len(part),
                    "t3_states": dict(Counter(e["t3_state"] for e in part)),
                }
    return out

def quality(summary: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for direction in ("BEARISH", "BULLISH"):
        d = summary[direction]
        cont = d["CONTINUATION"]
        rev = d["REVERSAL"]

        c = cont["t3_states"]
        r = rev["t3_states"]

        tp = c.get("CONFIRM_CONTINUATION", 0)
        fp = r.get("CONFIRM_CONTINUATION", 0)

        failure_detected = (
            r.get("CANCEL_BREAKOUT", 0)
            + r.get("RECLAIM_WATCH", 0)
        )
        false_cancel = (
            c.get("CANCEL_BREAKOUT", 0)
            + c.get("RECLAIM_WATCH", 0)
        )

        out[direction] = {
            "confirm_precision": tp / (tp + fp) if (tp + fp) else None,
            "confirm_recall_of_continuations": (
                tp / cont["count"] if cont["count"] else None
            ),
            "failure_detection_rate": (
                failure_detected / rev["count"] if rev["count"] else None
            ),
            "continuation_false_cancel_rate": (
                false_cancel / cont["count"] if cont["count"] else None
            ),
        }
    return out

def analyze(source: dict[str, Any]) -> dict[str, Any]:
    validate_source(source)
    rows = source.get("rows", [])
    rules = derive_t3_rules(rows)
    events = build_events(rows, rules)
    summary = summarize(events)

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_version": SOURCE_VERSION,
        "design": {
            "t1_observation_only": True,
            "t1_can_confirm": False,
            "t1_can_cancel": False,
            "t3_only_decision_checkpoint": True,
            "price_structure_primary": True,
            "oi_is_quality_tier_not_trigger": True,
            "stable_feature_gate": (
                "structural polarity must agree with TRAIN direction and "
                "TRAIN median gap must exceed minimum effect size"
            ),
        },
        "t3_train_only_rules": rules,
        "quality": quality(summary),
        "summary": summary,
        "leakage_guard": {
            "thresholds_derived_from_train_only": True,
            "feature_activation_derived_from_train_only": True,
            "structural_polarity_defined_a_priori": True,
            "oos_a_b_c_d_used_for_threshold_selection": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "pnl_used_for_rule_selection": False,
            "t1_emits_entry_confirmation": False,
            "t1_emits_cancel": False,
            "research_only": True,
            "research_emits_trade_order": False,
        },
        "events": events,
    }

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    result = analyze(load_json(Path(a.source)))
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": result["status"],
        "research_version": result["research_version"],
        "design": result["design"],
        "quality": result["quality"],
        "summary": result["summary"],
        "leakage_guard": result["leakage_guard"],
        "output": str(out),
    }, indent=2))

if __name__ == "__main__":
    main()
