"""Feature diagnostics for midpoint break strength/failure V2.1.

Reads the output of MIDPOINT_BREAK_STRENGTH_AND_FAILURE_V2 and compares
CONTINUATION vs REVERSAL at T+1 and T+3, separately by direction and block.

Purpose:
- identify which price features actually separate continuation from reversal;
- inspect CE/PE OI-state distributions and transitions;
- avoid creating another opaque aggregate score before understanding drivers.

This is descriptive research only. It does not alter trade decisions.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_FAILURE_FEATURE_DIAGNOSTICS_V2_1"
SOURCE_VERSION = "MIDPOINT_BREAK_STRENGTH_AND_FAILURE_V2"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
CHECKPOINTS = (1, 3)

PRICE_FEATURES = (
    "momentum_5m",
    "acceptance_pct",
    "consecutive_closes",
    "extreme_count",
    "progress_points",
    "velocity",
    "rebound_points",
    "midpoint_cross_count",
)

def load_json(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise ValueError("JSON root must be an object")
    return x

def validate_source(x: dict[str, Any]) -> None:
    if x.get("research_version") != SOURCE_VERSION:
        raise ValueError(
            f"expected {SOURCE_VERSION}, got {x.get('research_version')!r}"
        )
    guard = x.get("leakage_guard") or {}
    if guard.get("oos_e_f_g_h_used") is not False:
        raise ValueError("source does not prove E/F/G/H were excluded")
    if guard.get("oos_h_used") is not False:
        raise ValueError("source does not prove H was excluded")

    blocks = {str(r.get("block")) for r in x.get("rows", [])}
    bad = blocks - ALLOWED_BLOCKS
    if bad:
        raise ValueError(f"forbidden blocks present: {sorted(bad)}")

def _finite(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None

def _stats(values: list[float]) -> dict[str, Any]:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if not vals:
        return {"count": 0, "median": None, "mean": None, "min": None, "max": None}
    return {
        "count": len(vals),
        "median": median(vals),
        "mean": sum(vals) / len(vals),
        "min": min(vals),
        "max": max(vals),
    }

def _feature_values(rows: list[dict[str, Any]], feature: str) -> list[float]:
    out = []
    for r in rows:
        v = _finite((r.get("price_features") or {}).get(feature))
        if v is not None:
            out.append(v)
    return out

def _median_gap(cont: dict[str, Any], rev: dict[str, Any]) -> float | None:
    if cont["median"] is None or rev["median"] is None:
        return None
    return cont["median"] - rev["median"]

def _oi_pair(r: dict[str, Any]) -> str:
    oi = r.get("oi") or {}
    return f"{oi.get('ce_state') or 'NA'}|{oi.get('pe_state') or 'NA'}"

def _transition_pair(prev: dict[str, Any] | None, cur: dict[str, Any]) -> str:
    if prev is None:
        return "INITIAL"
    p = prev.get("oi") or {}
    c = cur.get("oi") or {}
    return (
        f"CE:{p.get('ce_state') or 'NA'}->{c.get('ce_state') or 'NA'};"
        f"PE:{p.get('pe_state') or 'NA'}->{c.get('pe_state') or 'NA'}"
    )

def build_event_groups(rows: list[dict[str, Any]]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    g = defaultdict(list)
    for r in rows:
        if r.get("checkpoint_minutes") not in CHECKPOINTS:
            continue
        if r.get("outcome_label") not in {"CONTINUATION", "REVERSAL"}:
            continue
        key = (
            r.get("block"),
            r.get("session_date"),
            r.get("setup_type"),
            r.get("primary_outcome"),
        )
        g[key].append(r)
    for xs in g.values():
        xs.sort(key=lambda r: r["checkpoint_minutes"])
    return g

def transition_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    groups = build_event_groups(rows)
    counts = Counter()
    for xs in groups.values():
        by_cp = {r["checkpoint_minutes"]: r for r in xs}
        if 1 in by_cp and 3 in by_cp:
            counts[_transition_pair(by_cp[1], by_cp[3])] += 1
    return dict(counts)

def summarize_slice(rows: list[dict[str, Any]]) -> dict[str, Any]:
    feature_summary = {}
    for feature in PRICE_FEATURES:
        cont_rows = [r for r in rows if r["outcome_label"] == "CONTINUATION"]
        rev_rows = [r for r in rows if r["outcome_label"] == "REVERSAL"]
        cont = _stats(_feature_values(cont_rows, feature))
        rev = _stats(_feature_values(rev_rows, feature))
        feature_summary[feature] = {
            "continuation": cont,
            "reversal": rev,
            "median_gap_cont_minus_rev": _median_gap(cont, rev),
        }

    cont_rows = [r for r in rows if r["outcome_label"] == "CONTINUATION"]
    rev_rows = [r for r in rows if r["outcome_label"] == "REVERSAL"]

    return {
        "count": len(rows),
        "continuation_count": len(cont_rows),
        "reversal_count": len(rev_rows),
        "features": feature_summary,
        "continuation_oi_support": dict(Counter(
            (r.get("oi") or {}).get("support_level", "UNAVAILABLE") for r in cont_rows
        )),
        "reversal_oi_support": dict(Counter(
            (r.get("oi") or {}).get("support_level", "UNAVAILABLE") for r in rev_rows
        )),
        "continuation_oi_pairs": dict(Counter(_oi_pair(r) for r in cont_rows)),
        "reversal_oi_pairs": dict(Counter(_oi_pair(r) for r in rev_rows)),
        "continuation_oi_transition_labels": dict(Counter(
            r.get("oi_transition", "UNKNOWN") for r in cont_rows
        )),
        "reversal_oi_transition_labels": dict(Counter(
            r.get("oi_transition", "UNKNOWN") for r in rev_rows
        )),
        "continuation_t1_to_t3_state_transitions": transition_counts(cont_rows),
        "reversal_t1_to_t3_state_transitions": transition_counts(rev_rows),
    }

def analyze(source: dict[str, Any]) -> dict[str, Any]:
    validate_source(source)
    rows = source.get("rows", [])

    pooled = {}
    by_block = {}

    for direction in ("BEARISH", "BULLISH"):
        pooled[direction] = {}
        by_block[direction] = {}

        for cp in CHECKPOINTS:
            subset = [
                r for r in rows
                if r.get("direction") == direction
                and r.get("checkpoint_minutes") == cp
                and r.get("outcome_label") in {"CONTINUATION", "REVERSAL"}
            ]
            pooled[direction][f"T+{cp}"] = summarize_slice(subset)

        for block in ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"):
            by_block[direction][block] = {}
            for cp in CHECKPOINTS:
                subset = [
                    r for r in rows
                    if r.get("direction") == direction
                    and r.get("block") == block
                    and r.get("checkpoint_minutes") == cp
                    and r.get("outcome_label") in {"CONTINUATION", "REVERSAL"}
                ]
                by_block[direction][block][f"T+{cp}"] = summarize_slice(subset)

    # Rank pooled features by absolute median separation at each direction/checkpoint.
    rankings = {}
    for direction in ("BEARISH", "BULLISH"):
        rankings[direction] = {}
        for cp in ("T+1", "T+3"):
            items = []
            for feature, data in pooled[direction][cp]["features"].items():
                gap = data["median_gap_cont_minus_rev"]
                if gap is not None:
                    items.append({"feature": feature, "median_gap_cont_minus_rev": gap, "abs_gap": abs(gap)})
            items.sort(key=lambda x: x["abs_gap"], reverse=True)
            rankings[direction][cp] = items

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_version": SOURCE_VERSION,
        "objective": (
            "Explain which T+1/T+3 price and OI-state features separate "
            "continuation from reversal before defining a frozen confirm/wait/cancel rule."
        ),
        "checkpoints": ["T+1", "T+3"],
        "price_features": list(PRICE_FEATURES),
        "pooled": pooled,
        "by_block": by_block,
        "feature_rankings_by_abs_median_gap": rankings,
        "leakage_guard": {
            "descriptive_only": True,
            "new_thresholds_selected": False,
            "entry_rule_modified": False,
            "pnl_used": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "research_emits_trade_order": False,
        },
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

    compact = {
        "status": result["status"],
        "research_version": result["research_version"],
        "feature_rankings_by_abs_median_gap": result["feature_rankings_by_abs_median_gap"],
        "leakage_guard": result["leakage_guard"],
        "output": str(out),
    }
    print(json.dumps(compact, indent=2))

if __name__ == "__main__":
    main()
