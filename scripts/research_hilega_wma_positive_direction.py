#!/usr/bin/env python3
"""Find when a directional WMA21(RSI9) slope produces positive trade results.

This study uses the immutable Hilega 490-session trade/indicator output.  It
normalizes bearish slopes so positive always means "supports the trade", then
tests fixed WMA slope bands and fixed entry-time confirmation profiles.  The
first 480 sessions are split chronologically 70/30; the latest 10 sessions are
reported separately as forward confirmation.  No outcome field participates
in an entry rule and no live state is modified.
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
    "data/historical-evidence/hilega-wma-positive-direction-490-v1"
)
FLAT_EPSILON = 0.10
DIRECTIONS = ("BULLISH", "BEARISH")
SLOPE_BANDS = (
    ("ADVERSE_OR_ZERO", None, 0.0),
    ("WEAK_0_TO_010", 0.0, 0.10),
    ("MILD_010_TO_025", 0.10, 0.25),
    ("MODERATE_025_TO_050", 0.25, 0.50),
    ("STRONG_050_TO_075", 0.50, 0.75),
    ("VERY_STRONG_075_TO_100", 0.75, 1.00),
    ("EXTREME_GT_100", 1.00, None),
)
THRESHOLDS = (0.0, 0.10, 0.25, 0.50, 0.75, 1.00)
PROFILE_NAMES = (
    "WMA_ONLY",
    "WMA_RSI50",
    "WMA_GAP_ALIGNED",
    "WMA_GAP_EXPANDING",
    "WMA_RSI50_GAP_EXPANDING",
    "FULL_DIRECTIONAL_ALIGNMENT",
)
NUMERIC_FIELDS = (
    "captured_points",
    "mfe_points",
    "mae_points",
    "giveback_points",
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
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def enrich(raw: dict[str, Any]) -> dict[str, Any]:
    row = dict(raw)
    for field in NUMERIC_FIELDS:
        row[field] = finite(row.get(field))
    direction = str(row.get("direction", ""))
    if direction not in DIRECTIONS:
        raise ValueError(f"unsupported direction: {direction!r}")
    sign = 1.0 if direction == "BULLISH" else -1.0
    rsi = row["entry_rsi9"]
    row.update({
        "rsi_directional_level": (
            None if rsi is None else sign * (rsi - 50.0)
        ),
        "gap_directional_level": signed(row["entry_ema_minus_wma"], sign),
        "rsi_directional_slope": signed(row["entry_rsi9_slope_3"], sign),
        "ema_directional_slope": signed(row["entry_ema3_rsi_slope_3"], sign),
        "wma_directional_slope": signed(row["entry_wma21_rsi_slope_3"], sign),
        "gap_directional_slope": signed(
            row["entry_ema_minus_wma_slope_3"], sign
        ),
    })
    return row


def signed(value: float | None, sign: float) -> float | None:
    return None if value is None else sign * value


def load_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        source = list(csv.DictReader(handle))
    if not source:
        raise ValueError("input contains no trade rows")
    required = {"session_date", "direction", "route", *NUMERIC_FIELDS}
    missing = required - set(source[0])
    if missing:
        raise ValueError(f"input is missing columns: {sorted(missing)}")
    enriched = [enrich(row) for row in source]
    unavailable = [
        row for row in enriched
        if any(row.get(field) is None for field in NUMERIC_FIELDS)
    ]
    return [row for row in enriched if row not in unavailable], len(unavailable)


def assign_chronological_splits(
    rows: list[dict[str, Any]], *, forward_sessions: int, is_ratio: float
) -> dict[str, Any]:
    sessions = sorted({str(row["session_date"]) for row in rows})
    if forward_sessions < 0 or forward_sessions >= len(sessions):
        raise ValueError("forward_sessions must leave at least one frozen session")
    frozen = sessions[:-forward_sessions] if forward_sessions else sessions
    forward = sessions[-forward_sessions:] if forward_sessions else []
    split_at = int(len(frozen) * is_ratio)
    is_sessions = set(frozen[:split_at])
    oos_sessions = set(frozen[split_at:])
    forward_set = set(forward)
    for row in rows:
        session = str(row["session_date"])
        row["research_split"] = (
            "IS" if session in is_sessions
            else "OOS" if session in oos_sessions
            else "FORWARD" if session in forward_set
            else "UNASSIGNED"
        )
    return {
        "all": len(sessions),
        "frozen": len(frozen),
        "is": len(is_sessions),
        "oos": len(oos_sessions),
        "forward": len(forward_set),
        "first": sessions[0],
        "last": sessions[-1],
        "forward_dates": forward,
    }


def slope_band(value: float) -> str:
    for name, lower, upper in SLOPE_BANDS:
        if lower is None and value <= float(upper):
            return name
        if upper is None and value > float(lower):
            return name
        if lower is not None and upper is not None and lower < value <= upper:
            return name
    raise AssertionError(value)


def maximum_drawdown(points: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in points:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


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
            "plus20_rate_pct": None,
            "immediate_failure_rate_pct": None,
            "mean_mfe_points": None,
            "mean_mae_points": None,
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
        "plus20_rate_pct": 100.0 * sum(
            float(row["mfe_points"]) >= 20.0 for row in rows
        ) / len(rows),
        "immediate_failure_rate_pct": 100.0 * sum(
            float(row["mfe_points"]) < 5.0
            and float(row["captured_points"]) < 0.0
            for row in rows
        ) / len(rows),
        "mean_mfe_points": fmean(float(row["mfe_points"]) for row in rows),
        "mean_mae_points": fmean(float(row["mae_points"]) for row in rows),
        "mean_giveback_points": fmean(
            float(row["giveback_points"]) for row in rows
        ),
        "max_drawdown_points": maximum_drawdown(points),
    }


def profile_keep(row: dict[str, Any], profile: str, threshold: float) -> bool:
    wma = float(row["wma_directional_slope"]) > threshold
    rsi50 = float(row["rsi_directional_level"]) > 0.0
    gap_aligned = float(row["gap_directional_level"]) > 0.0
    gap_expanding = float(row["gap_directional_slope"]) > 0.0
    rsi_slope = float(row["rsi_directional_slope"]) > 0.0
    ema_slope = float(row["ema_directional_slope"]) > 0.0
    if profile == "WMA_ONLY":
        return wma
    if profile == "WMA_RSI50":
        return wma and rsi50
    if profile == "WMA_GAP_ALIGNED":
        return wma and gap_aligned
    if profile == "WMA_GAP_EXPANDING":
        return wma and gap_expanding
    if profile == "WMA_RSI50_GAP_EXPANDING":
        return wma and rsi50 and gap_aligned and gap_expanding
    if profile == "FULL_DIRECTIONAL_ALIGNMENT":
        return (
            wma and rsi50 and gap_aligned and gap_expanding
            and rsi_slope and ema_slope
        )
    raise ValueError(f"unknown profile: {profile}")


def prepare_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row["wma_slope_band"] = slope_band(float(row["wma_directional_slope"]))
        row["rsi50_support"] = float(row["rsi_directional_level"]) > 0.0
        row["gap_alignment_support"] = float(row["gap_directional_level"]) > 0.0
        row["gap_expansion_support"] = float(row["gap_directional_slope"]) > 0.0
        row["rsi_slope_support"] = float(row["rsi_directional_slope"]) > 0.0
        row["ema_slope_support"] = float(row["ema_directional_slope"]) > 0.0


def grouped_metrics(
    rows: list[dict[str, Any]], fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    groups: defaultdict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[field] for field in fields)].append(row)
    return [
        {**dict(zip(fields, key)), **metrics(values)}
        for key, values in sorted(
            groups.items(), key=lambda item: tuple(str(value) for value in item[0])
        )
    ]


def threshold_scan(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for split in ("IS", "OOS", "FORWARD"):
        for direction in (*DIRECTIONS, "ALL"):
            baseline = [
                row for row in rows
                if row["research_split"] == split
                and (direction == "ALL" or row["direction"] == direction)
            ]
            baseline_stats = metrics(baseline)
            for threshold in THRESHOLDS:
                for profile in PROFILE_NAMES:
                    kept = [
                        row for row in baseline
                        if profile_keep(row, profile, threshold)
                    ]
                    rejected = [
                        row for row in baseline
                        if not profile_keep(row, profile, threshold)
                    ]
                    output.append({
                        "split": split,
                        "direction": direction,
                        "profile": profile,
                        "wma_directional_slope_gt": threshold,
                        **metrics(kept),
                        "baseline_trades": baseline_stats["trades"],
                        "baseline_total_points": baseline_stats["total_points"],
                        "selection_rate_pct": (
                            100.0 * len(kept) / len(baseline) if baseline else None
                        ),
                        "rejected_trades": len(rejected),
                        "rejected_total_points": sum(
                            float(row["captured_points"]) for row in rejected
                        ),
                        "point_delta_vs_control": -sum(
                            float(row["captured_points"]) for row in rejected
                        ),
                    })
    return output


def rank_is_profiles(scan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank using IS only; attach OOS/forward without using them to select."""
    lookup = {
        (
            row["split"], row["direction"], row["profile"],
            row["wma_directional_slope_gt"],
        ): row
        for row in scan
    }
    candidates = [
        row for row in scan
        if row["split"] == "IS"
        and row["direction"] in DIRECTIONS
        and row["trades"] >= 50
        and row["selection_rate_pct"] is not None
        and row["selection_rate_pct"] >= 10.0
    ]
    candidates.sort(
        key=lambda row: (
            row["profit_factor"] if row["profit_factor"] is not None else -1.0,
            row["total_points"],
        ),
        reverse=True,
    )
    output: list[dict[str, Any]] = []
    direction_rank: defaultdict[str, int] = defaultdict(int)
    for selected in candidates:
        direction = str(selected["direction"])
        direction_rank[direction] += 1
        key_tail = (
            direction,
            selected["profile"],
            selected["wma_directional_slope_gt"],
        )
        oos = lookup.get(("OOS", *key_tail), {})
        forward = lookup.get(("FORWARD", *key_tail), {})
        output.append({
            "is_rank_within_direction": direction_rank[direction],
            "direction": direction,
            "profile": selected["profile"],
            "wma_directional_slope_gt": selected["wma_directional_slope_gt"],
            "is_trades": selected["trades"],
            "is_total_points": selected["total_points"],
            "is_mean_points": selected["mean_points"],
            "is_win_rate_pct": selected["win_rate_pct"],
            "is_profit_factor": selected["profit_factor"],
            "is_plus20_rate_pct": selected["plus20_rate_pct"],
            "oos_trades": oos.get("trades"),
            "oos_total_points": oos.get("total_points"),
            "oos_mean_points": oos.get("mean_points"),
            "oos_win_rate_pct": oos.get("win_rate_pct"),
            "oos_profit_factor": oos.get("profit_factor"),
            "forward_trades": forward.get("trades"),
            "forward_total_points": forward.get("total_points"),
            "forward_mean_points": forward.get("mean_points"),
            "forward_win_rate_pct": forward.get("win_rate_pct"),
            "forward_profit_factor": forward.get("profit_factor"),
            "selection_basis": "IS_ONLY",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--forward-sessions", type=int, default=10)
    parser.add_argument("--is-ratio", type=float, default=0.70)
    args = parser.parse_args()
    if not 0.0 < args.is_ratio < 1.0:
        raise SystemExit("STOP: --is-ratio must be between zero and one")

    rows, unavailable = load_rows(args.input)
    universe = assign_chronological_splits(
        rows,
        forward_sessions=args.forward_sessions,
        is_ratio=args.is_ratio,
    )
    prepare_rows(rows)
    bands = grouped_metrics(
        rows, ("research_split", "direction", "wma_slope_band")
    )
    bands_by_route = grouped_metrics(
        rows, ("research_split", "direction", "route", "wma_slope_band")
    )
    contexts = grouped_metrics(rows, (
        "research_split", "direction", "wma_slope_band",
        "rsi50_support", "gap_alignment_support", "gap_expansion_support",
    ))
    scan = threshold_scan(rows)
    ranked = rank_is_profiles(scan)

    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "wma-slope-band-summary.csv", bands)
    write_csv(args.output_root / "wma-slope-band-by-route.csv", bands_by_route)
    write_csv(args.output_root / "wma-context-combinations.csv", contexts)
    write_csv(args.output_root / "wma-threshold-profile-scan.csv", scan)
    write_csv(args.output_root / "is-ranked-profiles-with-holdouts.csv", ranked)
    write_csv(args.output_root / "trade-wma-direction-evidence.csv", rows)

    report = {
        "model": "HILEGA_WMA_POSITIVE_DIRECTION_490_V1",
        "purpose": (
            "Determine when directional WMA21(RSI9) slope is associated with "
            "positive captured points, and whether RSI/gap confirmation is needed."
        ),
        "sessions": universe,
        "complete_indicator_trades": len(rows),
        "excluded_unavailable_indicator_trades": unavailable,
        "flat_epsilon": FLAT_EPSILON,
        "slope_bands": [
            {"name": name, "lower_exclusive": lower, "upper_inclusive": upper}
            for name, lower, upper in SLOPE_BANDS
        ],
        "profiles": {
            "WMA_ONLY": "directional WMA slope exceeds tested threshold",
            "WMA_RSI50": "WMA condition plus RSI on intended side of 50",
            "WMA_GAP_ALIGNED": "WMA condition plus EMA-WMA gap aligned",
            "WMA_GAP_EXPANDING": "WMA condition plus directional gap expansion",
            "WMA_RSI50_GAP_EXPANDING": (
                "WMA plus RSI50, aligned gap and expanding gap"
            ),
            "FULL_DIRECTIONAL_ALIGNMENT": (
                "previous profile plus directional RSI and EMA slopes"
            ),
        },
        "is_top_ranked_profiles": [
            row for row in ranked if row["is_rank_within_direction"] <= 10
        ],
        "interpretation_guards": [
            "WMA21 is WMA21 of RSI9, not a WMA of NIFTY price.",
            "Positive WMA slope is evidence, not an entry rule by itself.",
            "All candidate inputs are from the completed entry candle.",
            "Profiles are ranked using IS only; OOS and forward never select a profile.",
            "A profile must remain stable in OOS and forward before observation-only use.",
            "Underlying NIFTY points exclude option premium, spreads, charges and quantity.",
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

    print("HILEGA WMA POSITIVE-DIRECTION STUDY")
    print("Sessions", universe)
    print("Trades", len(rows), "unavailable excluded", unavailable)
    print("WMA SLOPE BANDS")
    for row in bands:
        print(row)
    print("TOP IS-RANKED PROFILES WITH UNTOUCHED HOLDOUT RESULTS")
    for row in report["is_top_ranked_profiles"]:
        print(row)
    print("Output:", args.output_root / "report.json")
    print("Read only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
