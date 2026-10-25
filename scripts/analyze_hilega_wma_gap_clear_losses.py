#!/usr/bin/env python3
"""Explain accepted Hilega WMA-gap losses and audit same-candle ordering."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from collections import Counter, defaultdict
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
    percentile,
    read_trades,
    write_csv,
)
from scripts.research_hilega_wma_gap_confirmation_policies import (
    passed_pairs,
    select_current,
)
from scripts.validate_hilega_wma_delayed_confirmation import validate_trade


DEFAULT_CACHE = Path("data/historical-evidence/hilega-milega-underlying-cache-v1")
DEFAULT_TRADES = Path(
    "data/historical-evidence/hilega-alignment-points-490-v1/"
    "trade-alignment-points.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/"
    "hilega-wma-gap-clear-loss-diagnostics-490-v1"
)
CHECKPOINTS = (1, 3, 5)


def finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def floor_5m(value: datetime) -> datetime:
    local = value.astimezone(IST)
    return local.replace(
        minute=(local.minute // 5) * 5,
        second=0,
        microsecond=0,
    )


def directional_ema_delta(
    previous: dict[str, Any], current: dict[str, Any], direction: str
) -> float:
    before = float(previous["provisional_ema3_rsi"])
    after = float(current["provisional_ema3_rsi"])
    return after - before if direction == "BULLISH" else before - after


def row_features(
    row: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    candidate_entry_price: float,
) -> dict[str, Any]:
    direction = str(row["direction"])
    gap = directional_gap(row, direction)
    prior_gap = directional_gap(previous, direction) if previous else None
    return {
        "timestamp": row["minute_timestamp"],
        "price": float(row["observed_close"]),
        "points_from_candidate_entry": directional_points(
            direction,
            candidate_entry_price,
            float(row["observed_close"]),
        ),
        "wma_strength": float(row["directional_wma_change"]),
        "rsi9": finite(row.get("provisional_rsi9")),
        "ema3": finite(row.get("provisional_ema3_rsi")),
        "wma21": finite(row.get("provisional_wma21_rsi")),
        "directional_gap": gap,
        "gap_delta_1m": None if prior_gap is None else gap - prior_gap,
        "ema_directional_delta_1m": (
            None if previous is None
            else directional_ema_delta(previous, row, direction)
        ),
        "full_alignment": bool(row.get("full_directional_alignment")),
    }


def warning_reasons(features: dict[str, Any], threshold: float) -> list[str]:
    reasons: list[str] = []
    if float(features["wma_strength"]) < threshold:
        reasons.append("WMA_BELOW_0_75")
    if float(features["directional_gap"]) <= 0:
        reasons.append("GAP_NON_POSITIVE")
    gap_delta = finite(features.get("gap_delta_1m"))
    if gap_delta is not None and gap_delta < 0:
        reasons.append("GAP_CONTRACTING")
    ema_delta = finite(features.get("ema_directional_delta_1m"))
    if ema_delta is not None and ema_delta < 0:
        reasons.append("EMA_NOT_CONTINUING")
    if not bool(features.get("full_alignment")):
        reasons.append("RSI_EMA_WMA_NOT_ALIGNED")
    if float(features["points_from_candidate_entry"]) <= 0:
        reasons.append("NO_POSITIVE_PRICE_PROGRESS")
    return reasons


def checkpoint_row(
    trace: list[dict[str, Any]],
    entry_index: int,
    offset: int,
    candidate_entry_price: float,
) -> dict[str, Any] | None:
    entry_at = datetime.fromisoformat(str(trace[entry_index]["minute_timestamp"]))
    wanted = entry_at + timedelta(minutes=offset)
    for index in range(entry_index + 1, len(trace)):
        current_at = datetime.fromisoformat(str(trace[index]["minute_timestamp"]))
        if current_at == wanted:
            previous = trace[index - 1] if index else None
            return row_features(
                trace[index], previous,
                candidate_entry_price=candidate_entry_price,
            )
        if current_at > wanted:
            break
    return None


def add_checkpoint_fields(
    output: dict[str, Any], prefix: str, features: dict[str, Any] | None,
    threshold: float,
) -> None:
    fields = (
        "timestamp", "price", "points_from_candidate_entry", "wma_strength",
        "rsi9", "ema3", "wma21", "directional_gap", "gap_delta_1m",
        "ema_directional_delta_1m", "full_alignment",
    )
    for field in fields:
        output[f"{prefix}_{field}"] = None if features is None else features[field]
    output[f"{prefix}_warning_reasons"] = (
        "UNAVAILABLE"
        if features is None
        else "|".join(warning_reasons(features, threshold))
    )


def first_warning(
    trace: list[dict[str, Any]],
    entry_index: int,
    candidate_entry_price: float,
    threshold: float,
) -> tuple[str | None, str]:
    for index in range(entry_index + 1, len(trace)):
        previous = trace[index - 1]
        features = row_features(
            trace[index], previous,
            candidate_entry_price=candidate_entry_price,
        )
        reasons = warning_reasons(features, threshold)
        if reasons:
            return str(features["timestamp"]), "|".join(reasons)
    return None, "NO_WARNING_IN_OBSERVATION_WINDOW"


def exact_trace_index(trace: list[dict[str, Any]], timestamp: str) -> int:
    for index, row in enumerate(trace):
        if str(row["minute_timestamp"]) == timestamp:
            return index
    raise ValueError(f"confirmation minute missing from trace: {timestamp}")


def classify_same_candle_conflicts(
    row: dict[str, Any], all_trades: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    entry_value = row.get("candidate_entry_timestamp")
    entry_at = (
        datetime.fromisoformat(str(entry_value)).astimezone(IST)
        if entry_value else None
    )
    signal_at = datetime.fromisoformat(str(row["signal_timestamp"])).astimezone(IST)
    own_exit_label = datetime.fromisoformat(
        str(row["canonical_exit_timestamp"])
    ).astimezone(IST)
    own_exit_close = own_exit_label + timedelta(minutes=4)
    output: list[dict[str, Any]] = []

    def emit(kind: str, other: dict[str, Any], exit_label: datetime) -> None:
        output.append({
            "session_date": row["session_date"],
            "entry_trade_id": row["trade_id"],
            "entry_direction": row["direction"],
            "signal_timestamp": row["signal_timestamp"],
            "candidate_entry_timestamp": entry_value,
            "conflict_type": kind,
            "exit_trade_id": other["trade_id"],
            "exit_direction": other["direction"],
            "exit_label_timestamp": exit_label.isoformat(),
            "exit_completed_close_timestamp": (
                exit_label + timedelta(minutes=4)
            ).isoformat(),
            "same_trade": str(other["trade_id"]) == str(row["trade_id"]),
        })

    if entry_at is not None and entry_at == own_exit_close:
        emit("OWN_ENTRY_EQUALS_EXIT_COMPLETED_CLOSE", row, own_exit_label)
    if entry_at is not None and floor_5m(entry_at) == own_exit_label:
        emit("OWN_ENTRY_INSIDE_EXIT_5M_CANDLE", row, own_exit_label)

    for other in all_trades:
        if str(other["session_date"]) != str(row["session_date"]):
            continue
        if str(other["trade_id"]) == str(row["trade_id"]):
            continue
        exit_label = datetime.fromisoformat(
            str(other["exit_timestamp"])
        ).astimezone(IST)
        exit_close = exit_label + timedelta(minutes=4)
        if entry_at is not None and entry_at == exit_close:
            emit("ENTRY_EQUALS_OTHER_EXIT_COMPLETED_CLOSE", other, exit_label)
        if entry_at is not None and floor_5m(entry_at) == exit_label:
            emit("ENTRY_INSIDE_OTHER_EXIT_5M_CANDLE", other, exit_label)
        if signal_at == exit_label:
            emit("SIGNAL_EQUALS_OTHER_EXIT_LABEL", other, exit_label)
    return output


def quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def parameter_comparison(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    features = (
        "entry_wma_strength", "entry_directional_gap", "entry_gap_delta_1m",
        "entry_ema_directional_delta_1m", "entry_rsi9", "entry_ema3",
        "entry_wma21",
        *tuple(
            f"t{offset}_{field}"
            for offset in CHECKPOINTS
            for field in (
                "points_from_candidate_entry", "wma_strength",
                "directional_gap", "gap_delta_1m",
                "ema_directional_delta_1m",
            )
        ),
    )
    output: list[dict[str, Any]] = []
    blocks = ("DEVELOPMENT_ALL", "OBSERVED_FORWARD", "ALL_490")
    for block in blocks:
        for direction in DIRECTIONS:
            selected = [row for row in rows if row["direction"] == direction]
            if block == "DEVELOPMENT_ALL":
                selected = [
                    row for row in selected
                    if str(row["evidence_block"]).startswith("DEVELOPMENT_BLOCK_")
                ]
            elif block == "OBSERVED_FORWARD":
                selected = [
                    row for row in selected
                    if row["evidence_block"] == "OBSERVED_FORWARD"
                ]
            for cohort, predicate in (
                ("ACCEPTED_WINNER", lambda item: float(item["candidate_points"]) > 0),
                ("ACCEPTED_LOSER", lambda item: float(item["candidate_points"]) < 0),
            ):
                cohort_rows = [row for row in selected if predicate(row)]
                for feature in features:
                    values = [
                        value for value in (
                            finite(row.get(feature)) for row in cohort_rows
                        ) if value is not None
                    ]
                    output.append({
                        "evidence_block": block,
                        "direction": direction,
                        "cohort": cohort,
                        "feature": feature,
                        "trades": len(cohort_rows),
                        "available": len(values),
                        "mean": sum(values) / len(values) if values else None,
                        "median": median(values) if values else None,
                        "q25": quantile(values, 0.25),
                        "q75": quantile(values, 0.75),
                    })
    return output


def summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    selected = list(rows)
    accepted = [row for row in selected if row["decision"] == "ENTRY"]
    denied = [row for row in selected if row["decision"] == "NO_ENTRY"]
    winners = [row for row in accepted if float(row["candidate_points"]) > 0]
    losers = [row for row in accepted if float(row["candidate_points"]) < 0]
    return {
        "signals": len(selected),
        "accepted": len(accepted),
        "denied": len(denied),
        "accepted_winners": len(winners),
        "accepted_losers": len(losers),
        "accepted_winner_points": sum(float(row["candidate_points"]) for row in winners),
        "accepted_loss_points": sum(float(row["candidate_points"]) for row in losers),
        "candidate_net_points": sum(float(row["candidate_points"]) for row in accepted),
        "denied_canonical_winners": sum(
            float(row["canonical_points"]) > 0 for row in denied
        ),
        "denied_canonical_losses": sum(
            float(row["canonical_points"]) < 0 for row in denied
        ),
    }


def simulate(
    *,
    trades: list[dict[str, Any]],
    cache_root: Path,
    threshold: float,
    strong_threshold: float,
    timeout_minutes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade["session_date"])].append(trade)
    selected_dates = set(grouped)
    last_day = max(date.fromisoformat(day) for day in selected_dates)
    engine = HilegaMilegaIndicatorEngineV1()
    results: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
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
            # Five additional minutes are diagnostic only.  Entry selection is
            # restricted below to the declared T+10 confirmation window.
            _, full_trace = validate_trade(
                trade,
                states=states,
                snapshots=snapshots,
                candles=ordered_candles,
                threshold=threshold,
                strong_threshold=strong_threshold,
                timeout_minutes=timeout_minutes + max(CHECKPOINTS),
            )
            selection_trace = [
                row for row in full_trace
                if int(row["minutes_observed"]) <= timeout_minutes
            ]
            selected = select_current(passed_pairs(selection_trace, threshold))
            canonical = float(trade["captured_points"])
            base: dict[str, Any] = {
                "session_date": trade["session_date"],
                "evidence_block": trade["evidence_block"],
                "trade_id": trade["trade_id"],
                "direction": trade["direction"],
                "route": trade["route"],
                "signal_timestamp": trade["entry_timestamp"],
                "signal_actionable_timestamp": (
                    datetime.fromisoformat(str(trade["entry_timestamp"]))
                    + timedelta(minutes=5)
                ).isoformat(),
                "canonical_entry_price": float(trade["entry_price"]),
                "canonical_exit_timestamp": trade["exit_timestamp"],
                "canonical_exit_completed_close_timestamp": (
                    datetime.fromisoformat(str(trade["exit_timestamp"]))
                    + timedelta(minutes=4)
                ).isoformat(),
                "canonical_exit_price": float(trade["exit_price"]),
                "canonical_points": canonical,
                "canonical_mfe_points": float(trade["mfe_points"]),
                "canonical_mae_points": float(trade["mae_points"]),
                "decision": "ENTRY" if selected else "NO_ENTRY",
                "candidate_entry_timestamp": None,
                "candidate_entry_price": None,
                "candidate_points": None,
                "candidate_outcome": "DENIED",
                "entry_sequence": (
                    "CANONICAL_SIGNAL->WMA_GE_0_75->"
                    "LATER_POSITIVE_EXPANDING_GAP"
                ),
            }
            if selected is None:
                results.append(base)
                conflicts.extend(classify_same_candle_conflicts(base, trades))
                continue

            entry_timestamp = str(selected["confirmation_timestamp"])
            entry_price = float(selected["confirmation_price"])
            entry_index = exact_trace_index(full_trace, entry_timestamp)
            previous = full_trace[entry_index - 1] if entry_index else None
            entry_features = row_features(
                full_trace[entry_index], previous,
                candidate_entry_price=entry_price,
            )
            candidate_points = directional_points(
                str(trade["direction"]), entry_price, float(trade["exit_price"])
            )
            base.update({
                "candidate_entry_timestamp": entry_timestamp,
                "candidate_entry_price": entry_price,
                "candidate_points": candidate_points,
                "candidate_outcome": (
                    "WIN" if candidate_points > 0
                    else "LOSS" if candidate_points < 0 else "ZERO"
                ),
                "actionable_to_entry_minutes": selected[
                    "actionable_latency_minutes"
                ],
                **{f"entry_{key}": value for key, value in entry_features.items()},
            })
            warning_at, warning = first_warning(
                full_trace, entry_index, entry_price, threshold
            )
            base["first_post_entry_warning_timestamp"] = warning_at
            base["first_post_entry_warning_reasons"] = warning
            for offset in CHECKPOINTS:
                features = checkpoint_row(
                    full_trace, entry_index, offset, entry_price
                )
                add_checkpoint_fields(base, f"t{offset}", features, threshold)
            results.append(base)
            conflicts.extend(classify_same_candle_conflicts(base, trades))

    missing = selected_dates - processed
    if missing:
        raise ValueError(f"trade sessions not evaluated: {sorted(missing)}")
    return results, conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--trades", type=Path, default=DEFAULT_TRADES)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument("--strong-threshold", type=float, default=1.0)
    parser.add_argument("--timeout-minutes", type=int, default=10)
    parser.add_argument("--observed-forward-sessions", type=int, default=10)
    parser.add_argument("--worst-trades", type=int, default=20)
    args = parser.parse_args()
    if args.threshold <= 0 or args.strong_threshold < args.threshold:
        raise SystemExit("STOP: invalid WMA thresholds")

    trades, unavailable = read_trades(args.trades)
    sessions = assign_evidence_blocks(trades, args.observed_forward_sessions)
    rows, conflicts = simulate(
        trades=trades,
        cache_root=args.cache_root,
        threshold=args.threshold,
        strong_threshold=args.strong_threshold,
        timeout_minutes=args.timeout_minutes,
    )
    accepted = [row for row in rows if row["decision"] == "ENTRY"]
    losses = [
        row for row in accepted if float(row["candidate_points"]) < 0
    ]
    winners = [
        row for row in accepted if float(row["candidate_points"]) > 0
    ]
    comparisons = parameter_comparison(accepted)
    warning_counts = Counter(
        (row["evidence_block"], row["direction"], row["candidate_outcome"],
         row.get("first_post_entry_warning_reasons"))
        for row in accepted
    )
    warning_summary = [
        {
            "evidence_block": key[0],
            "direction": key[1],
            "candidate_outcome": key[2],
            "first_warning_reasons": key[3],
            "trades": count,
        }
        for key, count in sorted(warning_counts.items(), key=lambda item: str(item[0]))
    ]

    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "clear-trade-view.csv", rows)
    write_csv(
        args.output_root / "accepted-losses-clear.csv",
        sorted(losses, key=lambda row: float(row["candidate_points"])),
    )
    write_csv(
        args.output_root / "accepted-winners-clear.csv",
        sorted(winners, key=lambda row: float(row["candidate_points"]), reverse=True),
    )
    write_csv(args.output_root / "parameter-comparison.csv", comparisons)
    write_csv(args.output_root / "same-candle-audit.csv", conflicts)
    write_csv(args.output_root / "first-warning-summary.csv", warning_summary)

    direction_summary = {
        direction: summary([row for row in rows if row["direction"] == direction])
        for direction in DIRECTIONS
    }
    conflict_counts = Counter(row["conflict_type"] for row in conflicts)
    development_losses = [
        row for row in losses
        if str(row["evidence_block"]).startswith("DEVELOPMENT_BLOCK_")
    ]
    report = {
        "model": "HILEGA_WMA_GAP_CLEAR_LOSS_DIAGNOSTIC_V1",
        "sessions": sessions,
        "input_unavailable": unavailable,
        "rule_under_diagnosis": (
            "CANONICAL_SIGNAL_THEN_DIRECTIONAL_WMA_GE_0_75_THEN_"
            "LATER_POSITIVE_EXPANDING_DIRECTIONAL_EMA_WMA_GAP"
        ),
        "direction_summary": direction_summary,
        "development_accepted_losses": len(development_losses),
        "same_candle_conflicts": dict(sorted(conflict_counts.items())),
        "same_candle_interpretation": {
            "exact_exit_close": (
                "Entry and completed exit share the exact one-minute timestamp; "
                "this must be zero for causal ordering."
            ),
            "same_exit_5m_candle": (
                "Entry occurs somewhere inside a five-minute candle carrying an "
                "exit label. Review separately; exact intrabar order matters."
            ),
        },
        "interpretation": [
            "An accepted loss passed the same WMA and gap sequence as an accepted winner.",
            "T+1/T+3/T+5 observations diagnose deterioration; they are not exit rules.",
            "Parameter comparison is descriptive and must not be optimized on observed forward rows.",
            "All 490 sessions are inspected evidence; new future sessions are required for confirmation.",
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
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    print("HILEGA WMA-GAP CLEAR LOSS DIAGNOSTIC")
    print("Sessions", sessions)
    for direction, values in direction_summary.items():
        print(direction, values)
    print("SAME-CANDLE AUDIT", dict(sorted(conflict_counts.items())))
    print("WORST ACCEPTED LOSSES")
    for row in sorted(
        development_losses,
        key=lambda item: float(item["candidate_points"]),
    )[:args.worst_trades]:
        print({
            "date": row["session_date"],
            "direction": row["direction"],
            "signal": row["signal_timestamp"],
            "entry": row["candidate_entry_timestamp"],
            "exit_label": row["canonical_exit_timestamp"],
            "exit_close": row["canonical_exit_completed_close_timestamp"],
            "points": round(float(row["candidate_points"]), 2),
            "entry_wma": round(float(row["entry_wma_strength"]), 4),
            "entry_gap": round(float(row["entry_directional_gap"]), 4),
            "entry_gap_delta": round(float(row["entry_gap_delta_1m"]), 4),
            "first_warning": row["first_post_entry_warning_reasons"],
            "t1_points": finite(row.get("t1_points_from_candidate_entry")),
            "t3_points": finite(row.get("t3_points_from_candidate_entry")),
            "t5_points": finite(row.get("t5_points_from_candidate_entry")),
        })
    print("Output:", args.output_root / "report.json")
    print("Read only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
