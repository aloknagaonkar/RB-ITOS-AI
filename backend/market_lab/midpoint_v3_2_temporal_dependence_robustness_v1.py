from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

RESEARCH_VERSION = "MIDPOINT_V3_2_TEMPORAL_DEPENDENCE_ROBUSTNESS_V1"
FROZEN_POLICY_ID = "SL5_BE5_TRAIL3_AFTER10_TIME15"
ALLOWED_BLOCKS = ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D")
FORBIDDEN_BLOCKS = ("OOS_E", "OOS_F", "OOS_G", "OOS_H")


def _finite_number(value: Any) -> float:
    if value is None:
        raise ValueError("missing numeric value")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite numeric value: {value!r}")
    return number


def _parse_timestamp(value: Any) -> datetime:
    if not value:
        raise ValueError("entry_timestamp is required")
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _net_return(row: dict[str, Any]) -> float:
    for key in ("net_return_pct", "realized_net_pct", "net_pct"):
        if key in row and row[key] is not None:
            return _finite_number(row[key])
    raise ValueError("frozen-policy row is missing net_return_pct")


def _session_date(row: dict[str, Any]) -> str:
    value = row.get("session_date")
    if value:
        return str(value)
    return _parse_timestamp(row.get("entry_timestamp")).date().isoformat()


def _month(row: dict[str, Any]) -> str:
    return _session_date(row)[:7]


def _profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses == 0:
        return None if gains == 0 else math.inf
    return gains / losses


def _summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    values = [_net_return(row) for row in rows]
    if not values:
        return {
            "trade_count": 0,
            "winner_count": 0,
            "win_rate_pct": None,
            "mean_net_pct": None,
            "median_net_pct": None,
            "profit_factor": None,
        }
    winners = [v for v in values if v > 0]
    return {
        "trade_count": len(values),
        "winner_count": len(winners),
        "win_rate_pct": 100.0 * len(winners) / len(values),
        "mean_net_pct": statistics.fmean(values),
        "median_net_pct": statistics.median(values),
        "profit_factor": _profit_factor(values),
        "average_winner_pct": statistics.fmean(winners) if winners else None,
        "average_loser_pct": statistics.fmean([v for v in values if v <= 0])
        if any(v <= 0 for v in values)
        else None,
    }


def prepare_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    source_rows = payload.get("rows")
    if not isinstance(source_rows, list):
        raise ValueError("source JSON must contain a rows array")

    rows: list[dict[str, Any]] = []
    seen_forbidden: set[str] = set()

    for source_row in source_rows:
        if source_row.get("policy_id") != FROZEN_POLICY_ID:
            continue
        block = str(source_row.get("block", "")).strip()
        if block in FORBIDDEN_BLOCKS:
            seen_forbidden.add(block)
            continue
        if block not in ALLOWED_BLOCKS:
            continue

        row = dict(source_row)
        row["block"] = block
        row["entry_timestamp"] = str(source_row.get("entry_timestamp") or "")
        _parse_timestamp(row["entry_timestamp"])
        row["session_date"] = _session_date(row)
        row["calendar_month"] = _month(row)
        row["net_return_pct"] = _net_return(row)
        rows.append(row)

    if seen_forbidden:
        raise ValueError(
            "forbidden OOS block(s) present in frozen-policy rows: "
            + ", ".join(sorted(seen_forbidden))
        )
    if not rows:
        raise ValueError("no frozen-policy rows found for TRAIN/OOS_A-D")

    rows.sort(key=lambda row: _parse_timestamp(row["entry_timestamp"]))
    return rows


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("empty sample")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


def _bootstrap_stats(sample_means: list[float], observed: float) -> dict[str, Any]:
    ordered = sorted(sample_means)
    return {
        "observed_mean_net_pct": observed,
        "bootstrap_samples": len(sample_means),
        "ci95_low": _percentile(ordered, 0.025),
        "ci95_high": _percentile(ordered, 0.975),
        "probability_mean_gt_zero_pct": 100.0
        * sum(value > 0 for value in sample_means)
        / len(sample_means),
        "probability_mean_le_zero_pct": 100.0
        * sum(value <= 0 for value in sample_means)
        / len(sample_means),
    }


def month_cluster_bootstrap(
    rows: Sequence[dict[str, Any]],
    *,
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    """Resample whole calendar-month clusters with replacement.

    Every sampled cluster contributes all of its trades. This preserves
    within-month dependence rather than pretending every trade is IID.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["calendar_month"]].append(row)
    months = sorted(grouped)
    if len(months) < 2:
        return {
            "status": "INSUFFICIENT_CLUSTERS",
            "cluster_count": len(months),
            "clusters": months,
        }

    rng = random.Random(seed)
    sample_means: list[float] = []
    for _ in range(iterations):
        sample: list[dict[str, Any]] = []
        for _ in range(len(months)):
            sampled_month = rng.choice(months)
            sample.extend(grouped[sampled_month])
        sample_means.append(statistics.fmean(_net_return(row) for row in sample))

    result = _bootstrap_stats(
        sample_means,
        statistics.fmean(_net_return(row) for row in rows),
    )
    result.update(
        {
            "status": "AVAILABLE",
            "cluster_type": "CALENDAR_MONTH",
            "cluster_count": len(months),
            "clusters": months,
            "caveat": "CLUSTER_BOOTSTRAP_DESCRIPTIVE_SMALL_CLUSTER_COUNT",
        }
    )
    return result


def block_cluster_bootstrap(
    rows: Sequence[dict[str, Any]],
    *,
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    """Resample whole OOS block clusters with replacement."""
    oos_rows = [row for row in rows if row["block"] != "TRAIN"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in oos_rows:
        grouped[row["block"]].append(row)
    blocks = sorted(grouped)
    if len(blocks) < 2:
        return {
            "status": "INSUFFICIENT_CLUSTERS",
            "cluster_count": len(blocks),
            "clusters": blocks,
        }

    rng = random.Random(seed)
    sample_means: list[float] = []
    for _ in range(iterations):
        sample: list[dict[str, Any]] = []
        for _ in range(len(blocks)):
            sampled_block = rng.choice(blocks)
            sample.extend(grouped[sampled_block])
        sample_means.append(statistics.fmean(_net_return(row) for row in sample))

    result = _bootstrap_stats(
        sample_means,
        statistics.fmean(_net_return(row) for row in oos_rows),
    )
    result.update(
        {
            "status": "AVAILABLE",
            "cluster_type": "OOS_BLOCK",
            "cluster_count": len(blocks),
            "clusters": blocks,
            "caveat": "CLUSTER_BOOTSTRAP_DESCRIPTIVE_ONLY_FOUR_OOS_BLOCKS",
        }
    )
    return result


def moving_block_bootstrap(
    rows: Sequence[dict[str, Any]],
    *,
    block_length: int,
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    """Circular moving-block bootstrap preserving local chronology."""
    if block_length <= 0:
        raise ValueError("block_length must be > 0")
    ordered = sorted(rows, key=lambda row: _parse_timestamp(row["entry_timestamp"]))
    n = len(ordered)
    if n < block_length:
        return {
            "status": "INSUFFICIENT_TRADES",
            "trade_count": n,
            "block_length": block_length,
        }

    values = [_net_return(row) for row in ordered]
    rng = random.Random(seed)
    sample_means: list[float] = []

    for _ in range(iterations):
        sample: list[float] = []
        while len(sample) < n:
            start = rng.randrange(n)
            for offset in range(block_length):
                sample.append(values[(start + offset) % n])
                if len(sample) >= n:
                    break
        sample_means.append(statistics.fmean(sample))

    result = _bootstrap_stats(sample_means, statistics.fmean(values))
    result.update(
        {
            "status": "AVAILABLE",
            "trade_count": n,
            "block_length": block_length,
            "bootstrap_method": "CIRCULAR_MOVING_BLOCK",
            "caveat": "BLOCK_LENGTH_IS_SENSITIVITY_PARAMETER_NOT_TUNED",
        }
    )
    return result


def _monthly_summaries(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["calendar_month"]].append(row)
    return {month: _summary(grouped[month]) for month in sorted(grouped)}


def worst_regime_stress(
    rows: Sequence[dict[str, Any]],
    *,
    adverse_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Reweight the empirically worst month to occur more often.

    This is a scenario stress test, not a forecast and not a trading filter.
    """
    if adverse_multiplier < 1.0:
        raise ValueError("adverse_multiplier must be >= 1")
    monthly = _monthly_summaries(rows)
    usable = {
        month: info
        for month, info in monthly.items()
        if info["trade_count"] and info["mean_net_pct"] is not None
    }
    if not usable:
        return {"status": "UNAVAILABLE"}

    worst_month = min(usable, key=lambda month: usable[month]["mean_net_pct"])
    total_count = sum(info["trade_count"] for info in usable.values())
    weighted_sum = 0.0
    weighted_count = 0.0

    for month, info in usable.items():
        weight = adverse_multiplier if month == worst_month else 1.0
        weighted_count += info["trade_count"] * weight
        weighted_sum += info["mean_net_pct"] * info["trade_count"] * weight

    return {
        "status": "AVAILABLE",
        "worst_calendar_month": worst_month,
        "worst_month_summary": usable[worst_month],
        "adverse_multiplier": adverse_multiplier,
        "baseline": _summary(rows),
        "stressed_mean_net_pct": weighted_sum / weighted_count,
        "scenario_interpretation": (
            "WORST_OBSERVED_MONTH_FREQUENCY_MULTIPLIED; "
            "NOT_A_FORECAST_AND_NOT_A_MONTH_FILTER"
        ),
        "baseline_trade_count": total_count,
    }


def chronological_stability(
    rows: Sequence[dict[str, Any]],
    *,
    window_sizes: Sequence[int] = (10, 15, 20),
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: _parse_timestamp(row["entry_timestamp"]))
    output: dict[str, Any] = {}

    for window in window_sizes:
        if len(ordered) < window:
            output[str(window)] = {
                "status": "INSUFFICIENT_TRADES",
                "trade_count": len(ordered),
            }
            continue

        summaries = []
        for start in range(0, len(ordered) - window + 1):
            sample = ordered[start : start + window]
            item = _summary(sample)
            item["start_timestamp"] = sample[0]["entry_timestamp"]
            item["end_timestamp"] = sample[-1]["entry_timestamp"]
            summaries.append(item)

        means = [item["mean_net_pct"] for item in summaries]
        pfs = [item["profit_factor"] for item in summaries if item["profit_factor"] is not None and math.isfinite(item["profit_factor"])]
        output[str(window)] = {
            "status": "AVAILABLE",
            "window_size_trades": window,
            "window_count": len(summaries),
            "positive_mean_window_count": sum(value > 0 for value in means),
            "positive_mean_window_pct": 100.0 * sum(value > 0 for value in means) / len(means),
            "min_window_mean_net_pct": min(means),
            "median_window_mean_net_pct": statistics.median(means),
            "max_window_mean_net_pct": max(means),
            "min_finite_window_profit_factor": min(pfs) if pfs else None,
            "median_finite_window_profit_factor": statistics.median(pfs) if pfs else None,
            "max_finite_window_profit_factor": max(pfs) if pfs else None,
        }

    return output


def classify_evidence(
    *,
    oos_block_cluster: dict[str, Any],
    oos_moving_block: dict[str, Any],
    stress: dict[str, Any],
    chronological: dict[str, Any],
) -> dict[str, Any]:
    """Descriptive research label; not an automatic promotion rule."""
    signals: list[str] = []
    weak_signals: list[str] = []

    if oos_block_cluster.get("status") == "AVAILABLE":
        if oos_block_cluster.get("probability_mean_gt_zero_pct", 0.0) >= 90:
            signals.append("BLOCK_CLUSTER_POSITIVE_PROBABILITY_GE_90")
        else:
            weak_signals.append("BLOCK_CLUSTER_POSITIVE_PROBABILITY_LT_90")

    if oos_moving_block.get("status") == "AVAILABLE":
        if oos_moving_block.get("probability_mean_gt_zero_pct", 0.0) >= 90:
            signals.append("MOVING_BLOCK_POSITIVE_PROBABILITY_GE_90")
        else:
            weak_signals.append("MOVING_BLOCK_POSITIVE_PROBABILITY_LT_90")

    stressed_mean = stress.get("stressed_mean_net_pct")
    if stressed_mean is not None:
        if stressed_mean > 0:
            signals.append("WORST_REGIME_STRESS_REMAINS_POSITIVE")
        else:
            weak_signals.append("WORST_REGIME_STRESS_NON_POSITIVE")

    fifteen = chronological.get("15", {})
    if fifteen.get("status") == "AVAILABLE":
        if fifteen.get("positive_mean_window_pct", 0.0) >= 80:
            signals.append("ROLLING_15_POSITIVE_WINDOWS_GE_80")
        else:
            weak_signals.append("ROLLING_15_POSITIVE_WINDOWS_LT_80")

    if weak_signals:
        label = "PROMISING_BUT_UNCERTAIN"
    elif len(signals) >= 4:
        label = "ROBUSTNESS_SUPPORTIVE"
    else:
        label = "INSUFFICIENT_EVIDENCE"

    return {
        "label": label,
        "supportive_signals": signals,
        "uncertainty_signals": weak_signals,
        "important": (
            "DESCRIPTIVE_RESEARCH_LABEL_ONLY; DOES_NOT_PROMOTE POLICY, "
            "DOES_NOT AUTHORIZE OOS_H, PAPER, OR LIVE TRADING"
        ),
    }


def analyze(
    payload: dict[str, Any],
    *,
    iterations: int = 20_000,
    seed: int = 42,
    adverse_multiplier: float = 2.0,
) -> dict[str, Any]:
    rows = prepare_rows(payload)
    train = [row for row in rows if row["block"] == "TRAIN"]
    oos = [row for row in rows if row["block"] != "TRAIN"]

    if not train:
        raise ValueError("TRAIN rows are required")
    expected_oos_blocks = {"OOS_A", "OOS_B", "OOS_C", "OOS_D"}
    actual_oos_blocks = {row["block"] for row in oos}
    if actual_oos_blocks != expected_oos_blocks:
        raise ValueError(
            f"expected exactly OOS_A-D; found {sorted(actual_oos_blocks)}"
        )

    oos_mbb: dict[str, Any] = {}
    for block_length in (3, 5, 10):
        oos_mbb[str(block_length)] = moving_block_bootstrap(
            oos,
            block_length=block_length,
            iterations=iterations,
            seed=seed + block_length,
        )

    chronological_oos = chronological_stability(oos)
    stress_oos = worst_regime_stress(oos, adverse_multiplier=adverse_multiplier)
    block_cluster = block_cluster_bootstrap(
        rows,
        iterations=iterations,
        seed=seed + 101,
    )

    # Use 5-trade MBB as the central descriptive sensitivity point only.
    assessment = classify_evidence(
        oos_block_cluster=block_cluster,
        oos_moving_block=oos_mbb["5"],
        stress=stress_oos,
        chronological=chronological_oos,
    )

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "frozen_policy_id": FROZEN_POLICY_ID,
        "promotion_status": "NOT_PROMOTED",
        "headline": {
            "train": _summary(train),
            "pooled_oos_a_d": _summary(oos),
            "all_development": _summary(rows),
        },
        "month_cluster_bootstrap_all_development": month_cluster_bootstrap(
            rows,
            iterations=iterations,
            seed=seed,
        ),
        "month_cluster_bootstrap_oos_a_d": month_cluster_bootstrap(
            oos,
            iterations=iterations,
            seed=seed + 1,
        ),
        "oos_block_cluster_bootstrap": block_cluster,
        "moving_block_bootstrap_oos_a_d": oos_mbb,
        "worst_regime_stress_oos_a_d": {
            "x2": stress_oos,
            "x3": worst_regime_stress(oos, adverse_multiplier=3.0),
        },
        "chronological_stability_oos_a_d": chronological_oos,
        "calendar_month_summaries_oos_a_d": _monthly_summaries(oos),
        "research_assessment": assessment,
        "interpretation_guard": {
            "temporal_bootstraps_are_descriptive_not_proof": True,
            "block_lengths_are_sensitivity_checks_not_tuned_parameters": True,
            "worst_month_is_stress_scenario_not_filter": True,
            "calendar_month_results_are_not_permission_to_filter_months": True,
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
    parser = argparse.ArgumentParser(
        description="Temporal dependence robustness diagnostics for frozen Midpoint V3.2."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--adverse-multiplier", type=float, default=2.0)
    args = parser.parse_args()

    if args.bootstrap_iterations <= 0:
        raise SystemExit("--bootstrap-iterations must be > 0")

    source = Path(args.source)
    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    result = analyze(
        payload,
        iterations=args.bootstrap_iterations,
        seed=args.seed,
        adverse_multiplier=args.adverse_multiplier,
    )
    result["output"] = args.output

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=False, allow_nan=False))


if __name__ == "__main__":
    main()
