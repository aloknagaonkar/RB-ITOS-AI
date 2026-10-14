#!/usr/bin/env python3
"""Backtest ordered Hilega WMA-arm then directional-gap confirmation."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime
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
from scripts.validate_hilega_wma_delayed_confirmation import validate_trade


DEFAULT_CACHE = Path("data/historical-evidence/hilega-milega-underlying-cache-v1")
DEFAULT_TRADES = Path(
    "data/historical-evidence/hilega-alignment-points-490-v1/"
    "trade-alignment-points.csv"
)
DEFAULT_OUTPUT = Path("data/historical-evidence/hilega-wma-gap-490-v1")
DIRECTIONS = ("BULLISH", "BEARISH")


def finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def read_trades(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        raw_rows = list(csv.DictReader(handle))
    if not raw_rows:
        raise ValueError(f"empty CSV: {path}")
    required = {
        "trade_id", "session_date", "direction", "route",
        "entry_timestamp", "entry_price", "exit_timestamp", "exit_price",
        "captured_points", "mfe_points", "mae_points",
    }
    missing = required - set(raw_rows[0])
    if missing:
        raise ValueError(f"trade CSV missing columns: {sorted(missing)}")
    rows: list[dict[str, Any]] = []
    unavailable = 0
    for raw in raw_rows:
        row = dict(raw)
        for field in (
            "entry_price", "exit_price", "captured_points", "mfe_points",
            "mae_points",
        ):
            row[field] = finite(row.get(field))
        if any(row[field] is None for field in (
            "entry_price", "exit_price", "captured_points", "mfe_points",
            "mae_points",
        )):
            unavailable += 1
            continue
        if row["direction"] not in DIRECTIONS:
            raise ValueError(f"unsupported direction: {row['direction']!r}")
        rows.append(row)
    rows.sort(key=lambda row: row["entry_timestamp"])
    return rows, unavailable


def cache_sessions(cache_root: Path, through: date) -> list[tuple[date, Path]]:
    sessions: list[tuple[date, Path]] = []
    for path in cache_root.glob("*.json"):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day <= through:
            sessions.append((day, path))
    return sorted(sessions)


def exact_next_minute(left: dict[str, Any], right: dict[str, Any]) -> bool:
    first = datetime.fromisoformat(str(left["minute_timestamp"]))
    second = datetime.fromisoformat(str(right["minute_timestamp"]))
    return (second - first).total_seconds() == 60.0


def directional_gap(row: dict[str, Any], direction: str) -> float:
    ema = float(row["provisional_ema3_rsi"])
    wma = float(row["provisional_wma21_rsi"])
    return ema - wma if direction == "BULLISH" else wma - ema


def ordered_gap_confirmation(
    trace: list[dict[str, Any]], threshold: float
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Find first later gap expansion after WMA has armed the setup."""
    ordered = sorted(trace, key=lambda row: row["minute_timestamp"])
    attempts: list[dict[str, Any]] = []
    for armed, current in zip(ordered, ordered[1:]):
        armed_window = armed.get("within_confirmation_window")
        current_window = current.get("within_confirmation_window")
        if (
            armed_window not in (None, "") and not truthy(armed_window)
        ) or (
            current_window not in (None, "") and not truthy(current_window)
        ):
            continue
        armed_strength = float(armed["directional_wma_change"])
        current_strength = float(current["directional_wma_change"])
        if armed_strength < threshold or not exact_next_minute(armed, current):
            continue
        direction = str(armed["direction"])
        armed_gap = directional_gap(armed, direction)
        current_gap = directional_gap(current, direction)
        gap_delta = current_gap - armed_gap
        threshold_maintained = current_strength >= threshold
        gap_positive = current_gap > 0.0
        gap_expanding = gap_delta > 0.0
        passed = threshold_maintained and gap_positive and gap_expanding
        failed: list[str] = []
        if not threshold_maintained:
            failed.append("WMA_THRESHOLD_NOT_MAINTAINED")
        if not gap_positive:
            failed.append("DIRECTIONAL_GAP_NOT_POSITIVE")
        if not gap_expanding:
            failed.append("DIRECTIONAL_GAP_NOT_EXPANDING")
        result = {
            "trade_id": armed["trade_id"],
            "session_date": armed["session_date"],
            "direction": direction,
            "strategy_signal_timestamp": armed["strategy_signal_timestamp"],
            "armed_timestamp": armed["minute_timestamp"],
            "confirmation_timestamp": current["minute_timestamp"],
            "armed_close": float(armed["observed_close"]),
            "confirmation_close": float(current["observed_close"]),
            "armed_wma_strength": armed_strength,
            "confirmation_wma_strength": current_strength,
            "armed_directional_gap": armed_gap,
            "confirmation_directional_gap": current_gap,
            "directional_gap_delta": gap_delta,
            "threshold_maintained": threshold_maintained,
            "directional_gap_positive": gap_positive,
            "directional_gap_expanding": gap_expanding,
            "passed": passed,
            "failure_reasons": "|".join(failed),
        }
        attempts.append(result)
        if passed:
            return result, attempts
    return None, attempts


def directional_points(direction: str, entry: float, exit_price: float) -> float:
    return exit_price - entry if direction == "BULLISH" else entry - exit_price


def assign_evidence_blocks(
    trades: list[dict[str, Any]], observed_forward_sessions: int
) -> dict[str, Any]:
    sessions = sorted({str(row["session_date"]) for row in trades})
    if observed_forward_sessions < 0 or observed_forward_sessions >= len(sessions):
        raise ValueError("observed forward sessions must leave development data")
    development = (
        sessions[:-observed_forward_sessions]
        if observed_forward_sessions else sessions
    )
    observed = (
        sessions[-observed_forward_sessions:]
        if observed_forward_sessions else []
    )
    size = len(development) // 3
    block_1 = set(development[:size])
    block_2 = set(development[size:2 * size])
    block_3 = set(development[2 * size:])
    observed_set = set(observed)
    for row in trades:
        day = str(row["session_date"])
        if day in block_1:
            row["evidence_block"] = "DEVELOPMENT_BLOCK_1"
        elif day in block_2:
            row["evidence_block"] = "DEVELOPMENT_BLOCK_2"
        elif day in block_3:
            row["evidence_block"] = "DEVELOPMENT_BLOCK_3"
        elif day in observed_set:
            row["evidence_block"] = "OBSERVED_FORWARD"
        else:
            row["evidence_block"] = "UNASSIGNED"
    return {
        "all_sessions": len(sessions),
        "development_sessions": len(development),
        "development_block_1": len(block_1),
        "development_block_2": len(block_2),
        "development_block_3": len(development) - (2 * size),
        "observed_forward_sessions": len(observed),
        "observed_forward_dates": observed,
        "new_untouched_confirmation_sessions": 0,
        "first_session": sessions[0],
        "last_session": sessions[-1],
    }


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


def simulate(
    *,
    trades: list[dict[str, Any]],
    cache_root: Path,
    threshold: float,
    strong_threshold: float,
    timeout_minutes: int,
    timeline_out: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade["session_date"])].append(trade)
    selected_dates = set(grouped)
    last_day = max(date.fromisoformat(day) for day in selected_dates)
    engine = HilegaMilegaIndicatorEngineV1()
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    unavailable = 0
    processed_trade_dates: set[str] = set()

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
        processed_trade_dates.add(day.isoformat())
        ordered_candles = sorted(candles, key=lambda candle: candle.timestamp)
        for trade in session_trades:
            first_touch, trace = validate_trade(
                trade,
                states=states,
                snapshots=snapshots,
                candles=ordered_candles,
                threshold=threshold,
                strong_threshold=strong_threshold,
                timeout_minutes=timeout_minutes,
            )
            if not trace:
                unavailable += 1
                continue
            if timeline_out is not None:
                timeline_out.extend(trace)
            confirmed, trade_attempts = ordered_gap_confirmation(trace, threshold)
            attempts.extend(trade_attempts)
            exit_price = float(trade["exit_price"])
            candidate_points = None
            candidate_price = None
            if confirmed is not None:
                candidate_price = float(confirmed["confirmation_close"])
                candidate_points = directional_points(
                    str(trade["direction"]), candidate_price, exit_price
                )
            first_touch_points = finite(
                first_touch.get("delayed_entry_to_canonical_exit_points")
            )
            results.append({
                **trade,
                "canonical_points": float(trade["captured_points"]),
                "canonical_reached_plus20": float(trade["mfe_points"]) >= 20.0,
                "first_touch_decision": first_touch["candidate_decision"],
                "first_touch_timestamp": first_touch["first_wma_075_timestamp"],
                "first_touch_points": first_touch_points,
                "candidate_decision": "ENTRY" if confirmed else "NO_ENTRY",
                "candidate_entry_timestamp": (
                    None if confirmed is None else confirmed["confirmation_timestamp"]
                ),
                "candidate_entry_price": candidate_price,
                "candidate_points": candidate_points,
                "candidate_delta_vs_canonical": (
                    None if candidate_points is None
                    else candidate_points - float(trade["captured_points"])
                ),
                "attempt_count": len(trade_attempts),
            })
    expected = selected_dates - processed_trade_dates
    if expected:
        raise ValueError(f"trade sessions not evaluated: {sorted(expected)}")
    return results, attempts, unavailable


def metrics(
    rows: Iterable[dict[str, Any]], top_thresholds: dict[str, float]
) -> dict[str, Any]:
    selected = list(rows)
    accepted = [row for row in selected if row["candidate_decision"] == "ENTRY"]
    denied = [row for row in selected if row["candidate_decision"] == "NO_ENTRY"]
    candidate_values = [float(row["candidate_points"]) for row in accepted]
    canonical_values = [float(row["canonical_points"]) for row in selected]
    denied_losses = [row for row in denied if float(row["canonical_points"]) < 0]
    denied_winners = [row for row in denied if float(row["canonical_points"]) > 0]
    plus20 = [row for row in selected if float(row["mfe_points"]) >= 20.0]
    top = [
        row for row in selected
        if float(row["mfe_points"]) >= top_thresholds[str(row["direction"])]
    ]
    denied_ids = {row["trade_id"] for row in denied}
    first_touch_values = [
        float(row["first_touch_points"])
        for row in selected if row["first_touch_points"] is not None
    ]
    return {
        "signals": len(selected),
        "canonical_total_points": sum(canonical_values),
        "canonical_mean_points": (
            sum(canonical_values) / len(canonical_values) if canonical_values else None
        ),
        "canonical_positive": sum(value > 0 for value in canonical_values),
        "canonical_negative": sum(value < 0 for value in canonical_values),
        "first_touch_entries": len(first_touch_values),
        "first_touch_total_points": sum(first_touch_values),
        "candidate_entries": len(accepted),
        "candidate_denied": len(denied),
        "candidate_total_points": sum(candidate_values),
        "candidate_mean_points": (
            sum(candidate_values) / len(candidate_values) if candidate_values else None
        ),
        "candidate_median_points": (
            median(candidate_values) if candidate_values else None
        ),
        "candidate_positive": sum(value > 0 for value in candidate_values),
        "candidate_negative": sum(value < 0 for value in candidate_values),
        "candidate_win_rate_pct": (
            100.0 * sum(value > 0 for value in candidate_values) / len(candidate_values)
            if candidate_values else None
        ),
        "delta_vs_canonical_sum": sum(candidate_values) - sum(canonical_values),
        "delta_vs_first_touch_sum": sum(candidate_values) - sum(first_touch_values),
        "denied_losing_trades": len(denied_losses),
        "points_saved_on_denied_losses": -sum(
            float(row["canonical_points"]) for row in denied_losses
        ),
        "denied_winning_trades": len(denied_winners),
        "points_lost_on_denied_winners": sum(
            float(row["canonical_points"]) for row in denied_winners
        ),
        "denied_canonical_net_points": sum(
            float(row["canonical_points"]) for row in denied
        ),
        "accepted_entry_delay_cost_vs_canonical": sum(
            float(row["candidate_points"]) - float(row["canonical_points"])
            for row in accepted
        ),
        "plus20_moves": len(plus20),
        "plus20_moves_destroyed": sum(row["trade_id"] in denied_ids for row in plus20),
        "plus20_moves_retained": sum(row["trade_id"] not in denied_ids for row in plus20),
        "top_decile_moves": len(top),
        "top_decile_moves_destroyed": sum(row["trade_id"] in denied_ids for row in top),
        "top_decile_moves_retained": sum(row["trade_id"] not in denied_ids for row in top),
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
    if args.threshold <= 0 or args.strong_threshold < args.threshold:
        raise SystemExit("STOP: invalid WMA thresholds")
    if args.timeout_minutes < 2:
        raise SystemExit("STOP: timeout must permit a later confirmation minute")

    trades, unavailable_input = read_trades(args.trades)
    session_summary = assign_evidence_blocks(
        trades, args.observed_forward_sessions
    )
    timeline: list[dict[str, Any]] = []
    results, attempts, unavailable_indicator = simulate(
        trades=trades,
        cache_root=args.cache_root,
        threshold=args.threshold,
        strong_threshold=args.strong_threshold,
        timeout_minutes=args.timeout_minutes,
        timeline_out=timeline,
    )
    development = [
        row for row in results
        if str(row["evidence_block"]).startswith("DEVELOPMENT_BLOCK_")
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
            block_rows = development
        elif block == "ALL_490":
            block_rows = results
        else:
            block_rows = [row for row in results if row["evidence_block"] == block]
        for direction in ("ALL", *DIRECTIONS):
            selected = (
                block_rows if direction == "ALL"
                else [row for row in block_rows if row["direction"] == direction]
            )
            if selected:
                headline.append({
                    "evidence_block": block,
                    "direction": direction,
                    **metrics(selected, top_thresholds),
                })

    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "trade-results.csv", results)
    write_csv(args.output_root / "confirmation-attempts.csv", attempts)
    write_csv(args.output_root / "candidate-timeline.csv", timeline)
    report = {
        "model": "HILEGA_ORDERED_WMA_GAP_490_V1",
        "sessions": session_summary,
        "input_trades": len(trades),
        "evaluated_trades": len(results),
        "unavailable_input_trades": unavailable_input,
        "unavailable_indicator_trades": unavailable_indicator,
        "development_top_decile_mfe_thresholds": top_thresholds,
        "rule": {
            "signal": "UNCHANGED_CANONICAL_HILEGA_DIRECTIONAL_SIGNAL",
            "arm": "DIRECTIONAL_WMA21_RSI9_CHANGE_GE_0_75",
            "confirmation": (
                "LATER_CONSECUTIVE_1M_CLOSE_WITH_WMA_STILL_GE_0_75_AND_"
                "POSITIVE_EXPANDING_DIRECTIONAL_EMA3_WMA21_GAP"
            ),
            "arming_candle_may_confirm": False,
            "failed_pair_may_rearm": True,
            "timeout_minutes": args.timeout_minutes,
            "candidate_fill": "ACTUAL_CONFIRMATION_1M_CLOSE",
            "exit": "UNCHANGED_CANONICAL_EXIT",
        },
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
            "The 480 historical and ten forward sessions are already-inspected evidence.",
            "No row in this report is a new untouched confirmation observation.",
            "Candidate denials are valued at zero points; accepted entries retain the canonical exit.",
            "Unavailable indicator trades are excluded, not silently classified as denials.",
        ],
    }
    (args.output_root / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    print("HILEGA ORDERED WMA + GAP — 490 SESSION BACKTEST")
    print("Sessions", session_summary)
    print(
        "Trades", len(results),
        "input unavailable", unavailable_input,
        "indicator unavailable", unavailable_indicator,
    )
    print("Development top-decile MFE", top_thresholds)
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
