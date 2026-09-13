"""Research-only midpoint CONFIRM / WAIT / CANCEL state machine V3.

Consumes:
  MIDPOINT_FAILURE_DIAGNOSTICS_V2_2

Design goals
------------
- RED/bearish and GREEN/bullish are modeled independently.
- Candidate thresholds are derived from TRAIN only.
- OOS_A/B/C/D validate thresholds unchanged.
- E/F/G/H are forbidden; OOS-H remains pristine.
- Price structure is primary.
- OI is a quality tier, not the main trigger.
- No P&L is used for threshold selection.
- No trade orders are emitted.

State flow
----------
BOUNDARY_BROKEN
  -> EARLY_CHECK_T1
       -> EARLY_STRONG
       -> WAIT
       -> FAILURE_RISK
  -> FINAL_CHECK_T3
       -> CONFIRM_CONTINUATION
       -> WAIT_BASE
       -> CANCEL_BREAKOUT
       -> RECLAIM_WATCH

This is a research classifier, not a live execution engine.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_CONFIRM_WAIT_CANCEL_STATE_MACHINE_V3"
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

HIGHER_IS_BETTER = {
    "acceptance_pct": True,
    "momentum_5m_directional": True,
    "progress_points": True,
    "progress_change_from_previous_checkpoint": True,
    "giveback_from_best_checkpoint_points": False,
    "consecutive_closes": True,
    "velocity": True,
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
        raise ValueError("source does not prove OOS_E/F/G/H excluded")
    if guard.get("oos_h_used") is not False:
        raise ValueError("source does not prove OOS_H excluded")
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

def _vals(rows: list[dict[str, Any]], feature: str) -> list[float]:
    out = []
    for r in rows:
        v = finite((r.get("price_features") or {}).get(feature))
        if v is not None:
            out.append(v)
    return out

def _threshold_from_train(
    continuation: list[float],
    reversal: list[float],
    higher_is_better: bool,
) -> dict[str, Any]:
    if not continuation or not reversal:
        return {
            "threshold": None,
            "continuation_median": median(continuation) if continuation else None,
            "reversal_median": median(reversal) if reversal else None,
            "higher_is_better": higher_is_better,
        }
    c = median(continuation)
    r = median(reversal)
    return {
        "threshold": (c + r) / 2.0,
        "continuation_median": c,
        "reversal_median": r,
        "higher_is_better": higher_is_better,
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
            out[direction][f"T+{cp}"] = {}
            for feat in FEATURES:
                cont = _vals(
                    [r for r in train if r.get("outcome_label") == "CONTINUATION"],
                    feat,
                )
                rev = _vals(
                    [r for r in train if r.get("outcome_label") == "REVERSAL"],
                    feat,
                )
                out[direction][f"T+{cp}"][feat] = _threshold_from_train(
                    cont, rev, HIGHER_IS_BETTER[feat]
                )
    return out

def pass_feature(value: float | None, spec: dict[str, Any]) -> bool | None:
    threshold = spec.get("threshold")
    if value is None or threshold is None:
        return None
    return value >= threshold if spec["higher_is_better"] else value <= threshold

def oi_quality(row: dict[str, Any]) -> str:
    level = str((row.get("oi") or {}).get("support_level") or "UNAVAILABLE")
    if level in {"STRONG", "SECONDARY", "NONE", "UNAVAILABLE"}:
        return level
    return "UNAVAILABLE"

def score_row(row: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    direction = row["direction"]
    cp = int(row["checkpoint_minutes"])
    specs = thresholds[direction][f"T+{cp}"]
    pf = row.get("price_features") or {}

    passes = {}
    for feat in FEATURES:
        passes[feat] = pass_feature(finite(pf.get(feat)), specs[feat])

    known = [v for v in passes.values() if v is not None]
    passed = sum(v is True for v in known)
    available = len(known)
    ratio = passed / available if available else None

    return {
        "feature_passes": passes,
        "price_pass_count": passed,
        "price_feature_available_count": available,
        "price_pass_ratio": ratio,
        "oi_quality": oi_quality(row),
    }

def classify_t1(direction: str, scored: dict[str, Any]) -> str:
    ratio = scored["price_pass_ratio"]
    oi = scored["oi_quality"]

    if ratio is None:
        return "WAIT"

    # GREEN/bullish gets a slightly more permissive early-confirm path because
    # V2.2 showed cleaner T+1 separation. RED/bearish remains more conservative.
    if direction == "BULLISH":
        if ratio >= 0.80 and oi in {"STRONG", "SECONDARY"}:
            return "EARLY_STRONG"
        if ratio <= 0.35:
            return "FAILURE_RISK"
        return "WAIT"

    # Bearish: T+1 is mainly an early-warning checkpoint.
    if ratio >= 0.90 and oi == "STRONG":
        return "EARLY_STRONG"
    if ratio <= 0.35:
        return "FAILURE_RISK"
    return "WAIT"

def classify_t3(
    direction: str,
    scored: dict[str, Any],
    row: dict[str, Any],
) -> str:
    ratio = scored["price_pass_ratio"]
    oi = scored["oi_quality"]
    pf = row.get("price_features") or {}

    acceptance = finite(pf.get("acceptance_pct"))
    progress = finite(pf.get("progress_points"))
    giveback = finite(pf.get("giveback_from_best_checkpoint_points"))
    acceptance_change = finite(pf.get("acceptance_change_from_previous_checkpoint"))

    if ratio is None:
        return "WAIT_BASE"

    # Hard structural failure indicators. Price wins over supportive OI.
    if (
        (acceptance is not None and acceptance <= 50.0)
        and (progress is not None and progress < 0.0)
    ):
        return "CANCEL_BREAKOUT"

    if (
        progress is not None and progress < 0.0
        and giveback is not None and giveback > 0.0
        and acceptance_change is not None and acceptance_change < 0.0
    ):
        return "RECLAIM_WATCH"

    # Strong structural continuation. OI improves quality but is not mandatory.
    if ratio >= 0.75:
        if oi in {"STRONG", "SECONDARY"}:
            return "CONFIRM_CONTINUATION"
        # strong price with weak OI remains a base/wait state rather than cancel
        return "WAIT_BASE"

    if ratio <= 0.35:
        return "CANCEL_BREAKOUT"

    return "WAIT_BASE"

def build_event_records(
    rows: list[dict[str, Any]],
    thresholds: dict[str, Any],
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("checkpoint_minutes") in {1, 3}:
            if r.get("outcome_label") in {"CONTINUATION", "REVERSAL"}:
                groups[event_key(r)].append(r)

    events = []
    for key, group in groups.items():
        by_cp = {int(r["checkpoint_minutes"]): r for r in group}
        if 1 not in by_cp or 3 not in by_cp:
            continue

        t1 = by_cp[1]
        t3 = by_cp[3]
        s1 = score_row(t1, thresholds)
        s3 = score_row(t3, thresholds)

        t1_state = classify_t1(t1["direction"], s1)
        t3_state = classify_t3(t3["direction"], s3, t3)

        events.append({
            "block": t3.get("block"),
            "session_date": t3.get("session_date"),
            "setup_type": t3.get("setup_type"),
            "direction": t3.get("direction"),
            "primary_outcome": t3.get("primary_outcome"),
            "outcome_label": t3.get("outcome_label"),
            "t1_state": t1_state,
            "t3_state": t3_state,
            "t1_score": s1,
            "t3_score": s3,
            "t1_exact_oi_transition_t1_to_t3": t1.get("exact_oi_transition_t1_to_t3"),
            "t3_exact_oi_transition_t1_to_t3": t3.get("exact_oi_transition_t1_to_t3"),
        })
    return events

def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for direction in ("BEARISH", "BULLISH"):
        out[direction] = {}
        subset_d = [e for e in events if e["direction"] == direction]

        out[direction]["overall"] = {
            "count": len(subset_d),
            "t1_states": dict(Counter(e["t1_state"] for e in subset_d)),
            "t3_states": dict(Counter(e["t3_state"] for e in subset_d)),
        }

        for label in ("CONTINUATION", "REVERSAL"):
            part = [e for e in subset_d if e["outcome_label"] == label]
            out[direction][label] = {
                "count": len(part),
                "t1_states": dict(Counter(e["t1_state"] for e in part)),
                "t3_states": dict(Counter(e["t3_state"] for e in part)),
            }

        out[direction]["by_block"] = {}
        for block in ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"):
            bp = [e for e in subset_d if e["block"] == block]
            out[direction]["by_block"][block] = {
                "count": len(bp),
                "continuation": {
                    "count": sum(e["outcome_label"] == "CONTINUATION" for e in bp),
                    "t3_states": dict(Counter(
                        e["t3_state"] for e in bp
                        if e["outcome_label"] == "CONTINUATION"
                    )),
                },
                "reversal": {
                    "count": sum(e["outcome_label"] == "REVERSAL" for e in bp),
                    "t3_states": dict(Counter(
                        e["t3_state"] for e in bp
                        if e["outcome_label"] == "REVERSAL"
                    )),
                },
            }
    return out

def state_quality(summary: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for direction in ("BEARISH", "BULLISH"):
        d = summary[direction]
        cont = d["CONTINUATION"]["t3_states"]
        rev = d["REVERSAL"]["t3_states"]

        confirm_tp = cont.get("CONFIRM_CONTINUATION", 0)
        confirm_fp = rev.get("CONFIRM_CONTINUATION", 0)
        cancel_tn = rev.get("CANCEL_BREAKOUT", 0) + rev.get("RECLAIM_WATCH", 0)
        cancel_fn = cont.get("CANCEL_BREAKOUT", 0) + cont.get("RECLAIM_WATCH", 0)

        out[direction] = {
            "confirm_precision": (
                confirm_tp / (confirm_tp + confirm_fp)
                if (confirm_tp + confirm_fp) else None
            ),
            "confirm_recall_of_continuations": (
                confirm_tp / d["CONTINUATION"]["count"]
                if d["CONTINUATION"]["count"] else None
            ),
            "failure_detection_rate": (
                cancel_tn / d["REVERSAL"]["count"]
                if d["REVERSAL"]["count"] else None
            ),
            "continuation_false_cancel_rate": (
                cancel_fn / d["CONTINUATION"]["count"]
                if d["CONTINUATION"]["count"] else None
            ),
        }
    return out

def analyze(source: dict[str, Any]) -> dict[str, Any]:
    validate_source(source)
    rows = source.get("rows", [])
    thresholds = derive_thresholds(rows)
    events = build_event_records(rows, thresholds)
    summary = summarize_events(events)
    quality = state_quality(summary)

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_version": SOURCE_VERSION,
        "design": {
            "price_structure_primary": True,
            "oi_is_quality_tier_not_trigger": True,
            "bearish_and_bullish_independent": True,
            "t1_role": {
                "BEARISH": "EARLY_WARNING_WITH_RARE_EARLY_STRONG",
                "BULLISH": "EARLY_CHECK_WITH_POSSIBLE_EARLY_STRONG",
            },
            "t3_role": "PRIMARY_CONFIRM_WAIT_CANCEL_CHECKPOINT",
        },
        "thresholds_train_only": thresholds,
        "summary": summary,
        "quality": quality,
        "leakage_guard": {
            "thresholds_derived_from_train_only": True,
            "oos_a_b_c_d_used_for_threshold_selection": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "pnl_used_for_rule_selection": False,
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
