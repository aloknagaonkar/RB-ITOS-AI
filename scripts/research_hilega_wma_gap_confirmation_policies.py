#!/usr/bin/env python3
"""Compare causal Hilega WMA-gap confirmation policies over 490 sessions."""

from __future__ import annotations

import argparse
import copy
import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from market_lab.domain import IST
from market_lab.hilega_milega_historical_replay_v1 import (
    UNDERLYING,
    _read_cache,
    aggregate_exact_5m,
)
from market_lab.hilega_milega_strategy_v1 import HilegaMilegaIndicatorEngineV1
from scripts.backtest_hilega_wma_gap_490 import (
    DIRECTIONS,
    assign_evidence_blocks,
    cache_sessions,
    directional_gap,
    directional_points,
    exact_next_minute,
    percentile,
    read_trades,
    write_csv,
)
from scripts.validate_hilega_wma_delayed_confirmation import validate_trade


DEFAULT_CACHE = Path("data/historical-evidence/hilega-milega-underlying-cache-v1")
DEFAULT_TRADES = Path(
    "data/historical-evidence/hilega-alignment-points-490-v1/"
    "trade-alignment-points.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-wma-gap-confirmation-policies-490-v1"
)
POLICIES = (
    "CURRENT_FIRST_CONFIRMATION",
    "NEXT_CLOSE_PERSISTENCE",
    "EARLY_RECONFIRMATION_T3_T5",
)


def passed_pairs(
    trace: list[dict[str, Any]], threshold: float
) -> list[dict[str, Any]]:
    """Return every causal consecutive-minute WMA-gap confirmation."""
    ordered = sorted(trace, key=lambda row: row["minute_timestamp"])
    output: list[dict[str, Any]] = []
    if not ordered:
        return output
    signal_at = datetime.fromisoformat(
        str(ordered[0]["strategy_signal_timestamp"])
    )
    actionable_at = signal_at + timedelta(minutes=5)
    for armed, current in zip(ordered, ordered[1:]):
        if not exact_next_minute(armed, current):
            continue
        armed_strength = float(armed["directional_wma_change"])
        current_strength = float(current["directional_wma_change"])
        if armed_strength < threshold or current_strength < threshold:
            continue
        direction = str(current["direction"])
        armed_gap = directional_gap(armed, direction)
        current_gap = directional_gap(current, direction)
        gap_delta = current_gap - armed_gap
        if current_gap <= 0 or gap_delta <= 0:
            continue
        confirmation_at = datetime.fromisoformat(
            str(current["minute_timestamp"])
        )
        latency = (confirmation_at - actionable_at).total_seconds() / 60.0
        if latency < 0:
            continue
        output.append({
            "trade_id": current["trade_id"],
            "direction": direction,
            "armed_timestamp": armed["minute_timestamp"],
            "confirmation_timestamp": current["minute_timestamp"],
            "confirmation_price": float(current["observed_close"]),
            "actionable_latency_minutes": latency,
            "armed_wma_strength": armed_strength,
            "confirmation_wma_strength": current_strength,
            "armed_directional_gap": armed_gap,
            "confirmation_directional_gap": current_gap,
            "directional_gap_delta": gap_delta,
        })
    return output


def select_current(pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
    return pairs[0] if pairs else None


def select_persistence(pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Enter when the full predicate passes on two consecutive closes."""
    for first, second in zip(pairs, pairs[1:]):
        if first["confirmation_timestamp"] == second["armed_timestamp"]:
            return second
    return None


def select_early_reconfirmation(
    pairs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not pairs:
        return None
    first = pairs[0]
    first_latency = float(first["actionable_latency_minutes"])
    if first_latency > 2:
        return first
    for candidate in pairs[1:]:
        latency = float(candidate["actionable_latency_minutes"])
        if 3 <= latency <= 5:
            return candidate
    return None


def choose(policy: str, pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if policy == "CURRENT_FIRST_CONFIRMATION":
        return select_current(pairs)
    if policy == "NEXT_CLOSE_PERSISTENCE":
        return select_persistence(pairs)
    if policy == "EARLY_RECONFIRMATION_T3_T5":
        return select_early_reconfirmation(pairs)
    raise ValueError(f"unknown policy: {policy}")


def simulate(
    *,
    trades: list[dict[str, Any]],
    cache_root: Path,
    threshold: float,
    strong_threshold: float,
    timeout_minutes: int,
) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade["session_date"])].append(trade)
    selected_dates = set(grouped)
    last_day = max(date.fromisoformat(day) for day in selected_dates)
    engine = HilegaMilegaIndicatorEngineV1()
    results: list[dict[str, Any]] = []
    processed: set[str] = set()

    for day, path in cache_sessions(cache_root, last_day):
        candles = _read_cache(path, UNDERLYING, day)
        if not candles:
            continue
        try:
            bars = aggregate_exact_5m(candles, day, require_full_session=True)
        except ValueError:
            if day.isoformat() in selected_dates:
                raise
            continue
        states: dict[tuple[str, datetime], Any] = {}
        snapshots: dict[tuple[str, datetime], Any] = {}
        for bar in bars:
            snapshot = engine.update(float(bar.close))
            if day.isoformat() in selected_dates:
                key = (day.isoformat(), bar.ts.astimezone(IST))
                states[key] = copy.deepcopy(engine)
                snapshots[key] = snapshot
        session_trades = grouped.get(day.isoformat(), [])
        if not session_trades:
            continue
        processed.add(day.isoformat())
        ordered_candles = sorted(candles, key=lambda candle: candle.timestamp)
        for trade in session_trades:
            _, trace = validate_trade(
                trade,
                states=states,
                snapshots=snapshots,
                candles=ordered_candles,
                threshold=threshold,
                strong_threshold=strong_threshold,
                timeout_minutes=timeout_minutes,
            )
            if not trace:
                continue
            pairs = passed_pairs(trace, threshold)
            for policy in POLICIES:
                selected = choose(policy, pairs)
                candidate_points = None
                entry_price = None
                if selected is not None:
                    entry_price = float(selected["confirmation_price"])
                    candidate_points = directional_points(
                        str(trade["direction"]),
                        entry_price,
                        float(trade["exit_price"]),
                    )
                results.append({
                    "session_date": trade["session_date"],
                    "evidence_block": trade["evidence_block"],
                    "trade_id": trade["trade_id"],
                    "direction": trade["direction"],
                    "route": trade["route"],
                    "signal_timestamp": trade["entry_timestamp"],
                    "canonical_entry_price": trade["entry_price"],
                    "canonical_exit_timestamp": trade["exit_timestamp"],
                    "canonical_exit_price": trade["exit_price"],
                    "canonical_points": float(trade["captured_points"]),
                    "mfe_points": float(trade["mfe_points"]),
                    "mae_points": float(trade["mae_points"]),
                    "policy": policy,
                    "decision": "ENTRY" if selected else "NO_ENTRY",
                    "candidate_entry_timestamp": (
                        selected["confirmation_timestamp"] if selected else None
                    ),
                    "candidate_entry_price": entry_price,
                    "actionable_latency_minutes": (
                        selected["actionable_latency_minutes"] if selected else None
                    ),
                    "confirmation_wma_strength": (
                        selected["confirmation_wma_strength"] if selected else None
                    ),
                    "confirmation_directional_gap": (
                        selected["confirmation_directional_gap"] if selected else None
                    ),
                    "directional_gap_delta": (
                        selected["directional_gap_delta"] if selected else None
                    ),
                    "candidate_points": candidate_points,
                    "delta_vs_canonical": (
                        candidate_points - float(trade["captured_points"])
                        if candidate_points is not None else None
                    ),
                    "qualifying_pair_count": len(pairs),
                })
    missing = selected_dates - processed
    if missing:
        raise ValueError(f"trade sessions not evaluated: {sorted(missing)}")
    return results


def maximum_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def metrics(
    rows: Iterable[dict[str, Any]], top_thresholds: dict[str, float]
) -> dict[str, Any]:
    selected = list(rows)
    accepted = [row for row in selected if row["decision"] == "ENTRY"]
    denied = [row for row in selected if row["decision"] == "NO_ENTRY"]
    values = [float(row["candidate_points"]) for row in accepted]
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    gross_win = sum(winners)
    gross_loss = -sum(losers)
    denied_losses = [row for row in denied if float(row["canonical_points"]) < 0]
    denied_winners = [row for row in denied if float(row["canonical_points"]) > 0]
    denied_ids = {str(row["trade_id"]) for row in denied}
    plus20 = [row for row in selected if float(row["mfe_points"]) >= 20]
    top = [
        row for row in selected
        if float(row["mfe_points"]) >= top_thresholds[str(row["direction"])]
    ]
    canonical = sum(float(row["canonical_points"]) for row in selected)
    candidate = sum(values)
    accepted_delta = sum(
        float(row["delta_vs_canonical"]) for row in accepted
    )
    return {
        "signals": len(selected),
        "entries": len(accepted),
        "denied": len(denied),
        "candidate_points": candidate,
        "mean_points": candidate / len(accepted) if accepted else None,
        "median_points": median(values) if values else None,
        "positive": len(winners),
        "negative": len(losers),
        "win_rate_pct": 100 * len(winners) / len(accepted) if accepted else None,
        "gross_winning_points": gross_win,
        "gross_losing_points": gross_loss,
        "profit_factor": gross_win / gross_loss if gross_loss else None,
        "max_drawdown_points": maximum_drawdown(values),
        "canonical_points": canonical,
        "delta_vs_canonical": candidate - canonical,
        "accepted_entry_timing_delta": accepted_delta,
        "adverse_entry_delay_cost_points": sum(
            max(0.0, -float(row["delta_vs_canonical"])) for row in accepted
        ),
        "denied_losing_trades": len(denied_losses),
        "points_saved_on_denied_losses": -sum(
            float(row["canonical_points"]) for row in denied_losses
        ),
        "denied_winning_trades": len(denied_winners),
        "points_lost_on_denied_winners": sum(
            float(row["canonical_points"]) for row in denied_winners
        ),
        "plus20_moves": len(plus20),
        "plus20_moves_destroyed": sum(
            str(row["trade_id"]) in denied_ids for row in plus20
        ),
        "top_decile_moves": len(top),
        "top_decile_moves_destroyed": sum(
            str(row["trade_id"]) in denied_ids for row in top
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--trades", type=Path, default=DEFAULT_TRADES)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument("--strong-threshold", type=float, default=1.0)
    parser.add_argument("--timeout-minutes", type=int, default=10)
    parser.add_argument("--observed-forward-sessions", type=int, default=10)
    args = parser.parse_args()
    trades, unavailable = read_trades(args.trades)
    session_summary = assign_evidence_blocks(trades, args.observed_forward_sessions)
    results = simulate(
        trades=trades,
        cache_root=args.cache_root,
        threshold=args.threshold,
        strong_threshold=args.strong_threshold,
        timeout_minutes=args.timeout_minutes,
    )
    development = [
        row for row in results
        if str(row["evidence_block"]).startswith("DEVELOPMENT_BLOCK_")
        and row["policy"] == POLICIES[0]
    ]
    top_thresholds = {
        direction: percentile(
            [
                float(row["mfe_points"]) for row in development
                if row["direction"] == direction
            ],
            0.90,
        )
        for direction in DIRECTIONS
    }
    headline: list[dict[str, Any]] = []
    blocks = (
        "DEVELOPMENT_ALL", "DEVELOPMENT_BLOCK_1", "DEVELOPMENT_BLOCK_2",
        "DEVELOPMENT_BLOCK_3", "OBSERVED_FORWARD", "ALL_490",
    )
    for block in blocks:
        if block == "DEVELOPMENT_ALL":
            block_rows = [
                row for row in results
                if str(row["evidence_block"]).startswith("DEVELOPMENT_BLOCK_")
            ]
        elif block == "ALL_490":
            block_rows = results
        else:
            block_rows = [
                row for row in results if row["evidence_block"] == block
            ]
        for policy in POLICIES:
            policy_rows = [row for row in block_rows if row["policy"] == policy]
            for direction in ("ALL", *DIRECTIONS):
                selected = (
                    policy_rows if direction == "ALL" else
                    [row for row in policy_rows if row["direction"] == direction]
                )
                if selected:
                    headline.append({
                        "evidence_block": block,
                        "policy": policy,
                        "direction": direction,
                        **metrics(selected, top_thresholds),
                    })
    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "trade-results.csv", results)
    write_csv(args.output_root / "headline.csv", headline)

    comparisons: list[dict[str, Any]] = []
    for block in blocks:
        for direction in ("ALL", *DIRECTIONS):
            rows = [
                row for row in headline
                if row["evidence_block"] == block and row["direction"] == direction
            ]
            control = next(
                (row for row in rows if row["policy"] == POLICIES[0]), None
            )
            if control is None:
                continue
            for row in rows:
                comparisons.append({
                    **row,
                    "delta_points_vs_current_confirmation": (
                        float(row["candidate_points"])
                        - float(control["candidate_points"])
                    ),
                    "additional_plus20_destroyed_vs_current": (
                        int(row["plus20_moves_destroyed"])
                        - int(control["plus20_moves_destroyed"])
                    ),
                    "additional_top_decile_destroyed_vs_current": (
                        int(row["top_decile_moves_destroyed"])
                        - int(control["top_decile_moves_destroyed"])
                    ),
                })
    write_csv(args.output_root / "policy-comparison.csv", comparisons)
    report = {
        "model": "HILEGA_WMA_GAP_CONFIRMATION_POLICIES_490_V1",
        "sessions": session_summary,
        "input_trades": len(trades),
        "unavailable_input_trades": unavailable,
        "development_top_decile_mfe_thresholds": top_thresholds,
        "policies": list(POLICIES),
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
        "interpretation": [
            "All 490 sessions are already-inspected evidence.",
            "The latest ten sessions are descriptive, not untouched OOS evidence.",
            "Every candidate retains the unchanged canonical exit.",
            "No candidate is authorized for live use by this report.",
        ],
    }
    (args.output_root / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print("HILEGA WMA-GAP CONFIRMATION POLICY RESEARCH")
    print("Sessions", session_summary)
    print("Trades", len(trades), "result rows", len(results))
    print("HEADLINE")
    for row in headline:
        if row["evidence_block"] in {
            "DEVELOPMENT_ALL", "OBSERVED_FORWARD", "ALL_490"
        }:
            print(row)
    print("Output:", args.output_root / "report.json")
    print("Read only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
