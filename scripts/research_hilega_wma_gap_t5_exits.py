#!/usr/bin/env python3
"""Test exact-T+5 causal exits on accepted Hilega WMA-gap entries."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

DEFAULT_INPUT = Path(
    "data/historical-evidence/"
    "hilega-wma-gap-capture-failures-490-v1/capture-trade-view.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-wma-gap-t5-exits-490-v1"
)
DEFAULT_CACHE = Path("data/historical-evidence/hilega-milega-underlying-cache-v1")
DIRECTIONS = ("BULLISH", "BEARISH")
POLICIES = (
    "CURRENT_EXIT_POLICY",
    "T5_PRICE_NONPOSITIVE",
    "T5_PRICE_2_OF_4_WEAK",
    "T5_PRICE_ALL_4_WEAK",
)


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate percentile of empty values")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                fields.append(field)
                seen.add(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    required = {
        "trade_id", "session_date", "direction", "evidence_block",
        "candidate_entry_timestamp", "captured_points",
        "candidate_mfe_close_points", "t5_timestamp", "t5_price",
        "t5_points_from_candidate_entry", "t5_wma_strength",
        "t5_directional_gap", "t5_gap_delta_1m",
        "t5_ema_directional_delta_1m", "t5_full_alignment",
    }
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"input CSV missing columns: {sorted(missing)}")
    rows.sort(key=lambda row: row["candidate_entry_timestamp"])
    return rows


def t5_components(row: dict[str, Any], threshold: float = 0.75) -> dict[str, bool]:
    """Return four predeclared weakness components at exact T+5."""
    strength = finite(row.get("t5_wma_strength"))
    gap = finite(row.get("t5_directional_gap"))
    gap_delta = finite(row.get("t5_gap_delta_1m"))
    ema_delta = finite(row.get("t5_ema_directional_delta_1m"))
    alignment = truthy(row.get("t5_full_alignment"))
    return {
        "wma_weak": strength is None or strength < threshold,
        "gap_weak": (
            gap is None or gap_delta is None or gap <= 0.0 or gap_delta <= 0.0
        ),
        "ema_weak": ema_delta is None or ema_delta <= 0.0,
        "alignment_weak": not alignment,
    }


def policy_decision(
    row: dict[str, Any], policy: str, threshold: float = 0.75
) -> dict[str, Any]:
    control = float(row["captured_points"])
    t5_points = finite(row.get("t5_points_from_candidate_entry"))
    t5_available = t5_points is not None and bool(row.get("t5_timestamp"))
    components = t5_components(row, threshold)
    weak_count = sum(components.values())
    price_failed = t5_available and t5_points <= 0.0
    trigger = False
    if policy == "CURRENT_EXIT_POLICY":
        trigger = False
    elif policy == "T5_PRICE_NONPOSITIVE":
        trigger = price_failed
    elif policy == "T5_PRICE_2_OF_4_WEAK":
        trigger = price_failed and weak_count >= 2
    elif policy == "T5_PRICE_ALL_4_WEAK":
        trigger = price_failed and weak_count == 4
    else:
        raise ValueError(f"unknown policy: {policy}")
    candidate = float(t5_points) if trigger else control
    reasons = [name.upper() for name, weak in components.items() if weak]
    return {
        "policy": policy,
        "t5_available": t5_available,
        "t5_price_failed": price_failed,
        **components,
        "weak_component_count": weak_count,
        "exit_triggered": trigger,
        "exit_timestamp": row.get("t5_timestamp") if trigger else None,
        "exit_price": finite(row.get("t5_price")) if trigger else None,
        "exit_reason": (
            "T5_NONPOSITIVE_PRICE|" + "|".join(reasons) if trigger else ""
        ),
        "control_points": control,
        "policy_points": candidate,
        "delta_vs_control": candidate - control,
    }


def maximum_drawdown(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["policy_points"]) for row in rows]
    controls = [float(row["control_points"]) for row in rows]
    wins = [value for value in values if value > 0]
    losses = [-value for value in values if value < 0]
    triggered = [row for row in rows if row["exit_triggered"]]
    loser_exits = [row for row in triggered if float(row["control_points"]) < 0]
    winner_exits = [row for row in triggered if float(row["control_points"]) > 0]
    control_plus20 = [row for row in rows if row["control_plus20_move"]]
    control_top = [row for row in rows if row["control_top_decile_move"]]
    destroyed_plus20 = [
        row for row in triggered
        if row["control_plus20_move"] and not row["plus20_reached_by_t5"]
    ]
    destroyed_top = [
        row for row in triggered
        if row["control_top_decile_move"] and not row["top_decile_reached_by_t5"]
    ]
    return {
        "trades": len(rows),
        "candidate_exits": len(triggered),
        "exit_precision_eventual_loser_pct": (
            100.0 * len(loser_exits) / len(triggered) if triggered else None
        ),
        "control_total_points": sum(controls),
        "policy_total_points": sum(values),
        "delta_vs_control_sum": sum(values) - sum(controls),
        "mean_points": sum(values) / len(values) if values else None,
        "positive": len(wins),
        "negative": len(losses),
        "win_rate_pct": 100.0 * len(wins) / len(values) if values else None,
        "gross_winning_points": sum(wins),
        "gross_losing_points": sum(losses),
        "profit_factor": sum(wins) / sum(losses) if losses else None,
        "max_drawdown_points": maximum_drawdown(values),
        "bad_trades_saved": sum(
            float(row["policy_points"]) > float(row["control_points"])
            for row in loser_exits
        ),
        "bad_trades_harmed": sum(
            float(row["policy_points"]) < float(row["control_points"])
            for row in loser_exits
        ),
        "points_saved_on_control_losers": sum(
            max(0.0, float(row["delta_vs_control"])) for row in loser_exits
        ),
        "control_winners_exited": len(winner_exits),
        "points_lost_on_control_winners": sum(
            max(0.0, -float(row["delta_vs_control"])) for row in winner_exits
        ),
        "control_plus20_moves": len(control_plus20),
        "plus20_moves_destroyed": len(destroyed_plus20),
        "plus20_moves_retained": len(control_plus20) - len(destroyed_plus20),
        "control_top_decile_moves": len(control_top),
        "top_decile_moves_destroyed": len(destroyed_top),
        "top_decile_moves_retained": len(control_top) - len(destroyed_top),
    }


def evidence_sets(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    development = [
        row for row in rows
        if str(row["evidence_block"]).startswith("DEVELOPMENT_BLOCK_")
    ]
    sessions = sorted({row["session_date"] for row in rows})
    result = {
        "DEVELOPMENT_ALL": development,
        "DEVELOPMENT_BLOCK_1": [
            row for row in rows if row["evidence_block"] == "DEVELOPMENT_BLOCK_1"
        ],
        "DEVELOPMENT_BLOCK_2": [
            row for row in rows if row["evidence_block"] == "DEVELOPMENT_BLOCK_2"
        ],
        "DEVELOPMENT_BLOCK_3": [
            row for row in rows if row["evidence_block"] == "DEVELOPMENT_BLOCK_3"
        ],
        "OBSERVED_FORWARD": [
            row for row in rows if row["evidence_block"] == "OBSERVED_FORWARD"
        ],
        "ALL_490": rows,
    }
    recent = [
        ("RECENT_30", sessions[-30:]),
        ("PRIOR_30", sessions[-60:-30]),
        ("EARLIER_30", sessions[-90:-60]),
    ]
    for name, dates in recent:
        wanted = set(dates)
        result[name] = [row for row in rows if row["session_date"] in wanted]
    return result


def exact_pre_t5_mfe(
    rows: list[dict[str, Any]], cache_root: Path
) -> dict[str, float]:
    """Calculate MFE from entry through T+5 using every completed 1m close."""
    from market_lab.hilega_milega_historical_replay_v1 import UNDERLYING, _read_cache

    by_day: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[row["session_date"]].append(row)
    result: dict[str, float] = {}
    for day_text, trades in by_day.items():
        day = date.fromisoformat(day_text)
        path = cache_root / f"{day_text}.json"
        if not path.is_file():
            raise FileNotFoundError(f"minute cache unavailable: {path}")
        candles = _read_cache(path, UNDERLYING, day)
        closes = sorted(
            [(candle.timestamp, float(candle.close)) for candle in candles],
            key=lambda item: item[0],
        )
        for row in trades:
            if not row.get("t5_timestamp"):
                result[row["trade_id"]] = 0.0
                continue
            entry_at = datetime.fromisoformat(row["candidate_entry_timestamp"])
            t5_at = datetime.fromisoformat(row["t5_timestamp"])
            entry_price = float(row["candidate_entry_price"])
            direction = row["direction"]
            points = [0.0]
            for timestamp, close in closes:
                if entry_at <= timestamp <= t5_at:
                    points.append(
                        close - entry_price
                        if direction == "BULLISH" else entry_price - close
                    )
            result[row["trade_id"]] = max(points)
    return result


def decorate(
    rows: list[dict[str, Any]], top_thresholds: dict[str, float],
    pre_t5_mfe: dict[str, float],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        through_t5_mfe = pre_t5_mfe[row["trade_id"]]
        threshold = top_thresholds[row["direction"]]
        row["pre_t5_mfe_points"] = through_t5_mfe
        row["plus20_reached_by_t5"] = through_t5_mfe >= 20.0
        row["top_decile_reached_by_t5"] = through_t5_mfe >= threshold
        row["control_plus20_move"] = (
            float(row["candidate_mfe_close_points"]) >= 20.0
        )
        row["control_top_decile_move"] = (
            float(row["candidate_mfe_close_points"]) >= threshold
        )
        output.append(row)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--wma-threshold", type=float, default=0.75)
    args = parser.parse_args()

    raw = read_rows(args.input)
    development = [
        row for row in raw
        if str(row["evidence_block"]).startswith("DEVELOPMENT_BLOCK_")
    ]
    top_thresholds = {
        direction: percentile([
            float(row["candidate_mfe_close_points"])
            for row in development if row["direction"] == direction
        ], 0.90)
        for direction in DIRECTIONS
    }
    base_rows = decorate(raw, top_thresholds, exact_pre_t5_mfe(raw, args.cache_root))
    comparisons: list[dict[str, Any]] = []
    triggers: list[dict[str, Any]] = []
    for row in base_rows:
        for policy in POLICIES:
            result = policy_decision(row, policy, args.wma_threshold)
            combined = {
                "trade_id": row["trade_id"],
                "session_date": row["session_date"],
                "evidence_block": row["evidence_block"],
                "direction": row["direction"],
                "signal_timestamp": row.get("signal_timestamp"),
                "candidate_entry_timestamp": row["candidate_entry_timestamp"],
                "candidate_entry_price": row.get("candidate_entry_price"),
                "canonical_exit_timestamp": row.get("canonical_exit_timestamp"),
                "canonical_exit_price": row.get("canonical_exit_price"),
                "candidate_mfe_close_points": row["candidate_mfe_close_points"],
                "pre_t5_mfe_points": row["pre_t5_mfe_points"],
                "control_plus20_move": row["control_plus20_move"],
                "plus20_reached_by_t5": row["plus20_reached_by_t5"],
                "control_top_decile_move": row["control_top_decile_move"],
                "top_decile_reached_by_t5": row["top_decile_reached_by_t5"],
                "t5_timestamp": row.get("t5_timestamp"),
                "t5_price": row.get("t5_price"),
                "t5_points": row.get("t5_points_from_candidate_entry"),
                "t5_wma_strength": row.get("t5_wma_strength"),
                "t5_directional_gap": row.get("t5_directional_gap"),
                "t5_gap_delta_1m": row.get("t5_gap_delta_1m"),
                "t5_ema_directional_delta_1m": row.get(
                    "t5_ema_directional_delta_1m"
                ),
                "t5_full_alignment": row.get("t5_full_alignment"),
                **result,
            }
            comparisons.append(combined)
            if combined["exit_triggered"]:
                triggers.append(combined)

    sets = evidence_sets(base_rows)
    headline: list[dict[str, Any]] = []
    for block, source_rows in sets.items():
        ids = {row["trade_id"] for row in source_rows}
        for policy in POLICIES:
            policy_rows = [
                row for row in comparisons
                if row["policy"] == policy and row["trade_id"] in ids
            ]
            for direction in ("ALL", *DIRECTIONS):
                selected = (
                    policy_rows if direction == "ALL" else
                    [row for row in policy_rows if row["direction"] == direction]
                )
                if selected:
                    headline.append({
                        "evidence_block": block,
                        "direction": direction,
                        "policy": policy,
                        **metrics(selected),
                    })

    daily: list[dict[str, Any]] = []
    grouped: defaultdict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in comparisons:
        grouped[(row["session_date"], row["direction"], row["policy"])].append(row)
    for key in sorted(grouped):
        day, direction, policy = key
        daily.append({
            "session_date": day,
            "direction": direction,
            "policy": policy,
            **metrics(grouped[key]),
        })

    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "headline.csv", headline)
    write_csv(args.output_root / "trade-policy-comparison.csv", comparisons)
    write_csv(args.output_root / "exit-trigger-details.csv", triggers)
    write_csv(args.output_root / "daily-policy-summary.csv", daily)
    report = {
        "model": "HILEGA_WMA_GAP_EXACT_T5_EXIT_RESEARCH_V1",
        "sessions": len({row["session_date"] for row in base_rows}),
        "accepted_wma_gap_entries": len(base_rows),
        "wma_threshold": args.wma_threshold,
        "top_decile_mfe_thresholds_from_development": top_thresholds,
        "policies": {
            "CURRENT_EXIT_POLICY": "Unchanged canonical exit control.",
            "T5_PRICE_NONPOSITIVE": "Exact T+5 directional points <= 0.",
            "T5_PRICE_2_OF_4_WEAK": (
                "T+5 points <= 0 and at least two of WMA, gap, EMA, alignment weak."
            ),
            "T5_PRICE_ALL_4_WEAK": (
                "T+5 points <= 0 and all WMA, gap, EMA, alignment weak."
            ),
        },
        "checkpoint_note": (
            "Plus20/top-decile reached-by-T5 uses every completed one-minute close "
            "from the delayed candidate entry through the exact T+5 close."
        ),
        "headline": headline,
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
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    print("HILEGA WMA-GAP EXACT T+5 EXIT RESEARCH")
    print("Sessions", report["sessions"], "accepted entries", len(base_rows))
    print("Top-decile thresholds", top_thresholds)
    print("HEADLINE")
    for row in headline:
        if row["evidence_block"] in {
            "DEVELOPMENT_ALL", "OBSERVED_FORWARD", "ALL_490",
            "RECENT_30", "PRIOR_30", "EARLIER_30",
        } and row["direction"] in {"ALL", "BULLISH", "BEARISH"}:
            print(row)
    print("Output:", args.output_root / "report.json")
    print("Research only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
