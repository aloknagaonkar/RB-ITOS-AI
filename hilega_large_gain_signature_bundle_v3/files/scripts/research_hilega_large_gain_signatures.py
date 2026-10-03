#!/usr/bin/env python3
"""Research flat-WMA filtering and large-gain Hilega entry signatures.

Consumes the immutable 490-session trade-alignment output.  Rules are learned
only from IS.  OOS is evaluated with frozen IS thresholds.  This script never
changes a strategy, service, live audit, order, paper order, or quantity.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable


DEFAULT_INPUT = Path(
    "data/historical-evidence/hilega-alignment-points-490-v1/"
    "trade-alignment-points.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-large-gain-signatures-490-v1"
)
PRIMARY_FLAT_EPSILON = 0.10
SENSITIVITY_EPSILONS = (0.05, 0.10, 0.15, 0.20, 0.30)

RAW_FEATURES = (
    "entry_rsi9",
    "entry_ema3_rsi",
    "entry_wma21_rsi",
    "entry_ema_minus_wma",
    "entry_rsi9_slope_3",
    "entry_ema3_rsi_slope_3",
    "entry_wma21_rsi_slope_3",
    "entry_ema_minus_wma_slope_3",
)
DIRECTIONAL_FEATURES = (
    "rsi_directional_level",
    "ema_wma_directional_gap",
    "rsi_directional_slope",
    "ema_directional_slope",
    "wma_directional_slope",
    "gap_directional_slope",
)


def finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def percentile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def angle_degrees(slope: float | None) -> float | None:
    """Indicator-space angle; chart-rendering angles are scale-dependent."""
    return None if slope is None else math.degrees(math.atan(slope))


def enrich(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in RAW_FEATURES + (
        "captured_points", "mfe_points", "mae_points", "giveback_points"
    ):
        result[key] = finite(row.get(key))
    sign = 1.0 if row["direction"] == "BULLISH" else -1.0

    def directional(value: float | None) -> float | None:
        return None if value is None else sign * value

    rsi = result["entry_rsi9"]
    result.update({
        "rsi_directional_level": (
            None if rsi is None else sign * (rsi - 50.0)
        ),
        "ema_wma_directional_gap": directional(result["entry_ema_minus_wma"]),
        "rsi_directional_slope": directional(result["entry_rsi9_slope_3"]),
        "ema_directional_slope": directional(result["entry_ema3_rsi_slope_3"]),
        "wma_directional_slope": directional(result["entry_wma21_rsi_slope_3"]),
        "gap_directional_slope": directional(result["entry_ema_minus_wma_slope_3"]),
        "rsi_slope_angle_degrees": angle_degrees(result["entry_rsi9_slope_3"]),
        "ema_slope_angle_degrees": angle_degrees(result["entry_ema3_rsi_slope_3"]),
        "wma_slope_angle_degrees": angle_degrees(result["entry_wma21_rsi_slope_3"]),
    })
    return result


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [enrich(row) for row in csv.DictReader(handle)]
    required = {
        "session_date", "split", "direction", "route", "captured_points",
        "mfe_points", *RAW_FEATURES,
    }
    missing = required - set(rows[0] if rows else ())
    if missing:
        raise ValueError(f"input is missing columns: {sorted(missing)}")
    unavailable = [row for row in rows if any(
        row.get(name) is None for name in RAW_FEATURES
    )]
    if unavailable:
        print(
            "NOTICE: excluding", len(unavailable),
            "trades with unavailable entry indicators", flush=True,
        )
    return [row for row in rows if all(
        row.get(name) is not None for name in RAW_FEATURES
    )]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def maximum_drawdown(points: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    result = 0.0
    for value in points:
        equity += value
        peak = max(peak, equity)
        result = max(result, peak - equity)
    return result


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "trades": 0, "total_points": 0.0, "mean_points": None,
            "median_points": None, "positive": 0, "negative": 0,
            "win_rate_pct": None, "profit_factor": None,
            "max_drawdown_points": 0.0,
        }
    points = [float(row["captured_points"]) for row in rows]
    gains = sum(value for value in points if value > 0)
    losses = -sum(value for value in points if value < 0)
    positive = sum(value > 0 for value in points)
    return {
        "trades": len(rows),
        "total_points": sum(points),
        "mean_points": fmean(points),
        "median_points": median(points),
        "positive": positive,
        "negative": sum(value < 0 for value in points),
        "win_rate_pct": 100.0 * positive / len(rows),
        "profit_factor": gains / losses if losses else None,
        "max_drawdown_points": maximum_drawdown(points),
        "mean_mfe_points": fmean(float(row["mfe_points"]) for row in rows),
        "median_mfe_points": median(float(row["mfe_points"]) for row in rows),
        "mean_mae_points": fmean(float(row["mae_points"]) for row in rows),
        "mean_giveback_points": fmean(float(row["giveback_points"]) for row in rows),
    }


def describe(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": fmean(values) if values else None,
        "median": median(values) if values else None,
        "p10": percentile(values, 0.10),
        "p25": percentile(values, 0.25),
        "p75": percentile(values, 0.75),
        "p90": percentile(values, 0.90),
    }


def flat_sensitivity(
    rows: list[dict[str, Any]],
    frozen_large_thresholds: dict[str, float],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for epsilon in SENSITIVITY_EPSILONS:
        for split in ("IS", "OOS"):
            for direction in ("BULLISH", "BEARISH"):
                cohort = [
                    row for row in rows
                    if row["split"] == split and row["direction"] == direction
                ]
                rejected = [
                    row for row in cohort
                    if abs(float(row["entry_wma21_rsi_slope_3"])) <= epsilon
                ]
                kept = [row for row in cohort if row not in rejected]
                baseline = metrics(cohort)
                keep_stats = metrics(kept)
                reject_stats = metrics(rejected)
                # The large-move definition is learned from IS once and then
                # remains frozen for OOS. Never recalculate an OOS percentile.
                large_cutoff = frozen_large_thresholds[direction]
                large = [
                    row for row in cohort
                    if large_cutoff is not None
                    and float(row["mfe_points"]) >= large_cutoff
                ]
                rejected_large = [row for row in large if row in rejected]
                output.append({
                    "epsilon": epsilon,
                    "split": split,
                    "direction": direction,
                    "baseline_trades": baseline["trades"],
                    "baseline_total_points": baseline["total_points"],
                    "kept_trades": keep_stats["trades"],
                    "kept_total_points": keep_stats["total_points"],
                    "kept_mean_points": keep_stats["mean_points"],
                    "kept_profit_factor": keep_stats["profit_factor"],
                    "rejected_trades": reject_stats["trades"],
                    "rejected_total_points": reject_stats["total_points"],
                    "rejected_mean_points": reject_stats["mean_points"],
                    "rejected_profit_factor": reject_stats["profit_factor"],
                    "counterfactual_point_delta": -reject_stats["total_points"],
                    "large_mfe_threshold": large_cutoff,
                    "large_moves": len(large),
                    "large_moves_rejected": len(rejected_large),
                    "large_move_rejection_pct": (
                        100.0 * len(rejected_large) / len(large) if large else None
                    ),
                })
    return output


def large_thresholds(rows: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for direction in ("BULLISH", "BEARISH"):
        values = [
            float(row["mfe_points"]) for row in rows
            if row["split"] == "IS" and row["direction"] == direction
        ]
        threshold = percentile(values, 0.90)
        if threshold is None:
            raise ValueError(f"no IS MFE values for {direction}")
        result[direction] = threshold
    return result


def cohort_name(row: dict[str, Any], thresholds: dict[str, float]) -> str:
    if float(row["mfe_points"]) >= thresholds[row["direction"]]:
        return "LARGE_MFE_TOP_DECILE_IS_THRESHOLD"
    if float(row["captured_points"]) <= 0:
        return "FAILING_NON_POSITIVE"
    return "OTHER_POSITIVE"


def cohort_feature_comparison(
    rows: list[dict[str, Any]], thresholds: dict[str, float]
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["split"], row["direction"], cohort_name(row, thresholds))].append(row)
    output: list[dict[str, Any]] = []
    for (split, direction, cohort), values in sorted(groups.items()):
        trade_stats = metrics(values)
        for feature in RAW_FEATURES + DIRECTIONAL_FEATURES:
            summary = describe([
                float(row[feature]) for row in values if row.get(feature) is not None
            ])
            output.append({
                "split": split,
                "direction": direction,
                "cohort": cohort,
                "feature": feature,
                **trade_stats,
                **{f"feature_{key}": value for key, value in summary.items()},
            })
    return output


def learn_sweet_spots(
    rows: list[dict[str, Any]], thresholds: dict[str, float]
) -> dict[str, dict[str, dict[str, float]]]:
    profiles: dict[str, dict[str, dict[str, float]]] = {}
    nonnegative_features = {
        "rsi_directional_level",
        "ema_wma_directional_gap",
        "rsi_directional_slope",
        "ema_directional_slope",
        "wma_directional_slope",
    }
    for direction in ("BULLISH", "BEARISH"):
        winners = [
            row for row in rows
            if row["split"] == "IS"
            and row["direction"] == direction
            and float(row["mfe_points"]) >= thresholds[direction]
        ]
        profile: dict[str, dict[str, float]] = {}
        for feature in DIRECTIONAL_FEATURES:
            values = [float(row[feature]) for row in winners]
            lower = percentile(values, 0.10)
            upper = percentile(values, 0.90)
            if lower is None or upper is None:
                continue
            if feature in nonnegative_features:
                lower = max(lower, 0.0)
            if feature == "wma_directional_slope":
                lower = max(lower, PRIMARY_FLAT_EPSILON)
            profile[feature] = {
                "minimum": lower,
                "maximum": upper,
                "median": float(median(values)),
            }
        profiles[direction] = profile
    return profiles


def sweet_spot_score(
    row: dict[str, Any], profile: dict[str, dict[str, float]]
) -> tuple[int, int]:
    passed = 0
    available = 0
    for feature, limits in profile.items():
        value = row.get(feature)
        if value is None:
            continue
        available += 1
        if limits["minimum"] <= float(value) <= limits["maximum"]:
            passed += 1
    return passed, available


def validate_sweet_spots(
    rows: list[dict[str, Any]],
    profiles: dict[str, dict[str, dict[str, float]]],
    thresholds: dict[str, float],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        profile = profiles[row["direction"]]
        score, available = sweet_spot_score(row, profile)
        wma_slope = float(row["wma_directional_slope"])
        selected = (
            wma_slope > PRIMARY_FLAT_EPSILON
            and available >= 5
            and score >= 4
        )
        row["sweet_spot_score"] = score
        row["sweet_spot_available"] = available
        row["sweet_spot_selected"] = selected
        row["large_mfe_by_is_threshold"] = (
            float(row["mfe_points"]) >= thresholds[row["direction"]]
        )

    for split in ("IS", "OOS"):
        for direction in ("BULLISH", "BEARISH"):
            base = [
                row for row in rows
                if row["split"] == split and row["direction"] == direction
            ]
            selected = [row for row in base if row["sweet_spot_selected"]]
            missed_large = [
                row for row in base
                if row["large_mfe_by_is_threshold"]
                and not row["sweet_spot_selected"]
            ]
            large = [row for row in base if row["large_mfe_by_is_threshold"]]
            stats = metrics(selected)
            output.append({
                "split": split,
                "direction": direction,
                **stats,
                "baseline_trades": len(base),
                "selection_rate_pct": 100.0 * len(selected) / len(base) if base else None,
                "large_moves": len(large),
                "large_moves_selected": len(large) - len(missed_large),
                "large_move_capture_pct": (
                    100.0 * (len(large) - len(missed_large)) / len(large)
                    if large else None
                ),
            })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = load_rows(args.input)
    thresholds = large_thresholds(rows)
    flat_rows = flat_sensitivity(rows, thresholds)
    comparison = cohort_feature_comparison(rows, thresholds)
    profiles = learn_sweet_spots(rows, thresholds)
    validation = validate_sweet_spots(rows, profiles, thresholds)

    large = [
        row for row in rows
        if float(row["mfe_points"]) >= thresholds[row["direction"]]
    ]
    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "flat-wma-sensitivity.csv", flat_rows)
    write_csv(args.output_root / "large-gain-trades.csv", large)
    write_csv(args.output_root / "cohort-feature-comparison.csv", comparison)
    write_csv(args.output_root / "sweet-spot-validation.csv", validation)
    write_csv(args.output_root / "trade-signature-scores.csv", rows)

    primary_flat = [
        row for row in flat_rows
        if row["epsilon"] == PRIMARY_FLAT_EPSILON
    ]
    report = {
        "model": "HILEGA_LARGE_GAIN_SIGNATURE_RESEARCH_V1",
        "input_trades_with_complete_indicators": len(rows),
        "large_gain_definition": {
            "metric": "MFE_POINTS",
            "threshold_source": "IS_DIRECTIONAL_90TH_PERCENTILE",
            "thresholds": thresholds,
            "reason": (
                "MFE measures signal expansion independently of the existing "
                "structural exit's giveback."
            ),
        },
        "flat_wma_filter": {
            "slope": "OLS over 3 completed five-minute RSI-WMA21 values",
            "primary_epsilon": PRIMARY_FLAT_EPSILON,
            "definition": "abs(WMA21 RSI slope) <= epsilon",
            "primary_results": primary_flat,
            "sensitivity_epsilons": list(SENSITIVITY_EPSILONS),
            "decision_guard": (
                "Strict no-trade is supported only if rejected points are negative "
                "and large-move rejection remains acceptable in both IS and OOS."
            ),
        },
        "large_gain_profiles": profiles,
        "sweet_spot_rule": {
            "source": "IS top-decile MFE directional feature p10-p90 ranges",
            "wma_requirement": f"directional WMA slope > {PRIMARY_FLAT_EPSILON}",
            "score_requirement": "at least 4 of 6 IS-derived feature ranges",
            "validation": validation,
        },
        "angle_warning": (
            "Angles are atan(indicator slope) in indicator space. Chart angles "
            "depend on visual scaling and must not be used as invariant rules."
        ),
        "safety": {
            "research_only": True,
            "observation_only": True,
            "live_strategy_modified": False,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        },
    }
    (args.output_root / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )

    print("HILEGA LARGE-GAIN SIGNATURE RESEARCH", len(rows), "trades")
    print("IS top-decile MFE thresholds", thresholds)
    print("IS LARGE-GAIN PROFILES")
    print(json.dumps(profiles, indent=2))
    print("PRIMARY FLAT FILTER")
    for row in primary_flat:
        print(row)
    print("SWEET SPOT VALIDATION")
    for row in validation:
        print(row)
    print("Output:", args.output_root / "report.json")
    print("Read only: strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
