"""Corrected midpoint failure diagnostics V2.2.

Reads MIDPOINT_BREAK_STRENGTH_AND_FAILURE_V2 output and fixes three diagnostic
issues without changing the frozen research entry logic:

1) Restores directional momentum semantics for bearish rows. The upstream
   midpoint framework already defines directional features so positive means
   favorable for both RED/bearish and GREEN/bullish. V2 accidentally inverted
   bearish momentum a second time.
2) Computes exact T+1 -> T+3 CE/PE OI-state transitions before slicing by
   checkpoint.
3) Derives checkpoint-path giveback / progress-decay metrics from the available
   T0, T+1 and T+3 directional progress observations. No unavailable raw feature
   is silently fabricated.

Descriptive research only: TRAIN + OOS_A/B/C/D. E/F/G/H forbidden.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_FAILURE_DIAGNOSTICS_V2_2"
SOURCE_VERSION = "MIDPOINT_BREAK_STRENGTH_AND_FAILURE_V2"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
CHECKPOINTS = (0, 1, 3)
ANALYSIS_CHECKPOINTS = (1, 3)

BASE_FEATURES = (
    "momentum_5m_directional",
    "acceptance_pct",
    "consecutive_closes",
    "extreme_count",
    "progress_points",
    "velocity",
)

DERIVED_FEATURES = (
    "giveback_from_best_checkpoint_points",
    "progress_change_from_previous_checkpoint",
    "acceptance_change_from_previous_checkpoint",
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
        raise ValueError("source does not prove OOS_E/F/G/H were excluded")
    if guard.get("oos_h_used") is not False:
        raise ValueError("source does not prove OOS_H was excluded")
    blocks = {str(r.get("block")) for r in x.get("rows", [])}
    bad = blocks - ALLOWED_BLOCKS
    if bad:
        raise ValueError(f"forbidden blocks present: {sorted(bad)}")

def finite(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None

def event_key(r: dict[str, Any]) -> tuple[Any, ...]:
    return (
        r.get("block"),
        r.get("session_date"),
        r.get("setup_type"),
        r.get("primary_outcome"),
    )

def correct_directional_momentum(row: dict[str, Any]) -> float | None:
    """Undo V2's accidental second inversion on bearish momentum.

    The source midpoint framework guarantees directional feature semantics:
    positive = favorable in the setup direction for both bearish and bullish.
    V2 negated bearish momentum after reading that already-directional field.
    """
    raw = finite((row.get("price_features") or {}).get("momentum_5m"))
    if raw is None:
        return None
    return -raw if row.get("direction") == "BEARISH" else raw

def oi_pair(row: dict[str, Any]) -> tuple[str, str]:
    oi = row.get("oi") or {}
    return (str(oi.get("ce_state") or "NA"), str(oi.get("pe_state") or "NA"))

def exact_oi_transition(a: dict[str, Any], b: dict[str, Any]) -> str:
    ace, ape = oi_pair(a)
    bce, bpe = oi_pair(b)
    return f"CE:{ace}->{bce};PE:{ape}->{bpe}"

def prepare_rows(source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [copy.deepcopy(r) for r in source_rows if r.get("block") in ALLOWED_BLOCKS]

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("checkpoint_minutes") in CHECKPOINTS:
            groups[event_key(r)].append(r)

    for group in groups.values():
        group.sort(key=lambda r: int(r["checkpoint_minutes"]))
        by_cp = {int(r["checkpoint_minutes"]): r for r in group}

        best_progress: float | None = None
        prev: dict[str, Any] | None = None

        for r in group:
            pf = r.setdefault("price_features", {})
            corrected_mom = correct_directional_momentum(r)
            pf["momentum_5m_directional"] = corrected_mom

            progress = finite(pf.get("progress_points"))
            acceptance = finite(pf.get("acceptance_pct"))

            if progress is not None:
                best_progress = progress if best_progress is None else max(best_progress, progress)
                giveback = max(0.0, best_progress - progress)
            else:
                giveback = None

            pf["giveback_from_best_checkpoint_points"] = giveback

            if prev is None:
                pf["progress_change_from_previous_checkpoint"] = None
                pf["acceptance_change_from_previous_checkpoint"] = None
            else:
                prev_pf = prev.get("price_features") or {}
                prev_progress = finite(prev_pf.get("progress_points"))
                prev_acceptance = finite(prev_pf.get("acceptance_pct"))
                pf["progress_change_from_previous_checkpoint"] = (
                    progress - prev_progress
                    if progress is not None and prev_progress is not None
                    else None
                )
                pf["acceptance_change_from_previous_checkpoint"] = (
                    acceptance - prev_acceptance
                    if acceptance is not None and prev_acceptance is not None
                    else None
                )
            prev = r

        if 1 in by_cp and 3 in by_cp:
            transition = exact_oi_transition(by_cp[1], by_cp[3])
            by_cp[1]["exact_oi_transition_t1_to_t3"] = transition
            by_cp[3]["exact_oi_transition_t1_to_t3"] = transition
        else:
            for r in group:
                r["exact_oi_transition_t1_to_t3"] = None

    return rows

def stats(values: list[float]) -> dict[str, Any]:
    vals = [x for x in values if x is not None and math.isfinite(x)]
    if not vals:
        return {"count": 0, "median": None, "mean": None, "min": None, "max": None}
    return {
        "count": len(vals),
        "median": median(vals),
        "mean": sum(vals) / len(vals),
        "min": min(vals),
        "max": max(vals),
    }

def values(rows: list[dict[str, Any]], feature: str) -> list[float]:
    out = []
    for r in rows:
        v = finite((r.get("price_features") or {}).get(feature))
        if v is not None:
            out.append(v)
    return out

def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cont = [r for r in rows if r.get("outcome_label") == "CONTINUATION"]
    rev = [r for r in rows if r.get("outcome_label") == "REVERSAL"]
    features = {}
    for feature in BASE_FEATURES + DERIVED_FEATURES:
        c = stats(values(cont, feature))
        v = stats(values(rev, feature))
        gap = (
            c["median"] - v["median"]
            if c["median"] is not None and v["median"] is not None
            else None
        )
        features[feature] = {
            "continuation": c,
            "reversal": v,
            "median_gap_cont_minus_rev": gap,
        }

    return {
        "count": len(rows),
        "continuation_count": len(cont),
        "reversal_count": len(rev),
        "features": features,
        "continuation_oi_support": dict(Counter(
            (r.get("oi") or {}).get("support_level", "UNAVAILABLE") for r in cont
        )),
        "reversal_oi_support": dict(Counter(
            (r.get("oi") or {}).get("support_level", "UNAVAILABLE") for r in rev
        )),
        "continuation_exact_oi_t1_to_t3": dict(Counter(
            r.get("exact_oi_transition_t1_to_t3")
            for r in cont
            if r.get("checkpoint_minutes") == 3
            and r.get("exact_oi_transition_t1_to_t3")
        )),
        "reversal_exact_oi_t1_to_t3": dict(Counter(
            r.get("exact_oi_transition_t1_to_t3")
            for r in rev
            if r.get("checkpoint_minutes") == 3
            and r.get("exact_oi_transition_t1_to_t3")
        )),
    }

def analyze(source: dict[str, Any]) -> dict[str, Any]:
    validate_source(source)
    rows = prepare_rows(source.get("rows", []))

    pooled: dict[str, Any] = {}
    by_block: dict[str, Any] = {}

    for direction in ("BEARISH", "BULLISH"):
        pooled[direction] = {}
        by_block[direction] = {}

        for cp in ANALYSIS_CHECKPOINTS:
            rs = [
                r for r in rows
                if r.get("direction") == direction
                and r.get("checkpoint_minutes") == cp
                and r.get("outcome_label") in {"CONTINUATION", "REVERSAL"}
            ]
            pooled[direction][f"T+{cp}"] = summarize(rs)

        for block in ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"):
            by_block[direction][block] = {}
            for cp in ANALYSIS_CHECKPOINTS:
                rs = [
                    r for r in rows
                    if r.get("direction") == direction
                    and r.get("block") == block
                    and r.get("checkpoint_minutes") == cp
                    and r.get("outcome_label") in {"CONTINUATION", "REVERSAL"}
                ]
                by_block[direction][block][f"T+{cp}"] = summarize(rs)

    rankings = {}
    for direction in ("BEARISH", "BULLISH"):
        rankings[direction] = {}
        for cp in ("T+1", "T+3"):
            ranked = []
            for feature, payload in pooled[direction][cp]["features"].items():
                gap = payload["median_gap_cont_minus_rev"]
                if gap is not None:
                    ranked.append({
                        "feature": feature,
                        "median_gap_cont_minus_rev": gap,
                        "abs_gap": abs(gap),
                    })
            ranked.sort(key=lambda x: x["abs_gap"], reverse=True)
            rankings[direction][cp] = ranked

    # Explicit coverage proof for the corrected items.
    coverage = {
        "bearish_t3_exact_transition_count": sum(
            pooled["BEARISH"]["T+3"]["continuation_exact_oi_t1_to_t3"].values()
        ) + sum(
            pooled["BEARISH"]["T+3"]["reversal_exact_oi_t1_to_t3"].values()
        ),
        "bullish_t3_exact_transition_count": sum(
            pooled["BULLISH"]["T+3"]["continuation_exact_oi_t1_to_t3"].values()
        ) + sum(
            pooled["BULLISH"]["T+3"]["reversal_exact_oi_t1_to_t3"].values()
        ),
        "bearish_t3_giveback_available": (
            pooled["BEARISH"]["T+3"]["features"]["giveback_from_best_checkpoint_points"]["continuation"]["count"]
            + pooled["BEARISH"]["T+3"]["features"]["giveback_from_best_checkpoint_points"]["reversal"]["count"]
        ),
        "bullish_t3_giveback_available": (
            pooled["BULLISH"]["T+3"]["features"]["giveback_from_best_checkpoint_points"]["continuation"]["count"]
            + pooled["BULLISH"]["T+3"]["features"]["giveback_from_best_checkpoint_points"]["reversal"]["count"]
        ),
    }

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_version": SOURCE_VERSION,
        "corrections": {
            "bearish_momentum_double_inversion_fixed": True,
            "exact_t1_to_t3_oi_transitions_fixed": True,
            "checkpoint_giveback_derived": True,
            "raw_rebound_feature_fabricated": False,
            "raw_midpoint_cross_feature_fabricated": False,
        },
        "methodology": [
            "Directional momentum uses positive=favorable semantics for both bearish and bullish.",
            "Exact OI transitions pair the same event's T+1 and T+3 rows before checkpoint slicing.",
            "Giveback is max prior checkpoint directional progress through current checkpoint minus current progress.",
            "Progress/acceptance changes use only available earlier checkpoint data.",
            "No unavailable raw rebound or midpoint-cross values are invented.",
        ],
        "feature_rankings_by_abs_median_gap": rankings,
        "coverage": coverage,
        "pooled": pooled,
        "by_block": by_block,
        "leakage_guard": {
            "descriptive_only": True,
            "new_thresholds_selected": False,
            "entry_rule_modified": False,
            "pnl_used": False,
            "uses_t0_t1_t3_or_earlier_only": True,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "research_emits_trade_order": False,
        },
        "rows": rows,
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
        "corrections": result["corrections"],
        "coverage": result["coverage"],
        "feature_rankings_by_abs_median_gap": result["feature_rankings_by_abs_median_gap"],
        "leakage_guard": result["leakage_guard"],
        "output": str(out),
    }, indent=2))

if __name__ == "__main__":
    main()
