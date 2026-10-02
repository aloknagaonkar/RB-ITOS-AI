from __future__ import annotations

"""
MIDPOINT_GLOBAL_EXEMPLAR_FEATURE_SEPARATION_V1

Descriptive separation study over the completed global 184-event artifact.

Compares:
- excellent/good bullish vs bullish failures
- excellent/good bearish vs bearish failures
- accepted winners vs accepted losers
- rejected winners vs rejected losers

No rule change, no threshold tuning, no promotion.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_GLOBAL_EXEMPLAR_FEATURE_SEPARATION_V1"

NUMERIC_FEATURES = (
    "acceptance_pct",
    "momentum_5m_directional",
    "progress_points",
    "giveback_from_best_checkpoint_points",
    "consecutive_closes",
    "velocity",
    "futures_vwap_distance_points",
)

ACCEPTED_FAMILIES = {
    "IMMEDIATE_CONTINUATION",
    "BASE_THEN_GO",
    "FAILED_BREAK_RECLAIM",
}

WIN_BUCKETS = {"EXCELLENT_5M_GE_10", "GOOD_5M_3_TO_10"}
LOSS_BUCKETS = {"LOSS_5M_0_TO_MINUS5", "LARGE_LOSS_5M_LE_MINUS5"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def num(v: Any) -> float | None:
    try:
        return float(v)
    except Exception:
        return None


def flatten(e: dict[str, Any]) -> dict[str, Any]:
    pf = e.get("price_features") or {}
    oi = e.get("oi") or {}
    fut = e.get("futures") or {}
    econ = e.get("option_economics") or {}
    return {
        "block": e.get("block"),
        "session_date": e.get("session_date"),
        "setup_type": e.get("setup_type"),
        "direction": e.get("direction"),
        "decision_family": e.get("decision_family"),
        "quality_bucket": e.get("quality_bucket"),
        "signal_timestamp": e.get("signal_timestamp"),
        "acceptance_pct": num(pf.get("acceptance_pct")),
        "momentum_5m_directional": num(pf.get("momentum_5m_directional")),
        "progress_points": num(pf.get("progress_points")),
        "giveback_from_best_checkpoint_points": num(pf.get("giveback_from_best_checkpoint_points")),
        "consecutive_closes": num(pf.get("consecutive_closes")),
        "velocity": num(pf.get("velocity")),
        "price_pass_count": num(e.get("price_pass_count")),
        "oi_quality": e.get("oi_quality"),
        "ce_state": oi.get("ce_state"),
        "pe_state": oi.get("pe_state"),
        "futures_vwap_distance_points": num(fut.get("distance_points")),
        "futures_vwap_distance_pct": num(fut.get("distance_pct")),
        "futures_vwap_aligned": fut.get("aligned"),
        "net_1m_pct": num(econ.get("net_1m_pct")),
        "net_3m_pct": num(econ.get("net_3m_pct")),
        "net_5m_pct": num(econ.get("net_5m_pct")),
        "net_10m_pct": num(econ.get("net_10m_pct")),
        "net_15m_pct": num(econ.get("net_15m_pct")),
        "mfe_pct_15m": num(econ.get("mfe_pct_15m")),
        "mae_pct_15m": num(econ.get("mae_pct_15m")),
    }


def summarize_numeric(rows: list[dict[str, Any]], feature: str) -> dict[str, Any]:
    vals = [float(r[feature]) for r in rows if r.get(feature) is not None]
    if not vals:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "count": len(vals),
        "mean": mean(vals),
        "median": median(vals),
        "min": min(vals),
        "max": max(vals),
    }


def categorical_counts(rows: list[dict[str, Any]], feature: str) -> dict[str, int]:
    return dict(Counter(str(r.get(feature)) for r in rows))


def compare_groups(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    numeric = {}
    for f in NUMERIC_FEATURES:
        sa = summarize_numeric(a, f)
        sb = summarize_numeric(b, f)
        numeric[f] = {
            "group_a": sa,
            "group_b": sb,
            "mean_delta_a_minus_b": (
                None if sa["mean"] is None or sb["mean"] is None
                else sa["mean"] - sb["mean"]
            ),
            "median_delta_a_minus_b": (
                None if sa["median"] is None or sb["median"] is None
                else sa["median"] - sb["median"]
            ),
        }
    return {
        "group_a_count": len(a),
        "group_b_count": len(b),
        "numeric": numeric,
        "categorical": {
            "price_pass_count": {
                "group_a": categorical_counts(a, "price_pass_count"),
                "group_b": categorical_counts(b, "price_pass_count"),
            },
            "oi_quality": {
                "group_a": categorical_counts(a, "oi_quality"),
                "group_b": categorical_counts(b, "oi_quality"),
            },
            "ce_state": {
                "group_a": categorical_counts(a, "ce_state"),
                "group_b": categorical_counts(b, "ce_state"),
            },
            "pe_state": {
                "group_a": categorical_counts(a, "pe_state"),
                "group_b": categorical_counts(b, "pe_state"),
            },
            "futures_vwap_aligned": {
                "group_a": categorical_counts(a, "futures_vwap_aligned"),
                "group_b": categorical_counts(b, "futures_vwap_aligned"),
            },
            "decision_family": {
                "group_a": categorical_counts(a, "decision_family"),
                "group_b": categorical_counts(b, "decision_family"),
            },
        },
    }


def is_win(r: dict[str, Any]) -> bool:
    return r.get("quality_bucket") in WIN_BUCKETS


def is_loss(r: dict[str, Any]) -> bool:
    return r.get("quality_bucket") in LOSS_BUCKETS


def is_accepted(r: dict[str, Any]) -> bool:
    return r.get("decision_family") in ACCEPTED_FAMILIES


def compact(r: dict[str, Any]) -> dict[str, Any]:
    return {
        k: r.get(k) for k in (
            "block", "session_date", "setup_type", "direction", "decision_family",
            "quality_bucket", "signal_timestamp",
            "acceptance_pct", "momentum_5m_directional", "progress_points",
            "giveback_from_best_checkpoint_points", "consecutive_closes", "velocity",
            "price_pass_count", "oi_quality", "ce_state", "pe_state",
            "futures_vwap_distance_points", "futures_vwap_aligned",
            "net_1m_pct", "net_3m_pct", "net_5m_pct", "net_10m_pct", "net_15m_pct",
            "mfe_pct_15m", "mae_pct_15m",
        )
    }


def top_abs_separators(comp: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f, d in comp["numeric"].items():
        delta = d.get("mean_delta_a_minus_b")
        if delta is not None:
            out.append({"feature": f, "mean_delta_a_minus_b": delta})
    out.sort(key=lambda x: abs(x["mean_delta_a_minus_b"]), reverse=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--global-analysis",
        required=True,
    )
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    src = load(Path(args.global_analysis))
    events = src.get("events")
    if not isinstance(events, list):
        raise SystemExit("global analysis missing top-level events")

    rows = [flatten(e) for e in events]
    if len(rows) != 184:
        raise SystemExit(f"expected 184 events, got {len(rows)}")

    bull = [r for r in rows if r["direction"] == "BULLISH"]
    bear = [r for r in rows if r["direction"] == "BEARISH"]

    groups = {
        "bullish_good_vs_bullish_failures": (
            [r for r in bull if is_win(r)],
            [r for r in bull if is_loss(r)],
        ),
        "bearish_good_vs_bearish_failures": (
            [r for r in bear if is_win(r)],
            [r for r in bear if is_loss(r)],
        ),
        "accepted_winners_vs_accepted_losers": (
            [r for r in rows if is_accepted(r) and is_win(r)],
            [r for r in rows if is_accepted(r) and is_loss(r)],
        ),
        "rejected_winners_vs_rejected_losers": (
            [r for r in rows if not is_accepted(r) and is_win(r)],
            [r for r in rows if not is_accepted(r) and is_loss(r)],
        ),
    }

    comparisons = {}
    for name, (a, b) in groups.items():
        comp = compare_groups(a, b)
        comp["largest_numeric_separators"] = top_abs_separators(comp)
        comparisons[name] = comp

    # Accepted winners/losers ranked for closest visual inspection.
    accepted_winners = groups["accepted_winners_vs_accepted_losers"][0]
    accepted_losers = groups["accepted_winners_vs_accepted_losers"][1]
    rejected_winners = groups["rejected_winners_vs_rejected_losers"][0]

    accepted_winners = sorted(
        accepted_winners, key=lambda r: r.get("net_5m_pct") or -999, reverse=True
    )
    accepted_losers = sorted(
        accepted_losers, key=lambda r: r.get("net_5m_pct") or 999
    )
    rejected_winners = sorted(
        rejected_winners, key=lambda r: r.get("net_5m_pct") or -999, reverse=True
    )

    out = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "research_status": "DESCRIPTIVE_ONLY_NO_RULE_CHANGE",
        "source_research_version": src.get("research_version"),
        "population": {
            "event_count": len(rows),
            "bullish_count": len(bull),
            "bearish_count": len(bear),
            "accepted_count": sum(1 for r in rows if is_accepted(r)),
            "rejected_count": sum(1 for r in rows if not is_accepted(r)),
            "winner_definition": sorted(WIN_BUCKETS),
            "loss_definition": sorted(LOSS_BUCKETS),
        },
        "comparisons": comparisons,
        "accepted_top_winners": [compact(r) for r in accepted_winners[:10]],
        "accepted_worst_losers": [compact(r) for r in accepted_losers[:10]],
        "rejected_top_winners": [compact(r) for r in rejected_winners[:10]],
        "sep7": [compact(r) for r in rows if r["session_date"] == "2026-09-07"],
        "integrity": {
            "threshold_tuning_performed": False,
            "strategy_rule_changed": False,
            "fresh_oos_consumed": False,
            "oos_e_f_g_h_used": False,
            "paper_or_live_order_emission_allowed": False,
            "retrospective_outcome_used_only_for_grouping": True,
        },
        "interpretation_guard": (
            "Large feature differences are descriptive signals only. "
            "Do not convert them directly into filters without freezing a candidate "
            "hypothesis and validating it on fresh precommitted sessions."
        ),
    }

    p = Path(args.output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "research_version": RESEARCH_VERSION,
        "population": out["population"],
        "bullish_good_vs_failures": comparisons["bullish_good_vs_bullish_failures"],
        "bearish_good_vs_failures": comparisons["bearish_good_vs_bearish_failures"],
        "accepted_winners_vs_losers": comparisons["accepted_winners_vs_accepted_losers"],
        "rejected_winners_vs_losers": comparisons["rejected_winners_vs_rejected_losers"],
        "accepted_top_winners": out["accepted_top_winners"][:5],
        "accepted_worst_losers": out["accepted_worst_losers"][:5],
        "rejected_top_winners": out["rejected_top_winners"][:5],
        "output": str(p),
    }, indent=2))


if __name__ == "__main__":
    main()
