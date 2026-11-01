"""Midpoint CONFIRM / WAIT / CANCEL state machine V3.1.

Corrections over V3
-------------------
1) Learn feature polarity from TRAIN instead of hard-coding it.
2) Mark equal/near-equal TRAIN medians NON_DISCRIMINATIVE.
3) Exclude NON_DISCRIMINATIVE features from the score denominator.
4) T+1 is informational only: DEVELOPING_STRONG / WAIT / FAILURE_RISK.
5) T+3 remains the only confirmation/cancel checkpoint.
6) OI remains a quality tier, not the primary trigger.

Research only. No P&L. No orders. TRAIN + OOS_A/B/C/D only.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_CONFIRM_WAIT_CANCEL_STATE_MACHINE_V3_1"
SOURCE_VERSION = "MIDPOINT_FAILURE_DIAGNOSTICS_V2_2"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}

FEATURES = (
    "acceptance_pct",
    "momentum_5m_directional",
    "progress_points",
    "progress_change_from_previous_checkpoint",
    "giveback_from_best_checkpoint_points",
    "consecutive_closes",
    "velocity",
)

# Relative equality tolerance only decides if the TRAIN medians are effectively
# indistinguishable. It does not use OOS information.
RELATIVE_EQUALITY_TOLERANCE = 0.05
ABSOLUTE_EQUALITY_FLOORS = {
    "acceptance_pct": 5.0,
    "momentum_5m_directional": 1.0,
    "progress_points": 0.5,
    "progress_change_from_previous_checkpoint": 0.5,
    "giveback_from_best_checkpoint_points": 0.5,
    "consecutive_closes": 0.5,
    "velocity": 0.25,
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

def is_near_equal(feature: str, a: float, b: float) -> bool:
    diff = abs(a - b)
    scale = max(abs(a), abs(b), 1.0)
    floor = ABSOLUTE_EQUALITY_FLOORS[feature]
    return diff <= max(floor, RELATIVE_EQUALITY_TOLERANCE * scale)

def derive_feature_rule(
    feature: str,
    continuation: list[float],
    reversal: list[float],
) -> dict[str, Any]:
    if not continuation or not reversal:
        return {
            "status": "UNAVAILABLE",
            "polarity": None,
            "threshold": None,
            "continuation_median": median(continuation) if continuation else None,
            "reversal_median": median(reversal) if reversal else None,
            "median_gap": None,
        }

    c = median(continuation)
    r = median(reversal)
    gap = c - r

    if is_near_equal(feature, c, r):
        return {
            "status": "NON_DISCRIMINATIVE",
            "polarity": None,
            "threshold": None,
            "continuation_median": c,
            "reversal_median": r,
            "median_gap": gap,
        }

    polarity = "HIGHER_IS_BETTER" if c > r else "LOWER_IS_BETTER"
    return {
        "status": "ACTIVE",
        "polarity": polarity,
        "threshold": (c + r) / 2.0,
        "continuation_median": c,
        "reversal_median": r,
        "median_gap": gap,
    }

def derive_thresholds(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for direction in ("BEARISH", "BULLISH"):
        out[direction] = {}
        for cp in (1, 3):
            train = [
                r for r in rows
                if r.get("block") == "TRAIN"
                and r.get("direction") == direction
                and r.get("checkpoint_minutes") == cp
                and r.get("outcome_label") in {"CONTINUATION", "REVERSAL"}
            ]
            rules = {}
            for feature in FEATURES:
                cont = values(
                    [r for r in train if r["outcome_label"] == "CONTINUATION"],
                    feature,
                )
                rev = values(
                    [r for r in train if r["outcome_label"] == "REVERSAL"],
                    feature,
                )
                rules[feature] = derive_feature_rule(feature, cont, rev)

            out[direction][f"T+{cp}"] = {
                "features": rules,
                "active_features": [
                    f for f, spec in rules.items()
                    if spec["status"] == "ACTIVE"
                ],
                "non_discriminative_features": [
                    f for f, spec in rules.items()
                    if spec["status"] == "NON_DISCRIMINATIVE"
                ],
            }
    return out

def pass_feature(value: float | None, spec: dict[str, Any]) -> bool | None:
    if spec.get("status") != "ACTIVE":
        return None
    threshold = spec.get("threshold")
    if value is None or threshold is None:
        return None
    if spec["polarity"] == "HIGHER_IS_BETTER":
        return value >= threshold
    if spec["polarity"] == "LOWER_IS_BETTER":
        return value <= threshold
    return None

def oi_quality(row: dict[str, Any]) -> str:
    level = str((row.get("oi") or {}).get("support_level") or "UNAVAILABLE")
    return level if level in {"STRONG", "SECONDARY", "NONE", "UNAVAILABLE"} else "UNAVAILABLE"

def score_row(row: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    direction = row["direction"]
    cp = int(row["checkpoint_minutes"])
    checkpoint = thresholds[direction][f"T+{cp}"]
    specs = checkpoint["features"]
    pf = row.get("price_features") or {}

    passes = {}
    for feature in FEATURES:
        passes[feature] = pass_feature(finite(pf.get(feature)), specs[feature])

    known = [x for x in passes.values() if x is not None]
    passed = sum(x is True for x in known)
    available = len(known)

    return {
        "feature_passes": passes,
        "active_features": checkpoint["active_features"],
        "non_discriminative_features": checkpoint["non_discriminative_features"],
        "price_pass_count": passed,
        "price_feature_available_count": available,
        "price_pass_ratio": passed / available if available else None,
        "oi_quality": oi_quality(row),
    }

def classify_t1(scored: dict[str, Any]) -> str:
    ratio = scored["price_pass_ratio"]
    if ratio is None:
        return "WAIT"

    # T+1 is informational only. It never authorizes an entry.
    if ratio >= 0.80:
        return "DEVELOPING_STRONG"
    if ratio <= 0.35:
        return "FAILURE_RISK"
    return "WAIT"

def classify_t3(scored: dict[str, Any], row: dict[str, Any]) -> str:
    ratio = scored["price_pass_ratio"]
    oi = scored["oi_quality"]
    pf = row.get("price_features") or {}

    acceptance = finite(pf.get("acceptance_pct"))
    progress = finite(pf.get("progress_points"))
    progress_change = finite(pf.get("progress_change_from_previous_checkpoint"))
    giveback = finite(pf.get("giveback_from_best_checkpoint_points"))
    acceptance_change = finite(pf.get("acceptance_change_from_previous_checkpoint"))

    if ratio is None:
        return "WAIT_BASE"

    # Strong price failure overrides supportive OI.
    if (
        acceptance is not None and acceptance <= 50.0
        and progress is not None and progress < 0.0
    ):
        return "CANCEL_BREAKOUT"

    # Reclaim-watch is intentionally stricter than V3 to reduce false cancels.
    if (
        progress is not None and progress < 0.0
        and progress_change is not None and progress_change < 0.0
        and giveback is not None and giveback > 0.0
        and acceptance_change is not None and acceptance_change < 0.0
        and ratio <= 0.50
    ):
        return "RECLAIM_WATCH"

    # Confirmation remains price-first. Supportive OI upgrades strong price.
    if ratio >= 0.75:
        if oi in {"STRONG", "SECONDARY"}:
            return "CONFIRM_CONTINUATION"
        return "WAIT_BASE"

    if ratio <= 0.25:
        return "CANCEL_BREAKOUT"

    return "WAIT_BASE"

def build_events(
    rows: list[dict[str, Any]],
    thresholds: dict[str, Any],
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
        s1 = score_row(t1, thresholds)
        s3 = score_row(t3, thresholds)

        events.append({
            "block": t3.get("block"),
            "session_date": t3.get("session_date"),
            "setup_type": t3.get("setup_type"),
            "direction": t3.get("direction"),
            "primary_outcome": t3.get("primary_outcome"),
            "outcome_label": t3.get("outcome_label"),
            "t1_state": classify_t1(s1),
            "t3_state": classify_t3(s3, t3),
            "t1_score": s1,
            "t3_score": s3,
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
                "t1_states": dict(Counter(e["t1_state"] for e in d)),
                "t3_states": dict(Counter(e["t3_state"] for e in d)),
            },
            "CONTINUATION": {},
            "REVERSAL": {},
            "by_block": {},
        }

        for label in ("CONTINUATION", "REVERSAL"):
            p = [e for e in d if e["outcome_label"] == label]
            out[direction][label] = {
                "count": len(p),
                "t1_states": dict(Counter(e["t1_state"] for e in p)),
                "t3_states": dict(Counter(e["t3_state"] for e in p)),
            }

        for block in ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"):
            b = [e for e in d if e["block"] == block]
            out[direction]["by_block"][block] = {}
            for label in ("CONTINUATION", "REVERSAL"):
                p = [e for e in b if e["outcome_label"] == label]
                out[direction]["by_block"][block][label] = {
                    "count": len(p),
                    "t1_states": dict(Counter(e["t1_state"] for e in p)),
                    "t3_states": dict(Counter(e["t3_state"] for e in p)),
                }
    return out

def quality(summary: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for direction in ("BEARISH", "BULLISH"):
        d = summary[direction]
        cont = d["CONTINUATION"]
        rev = d["REVERSAL"]

        cstates = cont["t3_states"]
        rstates = rev["t3_states"]

        tp = cstates.get("CONFIRM_CONTINUATION", 0)
        fp = rstates.get("CONFIRM_CONTINUATION", 0)

        detected = (
            rstates.get("CANCEL_BREAKOUT", 0)
            + rstates.get("RECLAIM_WATCH", 0)
        )
        false_cancel = (
            cstates.get("CANCEL_BREAKOUT", 0)
            + cstates.get("RECLAIM_WATCH", 0)
        )

        out[direction] = {
            "confirm_precision": tp / (tp + fp) if (tp + fp) else None,
            "confirm_recall_of_continuations": (
                tp / cont["count"] if cont["count"] else None
            ),
            "failure_detection_rate": (
                detected / rev["count"] if rev["count"] else None
            ),
            "continuation_false_cancel_rate": (
                false_cancel / cont["count"] if cont["count"] else None
            ),
        }
    return out

def analyze(source: dict[str, Any]) -> dict[str, Any]:
    validate_source(source)
    rows = source.get("rows", [])
    thresholds = derive_thresholds(rows)
    events = build_events(rows, thresholds)
    summary = summarize(events)
    q = quality(summary)

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_version": SOURCE_VERSION,
        "corrections_over_v3": {
            "feature_polarity_learned_from_train": True,
            "near_equal_train_features_excluded": True,
            "non_discriminative_features_removed_from_denominator": True,
            "t1_informational_only": True,
            "t3_only_confirmation_checkpoint": True,
            "oi_is_quality_tier_not_trigger": True,
        },
        "threshold_method": {
            "selection_data": "TRAIN_ONLY",
            "active_feature_rule": (
                "continuation and reversal medians must differ beyond the "
                "feature-specific equality tolerance"
            ),
            "polarity_rule": (
                "continuation median > reversal median => HIGHER_IS_BETTER; "
                "continuation median < reversal median => LOWER_IS_BETTER"
            ),
            "threshold_rule": "midpoint of TRAIN continuation/reversal medians",
        },
        "thresholds_train_only": thresholds,
        "quality": q,
        "summary": summary,
        "leakage_guard": {
            "thresholds_derived_from_train_only": True,
            "feature_polarity_derived_from_train_only": True,
            "oos_a_b_c_d_used_for_threshold_selection": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "pnl_used_for_rule_selection": False,
            "t1_emits_entry_confirmation": False,
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
        "corrections_over_v3": result["corrections_over_v3"],
        "quality": result["quality"],
        "summary": result["summary"],
        "leakage_guard": result["leakage_guard"],
        "output": str(out),
    }, indent=2))

if __name__ == "__main__":
    main()
