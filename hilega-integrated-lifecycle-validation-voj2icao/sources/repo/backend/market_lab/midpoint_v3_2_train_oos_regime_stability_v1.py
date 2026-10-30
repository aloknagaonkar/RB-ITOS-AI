"""TRAIN-vs-OOS regime stability diagnostics for frozen Midpoint V3.2.

This module explains why the frozen exit candidate is negative in TRAIN while
pooled OOS_A/B/C/D is positive.

It performs diagnostics only. It does NOT:
- modify V3.2 entry logic;
- modify the frozen exit policy;
- select a filter;
- select a threshold;
- promote STRONG OI, direction, time, or outcome-family filters;
- use OOS_E/F/G/H.

Inputs
------
MIDPOINT_V3_2_EXIT_MANAGEMENT_RESEARCH_V1 development JSON

Frozen policy
-------------
SL5_BE5_TRAIL3_AFTER10_TIME15
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Sequence

RESEARCH_VERSION = "MIDPOINT_V3_2_TRAIN_OOS_REGIME_STABILITY_V1"
SOURCE_VERSION = "MIDPOINT_V3_2_EXIT_MANAGEMENT_RESEARCH_V1"
FROZEN_POLICY_ID = "SL5_BE5_TRAIL3_AFTER10_TIME15"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
OOS_BLOCKS = {"OOS_A", "OOS_B", "OOS_C", "OOS_D"}

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

def normalize_block(v: Any) -> str:
    return str(v).strip().upper().replace("-", "_")

def parse_ts(v: Any) -> datetime:
    text = str(v or "").strip()
    if not text:
        raise ValueError("entry_timestamp missing")
    return datetime.fromisoformat(text.replace("Z", "+00:00"))

def validate_source(x: dict[str, Any]) -> None:
    if x.get("research_version") != SOURCE_VERSION:
        raise ValueError(
            f"expected {SOURCE_VERSION}, got {x.get('research_version')!r}"
        )
    if x.get("train_only_nominated_policy") != FROZEN_POLICY_ID:
        raise ValueError("unexpected frozen policy")
    guard = x.get("leakage_guard") or {}
    if guard.get("oos_e_f_g_h_used") is not False:
        raise ValueError("source does not prove E/F/G/H exclusion")
    if guard.get("oos_h_used") is not False:
        raise ValueError("source does not prove H exclusion")

def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    return gains / losses if losses else None

def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    vals = [finite(r.get("net_return_pct")) for r in rows]
    vals = [v for v in vals if v is not None]
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    return {
        "trade_count": len(vals),
        "winner_count": len(wins),
        "win_rate_pct": len(wins) / len(vals) * 100 if vals else None,
        "mean_net_pct": sum(vals) / len(vals) if vals else None,
        "median_net_pct": median(vals) if vals else None,
        "profit_factor": profit_factor(vals) if vals else None,
        "average_winner_pct": sum(wins) / len(wins) if wins else None,
        "average_loser_pct": sum(losses) / len(losses) if losses else None,
    }

def composition(rows: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    counts = Counter(str(r.get(field) or "UNAVAILABLE") for r in rows)
    total = sum(counts.values())
    return {
        key: {
            "count": n,
            "share_pct": n / total * 100 if total else None,
        }
        for key, n in sorted(counts.items())
    }

def by_field(rows: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(field) or "UNAVAILABLE")].append(r)
    return {k: summarize(v) for k, v in sorted(groups.items())}

def entry_hour_bucket(row: dict[str, Any]) -> str:
    ts = parse_ts(row.get("entry_timestamp"))
    hour = ts.hour
    minute = ts.minute
    mins = hour * 60 + minute
    if mins < 10 * 60 + 30:
        return "OPEN_TO_10_29"
    if mins < 12 * 60:
        return "10_30_TO_11_59"
    if mins < 13 * 60 + 30:
        return "12_00_TO_13_29"
    return "13_30_ONWARD"

def add_derived_fields(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        ts = parse_ts(r.get("entry_timestamp"))
        r["_entry_hour_bucket"] = entry_hour_bucket(r)
        r["_month"] = ts.strftime("%Y-%m")
        r["_weekday"] = ts.strftime("%A")

def compare_share(train_comp: dict[str, Any], oos_comp: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(set(train_comp) | set(oos_comp))
    out = {}
    for k in keys:
        t = train_comp.get(k, {"count": 0, "share_pct": 0.0})
        o = oos_comp.get(k, {"count": 0, "share_pct": 0.0})
        out[k] = {
            "train_count": t["count"],
            "train_share_pct": t["share_pct"],
            "oos_count": o["count"],
            "oos_share_pct": o["share_pct"],
            "share_difference_train_minus_oos_pct_points": (
                (t["share_pct"] or 0.0) - (o["share_pct"] or 0.0)
            ),
        }
    return out

def analyze(source: dict[str, Any]) -> dict[str, Any]:
    validate_source(source)
    rows = [
        dict(r) for r in source.get("rows", [])
        if r.get("policy_id") == FROZEN_POLICY_ID
        and r.get("status") == "EXITED"
        and normalize_block(r.get("block")) in ALLOWED_BLOCKS
    ]
    for r in rows:
        r["block"] = normalize_block(r.get("block"))
    add_derived_fields(rows)

    train = [r for r in rows if r["block"] == "TRAIN"]
    oos = [r for r in rows if r["block"] in OOS_BLOCKS]

    dimensions = {
        "direction": "direction",
        "oi_quality": "oi_quality",
        "t1_observation_state": "t1_observation_state",
        "outcome_family": "outcome_family",
        "entry_hour_bucket": "_entry_hour_bucket",
        "month": "_month",
        "weekday": "_weekday",
    }

    dimension_analysis = {}
    for name, field in dimensions.items():
        train_comp = composition(train, field)
        oos_comp = composition(oos, field)
        dimension_analysis[name] = {
            "composition_shift": compare_share(train_comp, oos_comp),
            "train_economics": by_field(train, field),
            "pooled_oos_economics": by_field(oos, field),
        }

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_version": SOURCE_VERSION,
        "frozen_policy_id": FROZEN_POLICY_ID,
        "purpose": "DIAGNOSTIC_ONLY_EXPLAIN_TRAIN_VS_OOS_DIVERGENCE",
        "train_summary": summarize(train),
        "pooled_oos_a_d_summary": summarize(oos),
        "block_summaries": {
            b: summarize([r for r in rows if r["block"] == b])
            for b in ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D")
        },
        "dimension_analysis": dimension_analysis,
        "interpretation_guard": {
            "composition_differences_are_not_filters": True,
            "segment_pnl_is_not_permission_to_select_segment": True,
            "diagnostic_findings_require_new_train_supported_hypothesis": True,
            "no_parameter_promotion_in_this_module": True,
        },
        "leakage_guard": {
            "entry_state_machine_modified": False,
            "exit_policy_modified": False,
            "new_filter_selected": False,
            "new_threshold_selected": False,
            "oos_a_b_c_d_used_for_diagnostics_only": True,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "research_only": True,
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

    print(json.dumps({
        "status": result["status"],
        "research_version": result["research_version"],
        "frozen_policy_id": result["frozen_policy_id"],
        "train_summary": result["train_summary"],
        "pooled_oos_a_d_summary": result["pooled_oos_a_d_summary"],
        "block_summaries": result["block_summaries"],
        "interpretation_guard": result["interpretation_guard"],
        "leakage_guard": result["leakage_guard"],
        "output": str(out),
    }, indent=2))

if __name__ == "__main__":
    main()
