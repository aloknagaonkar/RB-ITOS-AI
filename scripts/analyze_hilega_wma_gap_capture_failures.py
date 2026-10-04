#!/usr/bin/env python3
"""Measure actual candidate capture, giveback and accepted-loss types."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from market_lab.domain import IST
from market_lab.hilega_milega_historical_replay_v1 import UNDERLYING, _read_cache
from scripts.backtest_hilega_wma_gap_490 import cache_sessions, write_csv


DEFAULT_CLEAR = Path(
    "data/historical-evidence/"
    "hilega-wma-gap-clear-loss-diagnostics-490-v1/clear-trade-view.csv"
)
DEFAULT_CACHE = Path("data/historical-evidence/hilega-milega-underlying-cache-v1")
DEFAULT_TRADES = Path(
    "data/historical-evidence/hilega-alignment-points-490-v1/"
    "trade-alignment-points.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-wma-gap-capture-failures-490-v1"
)
DIRECTIONS = ("BULLISH", "BEARISH")
SIGNAL_FEATURES = (
    "entry_rsi9", "entry_ema3_rsi", "entry_wma21_rsi",
    "entry_ema_minus_wma", "entry_rsi9_slope_3",
    "entry_ema3_rsi_slope_3", "entry_wma21_rsi_slope_3",
    "entry_ema_minus_wma_slope_3",
)


def finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    return rows


def directional_points(direction: str, entry: float, mark: float) -> float:
    if direction == "BULLISH":
        return mark - entry
    if direction == "BEARISH":
        return entry - mark
    raise ValueError(f"unsupported direction: {direction!r}")


def percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot calculate percentile of empty values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def signal_period(timestamp: str) -> str:
    local = datetime.fromisoformat(timestamp).astimezone(IST).time()
    if local < time(10, 30):
        return "OPEN_0915_1029"
    if local < time(13, 0):
        return "MIDDAY_1030_1259"
    return "AFTERNOON_1300_1515"


def lifecycle_excursion(
    direction: str,
    entry_price: float,
    minute_rows: list[tuple[datetime, float]],
    exit_price: float,
) -> dict[str, Any]:
    values = [directional_points(direction, entry_price, close) for _, close in minute_rows]
    captured = directional_points(direction, entry_price, exit_price)
    # The canonical valuation is authoritative even if a revised broker cache
    # differs slightly on the final minute.
    values.append(captured)
    mfe = max(0.0, max(values))
    mae = min(0.0, min(values))
    giveback_from_mfe = mfe - captured
    return {
        "candidate_mfe_close_points": mfe,
        "candidate_mae_close_points": mae,
        "captured_points": captured,
        "giveback_from_mfe_points": giveback_from_mfe,
        "winner_capture_ratio_pct": (
            100.0 * captured / mfe if captured > 0 and mfe > 0 else None
        ),
        "winner_giveback_ratio_pct": (
            100.0 * giveback_from_mfe / mfe if captured > 0 and mfe > 0 else None
        ),
        "reached_plus20_after_candidate_entry": mfe >= 20.0,
    }


def own_same_exit_candle(row: dict[str, Any]) -> bool:
    if row.get("decision") != "ENTRY" or not row.get("candidate_entry_timestamp"):
        return False
    entry = datetime.fromisoformat(str(row["candidate_entry_timestamp"])).astimezone(IST)
    exit_label = datetime.fromisoformat(str(row["canonical_exit_timestamp"])).astimezone(IST)
    entry_label = entry.replace(
        minute=(entry.minute // 5) * 5, second=0, microsecond=0
    )
    return entry_label == exit_label


def classify_loss(row: dict[str, Any]) -> str:
    if float(row["captured_points"]) >= 0:
        return "NOT_A_LOSS"
    if truthy(row.get("own_same_exit_5m_candle")):
        return "SAME_EXIT_5M_CANDLE"
    t1 = finite(row.get("t1_points_from_candidate_entry"))
    t3 = finite(row.get("t3_points_from_candidate_entry"))
    t5 = finite(row.get("t5_points_from_candidate_entry"))
    observed = [value for value in (t1, t3, t5) if value is not None]
    if t5 is not None and t5 > 0:
        return "LATE_GIVEBACK_AFTER_T5"
    if t5 is not None and t5 <= 0 and any(
        value is not None and value > 0 for value in (t1, t3)
    ):
        return "EARLY_REVERSAL_BY_T5"
    if len(observed) == 3 and all(value <= 0 for value in observed):
        return "IMMEDIATE_FAILURE_THROUGH_T5"
    if t5 is not None and t5 <= 0 and float(row["candidate_mfe_close_points"]) > 0:
        return "RECOVERED_AFTER_T5_THEN_LOST"
    return "OTHER_ACCEPTED_LOSS"


def first_opposite_signal(
    row: dict[str, Any], session_rows: list[dict[str, Any]]
) -> tuple[str | None, float | None]:
    if row.get("decision") != "ENTRY":
        return None, None
    entry = datetime.fromisoformat(str(row["candidate_entry_timestamp"]))
    exit_close = datetime.fromisoformat(
        str(row["canonical_exit_completed_close_timestamp"])
    )
    candidates: list[datetime] = []
    for other in session_rows:
        if other["direction"] == row["direction"]:
            continue
        signal = datetime.fromisoformat(str(other["signal_timestamp"]))
        actionable = signal + timedelta(minutes=5)
        if entry < actionable <= exit_close:
            candidates.append(actionable)
    if not candidates:
        return None, None
    first = min(candidates)
    return first.isoformat(), (first - entry).total_seconds() / 60.0


def maximum_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def metrics(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    selected = list(rows)
    values = [float(row["captured_points"]) for row in selected]
    winners = [row for row in selected if float(row["captured_points"]) > 0]
    losers = [row for row in selected if float(row["captured_points"]) < 0]
    gross_wins = sum(float(row["captured_points"]) for row in winners)
    gross_losses = -sum(float(row["captured_points"]) for row in losers)
    winner_mfe = sum(float(row["candidate_mfe_close_points"]) for row in winners)
    winner_giveback = sum(float(row["giveback_from_mfe_points"]) for row in winners)
    return {
        "trades": len(selected),
        "winners": len(winners),
        "losers": len(losers),
        "gross_winning_points": gross_wins,
        "gross_losing_points": gross_losses,
        "net_points": sum(values),
        "profit_factor": gross_wins / gross_losses if gross_losses else None,
        "max_drawdown_points": maximum_drawdown(values),
        "winner_candidate_mfe_points": winner_mfe,
        "winner_captured_points": gross_wins,
        "winner_giveback_points": winner_giveback,
        "weighted_winner_capture_pct": (
            100.0 * gross_wins / winner_mfe if winner_mfe else None
        ),
        "weighted_winner_giveback_pct": (
            100.0 * winner_giveback / winner_mfe if winner_mfe else None
        ),
        "mean_winner_capture_pct": (
            sum(float(row["winner_capture_ratio_pct"]) for row in winners) / len(winners)
            if winners else None
        ),
        "median_winner_capture_pct": (
            median(float(row["winner_capture_ratio_pct"]) for row in winners)
            if winners else None
        ),
        "losers_that_reached_plus20": sum(
            float(row["candidate_mfe_close_points"]) >= 20 for row in losers
        ),
        "loss_points_after_reaching_plus20": -sum(
            float(row["captured_points"]) for row in losers
            if float(row["candidate_mfe_close_points"]) >= 20
        ),
    }


def group_summary(
    rows: list[dict[str, Any]], group_fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    grouped: defaultdict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row[field] for field in group_fields)].append(row)
    return [
        {**dict(zip(group_fields, key)), **metrics(grouped[key])}
        for key in sorted(grouped, key=lambda value: tuple(str(item) for item in value))
    ]


def minute_cache(
    cache_root: Path, selected_dates: set[str]
) -> dict[str, list[tuple[datetime, float]]]:
    last = max(date.fromisoformat(day) for day in selected_dates)
    result: dict[str, list[tuple[datetime, float]]] = {}
    for day, path in cache_sessions(cache_root, last):
        key = day.isoformat()
        if key not in selected_dates:
            continue
        candles = _read_cache(path, UNDERLYING, day)
        result[key] = sorted(
            [
                (candle.timestamp.astimezone(IST).replace(second=0, microsecond=0),
                 float(candle.close))
                for candle in candles
            ],
            key=lambda item: item[0],
        )
    missing = selected_dates - set(result)
    if missing:
        raise ValueError(f"minute cache unavailable: {sorted(missing)}")
    return result


def enrich(
    clear_rows: list[dict[str, str]],
    original_rows: list[dict[str, str]],
    caches: dict[str, list[tuple[datetime, float]]],
) -> list[dict[str, Any]]:
    originals = {row["trade_id"]: row for row in original_rows}
    by_session: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in clear_rows:
        by_session[row["session_date"]].append(row)
    output: list[dict[str, Any]] = []
    for raw in clear_rows:
        if raw["decision"] != "ENTRY":
            continue
        row: dict[str, Any] = dict(raw)
        day = row["session_date"]
        direction = row["direction"]
        entry_at = datetime.fromisoformat(row["candidate_entry_timestamp"]).astimezone(IST)
        exit_at = datetime.fromisoformat(
            row["canonical_exit_completed_close_timestamp"]
        ).astimezone(IST)
        entry_price = float(row["candidate_entry_price"])
        exit_price = float(row["canonical_exit_price"])
        window = [
            item for item in caches[day]
            if entry_at <= item[0] <= exit_at
        ]
        row.update(lifecycle_excursion(
            direction, entry_price, window, exit_price
        ))
        row["signal_period"] = signal_period(row["signal_timestamp"])
        row["own_same_exit_5m_candle"] = own_same_exit_candle(row)
        opposite_at, opposite_minutes = first_opposite_signal(
            row, by_session[day]
        )
        row["first_opposite_signal_actionable_timestamp"] = opposite_at
        row["minutes_to_first_opposite_signal"] = opposite_minutes
        row["opposite_signal_within_5m"] = (
            opposite_minutes is not None and opposite_minutes <= 5
        )
        row["opposite_signal_within_10m"] = (
            opposite_minutes is not None and opposite_minutes <= 10
        )
        original = originals.get(row["trade_id"], {})
        for field in SIGNAL_FEATURES:
            row[f"signal_{field}"] = finite(original.get(field))
        row["failure_group"] = classify_loss(row)
        output.append(row)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clear-trades", type=Path, default=DEFAULT_CLEAR)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--original-trades", type=Path, default=DEFAULT_TRADES)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    clear_rows = read_csv(args.clear_trades)
    original_rows = read_csv(args.original_trades)
    selected_dates = {row["session_date"] for row in clear_rows}
    rows = enrich(
        clear_rows, original_rows, minute_cache(args.cache_root, selected_dates)
    )
    development = [
        row for row in rows
        if str(row["evidence_block"]).startswith("DEVELOPMENT_BLOCK_")
    ]
    top_thresholds = {
        direction: percentile([
            float(row["candidate_mfe_close_points"])
            for row in development if row["direction"] == direction
        ], 0.90)
        for direction in DIRECTIONS
    }
    for row in rows:
        row["candidate_top_decile_move"] = (
            float(row["candidate_mfe_close_points"])
            >= top_thresholds[row["direction"]]
        )

    blocks: list[dict[str, Any]] = []
    for block in (
        "DEVELOPMENT_ALL", "DEVELOPMENT_BLOCK_1", "DEVELOPMENT_BLOCK_2",
        "DEVELOPMENT_BLOCK_3", "OBSERVED_FORWARD", "ALL_490",
    ):
        if block == "DEVELOPMENT_ALL":
            selected = development
        elif block == "ALL_490":
            selected = rows
        else:
            selected = [row for row in rows if row["evidence_block"] == block]
        for direction in ("ALL", *DIRECTIONS):
            subset = (
                selected if direction == "ALL"
                else [row for row in selected if row["direction"] == direction]
            )
            if subset:
                blocks.append({
                    "evidence_block": block,
                    "direction": direction,
                    **metrics(subset),
                })

    winner_summary = group_summary(
        [row for row in rows if float(row["captured_points"]) > 0],
        ("evidence_block", "direction"),
    )
    loss_summary = group_summary(
        [row for row in rows if float(row["captured_points"]) < 0],
        ("evidence_block", "direction", "failure_group"),
    )
    same_exit_summary = group_summary(
        [row for row in rows if truthy(row["own_same_exit_5m_candle"])],
        ("evidence_block", "direction"),
    )
    opposite_summary = group_summary(
        rows,
        ("evidence_block", "direction", "opposite_signal_within_10m"),
    )

    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "capture-trade-view.csv", rows)
    write_csv(args.output_root / "winner-capture-summary.csv", winner_summary)
    write_csv(args.output_root / "loss-classification-summary.csv", loss_summary)
    write_csv(
        args.output_root / "failure-group-trades.csv",
        [row for row in rows if row["failure_group"] != "NOT_A_LOSS"],
    )
    write_csv(args.output_root / "same-exit-candle-summary.csv", same_exit_summary)
    write_csv(args.output_root / "opposite-signal-summary.csv", opposite_summary)
    write_csv(args.output_root / "headline.csv", blocks)

    all_summary = next(
        row for row in blocks
        if row["evidence_block"] == "ALL_490" and row["direction"] == "ALL"
    )
    report = {
        "model": "HILEGA_WMA_GAP_CAPTURE_FAILURE_ANALYSIS_V1",
        "sessions": len(selected_dates),
        "accepted_trades": len(rows),
        "candidate_top_decile_mfe_thresholds": top_thresholds,
        "all_490": all_summary,
        "headline": blocks,
        "failure_groups": sorted({row["failure_group"] for row in rows}),
        "mfe_mae_basis": "COMPLETED_ONE_MINUTE_CLOSES_AFTER_CANDIDATE_ENTRY",
        "interpretation": [
            "Winner capture/giveback uses candidate-entry MFE, not canonical-entry MFE.",
            "Gross losing points are not winner giveback and are reported separately.",
            "Loss groups are descriptive; none becomes a live rule in this run.",
            "All 490 sessions are inspected evidence; future sessions remain necessary.",
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

    print("HILEGA WMA-GAP CAPTURE AND FAILURE ANALYSIS")
    print("Candidate MFE thresholds", top_thresholds)
    print("HEADLINE")
    for row in blocks:
        if row["evidence_block"] in {"DEVELOPMENT_ALL", "OBSERVED_FORWARD", "ALL_490"}:
            print(row)
    print("LOSS GROUPS")
    for row in loss_summary:
        print(row)
    print("SAME EXIT 5M CANDLE")
    for row in same_exit_summary:
        print(row)
    print("Output:", args.output_root / "report.json")
    print("Read only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
