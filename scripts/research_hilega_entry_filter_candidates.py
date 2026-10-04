#!/usr/bin/env python3
"""Compare three causal Hilega entry-health candidates on frozen IS/OOS data.

The source is the immutable 490-session Hilega alignment/points trade file.
Every feature is measured at entry from completed candles.  No outcome field is
used by a candidate rule.  The script is research-only and never changes live
strategy state, services, audits, orders, paper orders, or quantity.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable


DEFAULT_INPUT = Path(
    "data/historical-evidence/hilega-alignment-points-490-v1/"
    "trade-alignment-points.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-entry-filter-candidates-490-v1"
)
FLAT_WMA_EPSILON = 0.10
DIRECTIONS = ("BULLISH", "BEARISH")
SPLITS = ("IS", "OOS")
CANDIDATES = (
    "CONTROL_CURRENT_POLICY",
    "LARGE_GAIN_ALIGNMENT",
    "FLAT_WMA_CONFIRMATION_FILTER",
)
RAW_FEATURES = (
    "entry_rsi9",
    "entry_ema_minus_wma",
    "entry_rsi9_slope_3",
    "entry_ema3_rsi_slope_3",
    "entry_wma21_rsi_slope_3",
    "entry_ema_minus_wma_slope_3",
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


def enrich(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in RAW_FEATURES + (
        "captured_points", "mfe_points", "mae_points", "giveback_points"
    ):
        result[key] = finite(row.get(key))
    direction = str(row.get("direction", ""))
    if direction not in DIRECTIONS:
        raise ValueError(f"unsupported direction: {direction!r}")
    sign = 1.0 if direction == "BULLISH" else -1.0
    rsi = result["entry_rsi9"]
    result.update({
        "rsi_directional_level": (
            None if rsi is None else sign * (rsi - 50.0)
        ),
        "ema_wma_directional_gap": _signed(
            result["entry_ema_minus_wma"], sign
        ),
        "rsi_directional_slope": _signed(
            result["entry_rsi9_slope_3"], sign
        ),
        "ema_directional_slope": _signed(
            result["entry_ema3_rsi_slope_3"], sign
        ),
        "wma_directional_slope": _signed(
            result["entry_wma21_rsi_slope_3"], sign
        ),
        "gap_directional_slope": _signed(
            result["entry_ema_minus_wma_slope_3"], sign
        ),
    })
    return result


def _signed(value: float | None, sign: float) -> float | None:
    return None if value is None else sign * value


def load_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        source = list(csv.DictReader(handle))
    if not source:
        raise ValueError("input contains no trades")
    required = {
        "session_date", "split", "direction", "route", "captured_points",
        "mfe_points", "mae_points", "giveback_points", *RAW_FEATURES,
    }
    missing = required - set(source[0])
    if missing:
        raise ValueError(f"input is missing columns: {sorted(missing)}")
    enriched = [enrich(row) for row in source]
    unavailable = [
        row for row in enriched
        if any(row.get(feature) is None for feature in RAW_FEATURES)
        or row.get("captured_points") is None
        or row.get("mfe_points") is None
        or row.get("mae_points") is None
        or row.get("giveback_points") is None
    ]
    complete = [row for row in enriched if row not in unavailable]
    return complete, len(unavailable)


def maximum_drawdown(points: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in points:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "trades": 0,
            "total_points": 0.0,
            "mean_points": None,
            "median_points": None,
            "positive": 0,
            "negative": 0,
            "win_rate_pct": None,
            "profit_factor": None,
            "max_drawdown_points": 0.0,
        }
    points = [float(row["captured_points"]) for row in rows]
    gains = sum(point for point in points if point > 0)
    losses = -sum(point for point in points if point < 0)
    positive = sum(point > 0 for point in points)
    return {
        "trades": len(rows),
        "total_points": sum(points),
        "mean_points": fmean(points),
        "median_points": median(points),
        "positive": positive,
        "negative": sum(point < 0 for point in points),
        "win_rate_pct": 100.0 * positive / len(rows),
        "profit_factor": gains / losses if losses else None,
        "max_drawdown_points": maximum_drawdown(points),
        "mean_mfe_points": fmean(float(row["mfe_points"]) for row in rows),
        "mean_mae_points": fmean(float(row["mae_points"]) for row in rows),
        "mean_giveback_points": fmean(
            float(row["giveback_points"]) for row in rows
        ),
    }


def learn_large_thresholds(rows: list[dict[str, Any]]) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for direction in DIRECTIONS:
        threshold = percentile(
            (
                float(row["mfe_points"])
                for row in rows
                if row["split"] == "IS" and row["direction"] == direction
            ),
            0.90,
        )
        if threshold is None:
            raise ValueError(f"no IS MFE values for {direction}")
        thresholds[direction] = threshold
    return thresholds


def evaluate_entry(row: dict[str, Any]) -> dict[str, Any]:
    flat = abs(float(row["entry_wma21_rsi_slope_3"])) <= FLAT_WMA_EPSILON
    checks = {
        "rsi_side_support": float(row["rsi_directional_level"]) > 0.0,
        "ema_wma_alignment_support": (
            float(row["ema_wma_directional_gap"]) > 0.0
        ),
        "rsi_slope_support": float(row["rsi_directional_slope"]) > 0.0,
        "ema_slope_support": float(row["ema_directional_slope"]) > 0.0,
        "wma_slope_support": (
            float(row["wma_directional_slope"]) > FLAT_WMA_EPSILON
        ),
    }
    weakness = {
        "gap_not_expanding": float(row["gap_directional_slope"]) <= 0.0,
        "rsi_slope_weak": float(row["rsi_directional_slope"]) <= 0.0,
        "ema_slope_weak": float(row["ema_directional_slope"]) <= 0.0,
    }
    weak_reasons = [name for name, failed in weakness.items() if failed]
    aligned = all(checks.values())
    confirmed_flat_reject = flat and len(weak_reasons) >= 2
    return {
        "wma_flat_warning": flat,
        **checks,
        **weakness,
        "alignment_support_count": sum(checks.values()),
        "large_gain_alignment_keep": aligned,
        "flat_weakness_count": len(weak_reasons),
        "flat_weakness_reasons": "|".join(weak_reasons),
        "flat_confirmation_reject": confirmed_flat_reject,
        "flat_confirmation_keep": not confirmed_flat_reject,
    }


def candidate_keeps(row: dict[str, Any], candidate: str) -> bool:
    if candidate == "CONTROL_CURRENT_POLICY":
        return True
    if candidate == "LARGE_GAIN_ALIGNMENT":
        return bool(row["large_gain_alignment_keep"])
    if candidate == "FLAT_WMA_CONFIRMATION_FILTER":
        return bool(row["flat_confirmation_keep"])
    raise ValueError(f"unknown candidate: {candidate}")


def apply_rules(rows: list[dict[str, Any]], thresholds: dict[str, float]) -> None:
    for row in rows:
        row.update(evaluate_entry(row))
        row["large_move_by_frozen_is_threshold"] = (
            float(row["mfe_points"]) >= thresholds[row["direction"]]
        )


def cohort_rows(
    rows: list[dict[str, Any]], split: str, direction: str
) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if row["split"] == split
        and (direction == "ALL" or row["direction"] == direction)
    ]


def candidate_summary(
    rows: list[dict[str, Any]], thresholds: dict[str, float]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for split in SPLITS:
        for direction in (*DIRECTIONS, "ALL"):
            baseline = cohort_rows(rows, split, direction)
            baseline_stats = metrics(baseline)
            for candidate in CANDIDATES:
                kept = [row for row in baseline if candidate_keeps(row, candidate)]
                rejected = [
                    row for row in baseline if not candidate_keeps(row, candidate)
                ]
                large = [
                    row for row in baseline
                    if row["large_move_by_frozen_is_threshold"]
                ]
                retained_large = [
                    row for row in large if candidate_keeps(row, candidate)
                ]
                kept_stats = metrics(kept)
                rejected_stats = metrics(rejected)
                output.append({
                    "split": split,
                    "direction": direction,
                    "candidate": candidate,
                    **kept_stats,
                    "baseline_trades": baseline_stats["trades"],
                    "baseline_total_points": baseline_stats["total_points"],
                    "baseline_profit_factor": baseline_stats["profit_factor"],
                    "baseline_max_drawdown_points": (
                        baseline_stats["max_drawdown_points"]
                    ),
                    "rejected_trades": rejected_stats["trades"],
                    "rejected_total_points": rejected_stats["total_points"],
                    "point_delta_vs_control": -rejected_stats["total_points"],
                    "large_threshold_bullish": thresholds["BULLISH"],
                    "large_threshold_bearish": thresholds["BEARISH"],
                    "large_moves": len(large),
                    "large_moves_retained": len(retained_large),
                    "large_move_retention_pct": (
                        100.0 * len(retained_large) / len(large)
                        if large else None
                    ),
                })
    return output


def warning_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for split in SPLITS:
        for direction in (*DIRECTIONS, "ALL"):
            cohort = cohort_rows(rows, split, direction)
            for state, selected in (
                ("WMA_FLAT_WARNING", [r for r in cohort if r["wma_flat_warning"]]),
                ("WMA_NOT_FLAT", [r for r in cohort if not r["wma_flat_warning"]]),
            ):
                output.append({
                    "split": split,
                    "direction": direction,
                    "state": state,
                    **metrics(selected),
                })
    return output


def route_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    routes = sorted({str(row["route"]) for row in rows})
    for split in SPLITS:
        for direction in DIRECTIONS:
            for route in routes:
                cohort = [
                    row for row in rows
                    if row["split"] == split
                    and row["direction"] == direction
                    and row["route"] == route
                ]
                if not cohort:
                    continue
                for candidate in CANDIDATES[1:]:
                    kept = [r for r in cohort if candidate_keeps(r, candidate)]
                    rejected = [r for r in cohort if not candidate_keeps(r, candidate)]
                    output.append({
                        "split": split,
                        "direction": direction,
                        "route": route,
                        "candidate": candidate,
                        **metrics(kept),
                        "baseline_trades": len(cohort),
                        "rejected_trades": len(rejected),
                        "rejected_total_points": sum(
                            float(r["captured_points"]) for r in rejected
                        ),
                    })
    return output


def rejection_reason_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for split in SPLITS:
        for direction in DIRECTIONS:
            rejected = [
                row for row in rows
                if row["split"] == split
                and row["direction"] == direction
                and row["flat_confirmation_reject"]
            ]
            counts: Counter[str] = Counter()
            points: defaultdict[str, float] = defaultdict(float)
            for row in rejected:
                for reason in str(row["flat_weakness_reasons"]).split("|"):
                    if reason:
                        counts[reason] += 1
                        points[reason] += float(row["captured_points"])
            for reason in sorted(counts):
                output.append({
                    "split": split,
                    "direction": direction,
                    "reason": reason,
                    "rejected_trades_containing_reason": counts[reason],
                    "points_for_trades_containing_reason": points[reason],
                })
    return output


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


def key_results(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in summary
        if row["direction"] in DIRECTIONS
        and row["candidate"] != "CONTROL_CURRENT_POLICY"
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows, unavailable = load_rows(args.input)
    thresholds = learn_large_thresholds(rows)
    apply_rules(rows, thresholds)
    summary = candidate_summary(rows, thresholds)
    warning = warning_summary(rows)
    routes = route_summary(rows)
    reasons = rejection_reason_summary(rows)

    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "candidate-summary.csv", summary)
    write_csv(args.output_root / "flat-warning-summary.csv", warning)
    write_csv(args.output_root / "candidate-route-summary.csv", routes)
    write_csv(args.output_root / "flat-confirmation-reasons.csv", reasons)
    write_csv(args.output_root / "trade-candidate-decisions.csv", rows)

    report = {
        "model": "HILEGA_ENTRY_FILTER_CANDIDATES_490_V1",
        "complete_indicator_trades": len(rows),
        "excluded_unavailable_indicator_trades": unavailable,
        "frozen_is_large_mfe_thresholds": thresholds,
        "candidate_definitions": {
            "WMA_FLAT_WARNING": (
                f"Tag only when abs(raw WMA21-RSI OLS3 slope) <= "
                f"{FLAT_WMA_EPSILON}; never rejects a trade."
            ),
            "LARGE_GAIN_ALIGNMENT": (
                "Keep only when RSI is on the intended side of 50, EMA3-RSI "
                "is on the intended side of WMA21-RSI, RSI and EMA slopes "
                f"support direction, and directional WMA slope > "
                f"{FLAT_WMA_EPSILON}."
            ),
            "FLAT_WMA_CONFIRMATION_FILTER": (
                f"Reject only when abs(WMA slope) <= {FLAT_WMA_EPSILON} and "
                "at least two are weak: directional EMA-WMA gap slope <= 0, "
                "directional RSI slope <= 0, directional EMA slope <= 0."
            ),
        },
        "candidate_summary": summary,
        "flat_warning_summary": warning,
        "rejection_reason_summary": reasons,
        "interpretation_guards": [
            "Candidate rules use entry-time completed-candle features only.",
            "IS and OOS labels come from the immutable source dataset.",
            "Large-move thresholds are learned from IS once and frozen for OOS.",
            "A filtered trade contributes zero counterfactual points.",
            "No candidate is a live rule until robustness gates are reviewed.",
        ],
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

    print("HILEGA ENTRY FILTER CANDIDATES", len(rows), "trades")
    print("Excluded unavailable indicators:", unavailable)
    print("Frozen IS large-MFE thresholds:", thresholds)
    print("FLAT WARNING COHORTS")
    for row in warning:
        if row["direction"] in DIRECTIONS:
            print(row)
    print("CANDIDATE RESULTS")
    for row in key_results(summary):
        print(row)
    print("Output:", args.output_root / "report.json")
    print("Research only: live strategy, services, audits and orders untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
