"""Temporal stability and uncertainty diagnostics for frozen Midpoint V3.2."""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Sequence

RESEARCH_VERSION = "MIDPOINT_V3_2_TEMPORAL_STABILITY_AND_UNCERTAINTY_V1"
SOURCE_VERSION = "MIDPOINT_V3_2_EXIT_MANAGEMENT_RESEARCH_V1"
FROZEN_POLICY_ID = "SL5_BE5_TRAIL3_AFTER10_TIME15"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
OOS_BLOCKS = {"OOS_A", "OOS_B", "OOS_C", "OOS_D"}

BOOTSTRAP_SAMPLES = 10000
PERMUTATION_SAMPLES = 10000
RNG_SEED = 320026
ROLLING_WINDOW_TRADES = 15

def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("JSON root must be object")
    return obj

def normalize_block(v: Any) -> str:
    return str(v).strip().upper().replace("-", "_")

def finite(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None

def parse_ts(v: Any) -> datetime:
    s = str(v or "").strip()
    if not s:
        raise ValueError("entry_timestamp missing")
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def validate_source(x: dict[str, Any]) -> None:
    if x.get("research_version") != SOURCE_VERSION:
        raise ValueError(f"expected {SOURCE_VERSION}, got {x.get('research_version')!r}")
    if x.get("train_only_nominated_policy") != FROZEN_POLICY_ID:
        raise ValueError("unexpected frozen policy")
    guard = x.get("leakage_guard") or {}
    if guard.get("oos_a_b_c_d_used_for_policy_nomination") is not False:
        raise ValueError("source does not prove A-D excluded from nomination")
    if guard.get("oos_e_f_g_h_used") is not False:
        raise ValueError("source does not prove E/F/G/H exclusion")
    if guard.get("oos_h_used") is not False:
        raise ValueError("source does not prove H exclusion")

def profit_factor(vals: Sequence[float]) -> float | None:
    gains = sum(v for v in vals if v > 0)
    losses = -sum(v for v in vals if v < 0)
    return gains / losses if losses > 0 else None

def summarize_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    vals = [finite(r.get("net_return_pct")) for r in rows]
    vals = [v for v in vals if v is not None]
    winners = [v for v in vals if v > 0]
    losers = [v for v in vals if v <= 0]
    return {
        "trade_count": len(vals),
        "winner_count": len(winners),
        "win_rate_pct": len(winners) / len(vals) * 100 if vals else None,
        "mean_net_pct": sum(vals) / len(vals) if vals else None,
        "median_net_pct": median(vals) if vals else None,
        "profit_factor": profit_factor(vals) if vals else None,
        "average_winner_pct": sum(winners) / len(winners) if winners else None,
        "average_loser_pct": sum(losers) / len(losers) if losers else None,
    }

def quantile(sorted_vals: Sequence[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    w = pos - lo
    return sorted_vals[lo] * (1 - w) + sorted_vals[hi] * w

def bootstrap_mean_ci(vals: Sequence[float], *, samples: int = BOOTSTRAP_SAMPLES, seed: int = RNG_SEED) -> dict[str, Any]:
    vals = list(vals)
    if not vals:
        return {"sample_count": 0, "bootstrap_samples": samples, "mean": None,
                "ci95_low": None, "ci95_high": None,
                "probability_mean_gt_zero_pct": None}
    rng = random.Random(seed)
    n = len(vals)
    means = []
    for _ in range(samples):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return {
        "sample_count": n,
        "bootstrap_samples": samples,
        "mean": sum(vals) / n,
        "ci95_low": quantile(means, 0.025),
        "ci95_high": quantile(means, 0.975),
        "probability_mean_gt_zero_pct": sum(m > 0 for m in means) / samples * 100.0,
        "caveat": "NAIVE_TRADE_LEVEL_BOOTSTRAP_TEMPORAL_DEPENDENCE_NOT_MODELED",
    }

def permutation_mean_gap(train_vals: Sequence[float], oos_vals: Sequence[float], *, samples: int = PERMUTATION_SAMPLES, seed: int = RNG_SEED) -> dict[str, Any]:
    a = list(train_vals)
    b = list(oos_vals)
    observed = sum(b) / len(b) - sum(a) / len(a)
    combined = a + b
    n_a = len(a)
    rng = random.Random(seed + 1)
    extreme = 0
    for _ in range(samples):
        shuffled = combined[:]
        rng.shuffle(shuffled)
        aa = shuffled[:n_a]
        bb = shuffled[n_a:]
        gap = sum(bb) / len(bb) - sum(aa) / len(aa)
        if abs(gap) >= abs(observed):
            extreme += 1
    return {
        "train_count": len(a),
        "oos_count": len(b),
        "observed_oos_minus_train_mean_pct_points": observed,
        "permutation_samples": samples,
        "two_sided_permutation_p": (extreme + 1) / (samples + 1),
        "caveat": "DESCRIPTIVE_PERMUTATION_TEMPORAL_DEPENDENCE_NOT_MODELED",
    }

def chronological(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: parse_ts(r["entry_timestamp"]))

def rolling_windows(rows: Sequence[dict[str, Any]], window: int = ROLLING_WINDOW_TRADES) -> list[dict[str, Any]]:
    ordered = chronological(rows)
    if len(ordered) < window:
        return []
    out = []
    for i in range(len(ordered) - window + 1):
        w = ordered[i:i+window]
        out.append({
            "window_index": i + 1,
            "start_entry_timestamp": w[0]["entry_timestamp"],
            "end_entry_timestamp": w[-1]["entry_timestamp"],
            "start_session_date": w[0].get("session_date"),
            "end_session_date": w[-1].get("session_date"),
            **summarize_rows(w),
        })
    return out

def rolling_summary(windows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    means = [w["mean_net_pct"] for w in windows if w.get("mean_net_pct") is not None]
    pfs = [w["profit_factor"] for w in windows if w.get("profit_factor") is not None]
    return {
        "window_size_trades": ROLLING_WINDOW_TRADES,
        "window_count": len(windows),
        "positive_mean_window_count": sum(x > 0 for x in means),
        "positive_mean_window_pct": sum(x > 0 for x in means) / len(means) * 100 if means else None,
        "min_window_mean_net_pct": min(means) if means else None,
        "median_window_mean_net_pct": median(means) if means else None,
        "max_window_mean_net_pct": max(means) if means else None,
        "min_window_profit_factor": min(pfs) if pfs else None,
        "median_window_profit_factor": median(pfs) if pfs else None,
        "max_window_profit_factor": max(pfs) if pfs else None,
    }

def group_by_month(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[parse_ts(r["entry_timestamp"]).strftime("%Y-%m")].append(r)
    return dict(sorted(groups.items()))

def leave_one_month_out(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    months = group_by_month(rows)
    return {
        month: summarize_rows([r for m, group_rows in months.items() if m != month for r in group_rows])
        for month in months
    }

def group_summary(rows: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(field) or "UNAVAILABLE")].append(r)
    return {k: summarize_rows(v) for k, v in sorted(groups.items())}

def share_map(rows: Sequence[dict[str, Any]], field: str) -> dict[str, float]:
    c = Counter(str(r.get(field) or "UNAVAILABLE") for r in rows)
    total = sum(c.values())
    return {k: v / total for k, v in c.items()} if total else {}

def mean_map(rows: Sequence[dict[str, Any]], field: str) -> dict[str, float | None]:
    return {k: v["mean_net_pct"] for k, v in group_summary(rows, field).items()}

def composition_decomposition(train: Sequence[dict[str, Any]], oos: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    p_t, p_o = share_map(train, field), share_map(oos, field)
    mu_t, mu_o = mean_map(train, field), mean_map(oos, field)
    common = sorted(set(p_t) & set(p_o))
    unsupported = sorted((set(p_t) | set(p_o)) - set(common))
    comp = within = 0.0
    details = {}
    for k in common:
        mt, mo = mu_t[k], mu_o[k]
        if mt is None or mo is None:
            continue
        c = (p_o[k] - p_t[k]) * mt
        w = p_o[k] * (mo - mt)
        comp += c
        within += w
        details[k] = {
            "train_share": p_t[k],
            "oos_share": p_o[k],
            "train_mean_net_pct": mt,
            "oos_mean_net_pct": mo,
            "composition_component_pct_points": c,
            "within_segment_component_pct_points": w,
        }
    observed_gap = summarize_rows(oos)["mean_net_pct"] - summarize_rows(train)["mean_net_pct"]
    return {
        "field": field,
        "observed_oos_minus_train_mean_pct_points": observed_gap,
        "composition_component_pct_points_common_categories": comp,
        "within_segment_component_pct_points_common_categories": within,
        "explained_sum_common_categories": comp + within,
        "unsupported_categories": unsupported,
        "details": details,
        "caveat": "DESCRIPTIVE_DECOMPOSITION_NOT_CAUSAL" + ("; OUTCOME_FAMILY_IS_FUTURE_LABEL" if field == "outcome_family" else ""),
    }

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
        parse_ts(r.get("entry_timestamp"))

    train = [r for r in rows if r["block"] == "TRAIN"]
    oos = [r for r in rows if r["block"] in OOS_BLOCKS]
    train_vals = [float(r["net_return_pct"]) for r in train]
    oos_vals = [float(r["net_return_pct"]) for r in oos]
    rolling_all = rolling_windows(rows)
    rolling_oos = rolling_windows(oos)
    months = group_by_month(rows)

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_version": SOURCE_VERSION,
        "frozen_policy_id": FROZEN_POLICY_ID,
        "promotion_status": "NOT_PROMOTED",
        "headline": {
            "train": summarize_rows(train),
            "pooled_oos_a_d": summarize_rows(oos),
            "observed_oos_minus_train_mean_pct_points": summarize_rows(oos)["mean_net_pct"] - summarize_rows(train)["mean_net_pct"],
        },
        "bootstrap_uncertainty": {
            "train_mean": bootstrap_mean_ci(train_vals, seed=RNG_SEED),
            "pooled_oos_a_d_mean": bootstrap_mean_ci(oos_vals, seed=RNG_SEED + 10),
        },
        "train_vs_oos_permutation_diagnostic": permutation_mean_gap(train_vals, oos_vals),
        "leave_one_oos_block_out": {
            block: summarize_rows([r for r in oos if r["block"] != block])
            for block in ("OOS_A", "OOS_B", "OOS_C", "OOS_D")
        },
        "calendar_month_summaries": {
            month: summarize_rows(month_rows)
            for month, month_rows in months.items()
        },
        "leave_one_month_out_all_development": leave_one_month_out(rows),
        "rolling_all_development": {
            "summary": rolling_summary(rolling_all),
            "windows": rolling_all,
        },
        "rolling_oos_a_d": {
            "summary": rolling_summary(rolling_oos),
            "windows": rolling_oos,
        },
        "segment_stability": {
            "direction": {"train": group_summary(train, "direction"), "oos": group_summary(oos, "direction")},
            "oi_quality": {"train": group_summary(train, "oi_quality"), "oos": group_summary(oos, "oi_quality")},
            "t1_observation_state": {"train": group_summary(train, "t1_observation_state"), "oos": group_summary(oos, "t1_observation_state")},
            "outcome_family": {"train": group_summary(train, "outcome_family"), "oos": group_summary(oos, "outcome_family")},
        },
        "composition_vs_within_segment": {
            "oi_quality": composition_decomposition(train, oos, "oi_quality"),
            "outcome_family": composition_decomposition(train, oos, "outcome_family"),
        },
        "interpretation_guard": {
            "bootstrap_is_descriptive_not_iid_proof": True,
            "permutation_is_descriptive_not_iid_proof": True,
            "outcome_family_is_future_label_not_live_filter": True,
            "segment_results_are_not_permission_to_select_filters": True,
            "no_policy_promotion_in_this_module": True,
        },
        "leakage_guard": {
            "entry_state_machine_modified": False,
            "exit_policy_modified": False,
            "alternative_exit_search_performed": False,
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
    compact = {
        "status": result["status"],
        "research_version": result["research_version"],
        "frozen_policy_id": result["frozen_policy_id"],
        "promotion_status": result["promotion_status"],
        "headline": result["headline"],
        "bootstrap_uncertainty": result["bootstrap_uncertainty"],
        "train_vs_oos_permutation_diagnostic": result["train_vs_oos_permutation_diagnostic"],
        "leave_one_oos_block_out": result["leave_one_oos_block_out"],
        "calendar_month_summaries": result["calendar_month_summaries"],
        "rolling_all_development_summary": result["rolling_all_development"]["summary"],
        "rolling_oos_a_d_summary": result["rolling_oos_a_d"]["summary"],
        "composition_vs_within_segment": result["composition_vs_within_segment"],
        "interpretation_guard": result["interpretation_guard"],
        "leakage_guard": result["leakage_guard"],
        "output": str(out),
    }
    print(json.dumps(compact, indent=2))

if __name__ == "__main__":
    main()
