#!/usr/bin/env python3
"""Test RSI14 warning plus structural confirmation exits for Hilega."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.research_hilega_post_proof_mfe_exits import (
    CONTROL, DIRECTIONS, directional_points, evidence_sets, load_timelines,
    metrics, percentile, read_rows, trade_timeline, write_csv,
)
from scripts.research_hilega_rsi14_extreme_exits import (
    completed_five_minute_closes, fixed_control_winner_metrics, pine_rsi,
)


DEFAULT_INPUT = Path(
    "data/historical-evidence/hilega-wma-gap-capture-failures-490-v1/"
    "capture-trade-view.csv"
)
DEFAULT_CACHE = Path("data/historical-evidence/hilega-milega-underlying-cache-v1")
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-rsi14-structural-confirmation-490-v1"
)
TWO_OF_THREE = "RSI14_WARNING_2_OF_3_AFTER_PLUS20_5M"
THREE_OF_THREE = "RSI14_WARNING_3_OF_3_AFTER_PLUS20_5M"
POLICIES = (CONTROL, TWO_OF_THREE, THREE_OF_THREE)


def ema(values: list[float | None], length: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    alpha = 2.0 / (length + 1.0)
    previous: float | None = None
    for index, value in enumerate(values):
        if value is None:
            continue
        previous = value if previous is None else alpha * value + (1.0 - alpha) * previous
        result[index] = previous
    return result


def wma(values: list[float | None], length: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    weights = list(range(1, length + 1))
    denominator = sum(weights)
    for index in range(length - 1, len(values)):
        window = values[index - length + 1:index + 1]
        if any(value is None for value in window):
            continue
        result[index] = sum(
            float(value) * weight for value, weight in zip(window, weights)
        ) / denominator
    return result


def indicator_index(
    timelines: dict[str, list[tuple[datetime, float]]],
) -> dict[datetime, dict[str, float]]:
    closes = completed_five_minute_closes(timelines)
    close_values = [close for _, close in closes]
    rsi9 = pine_rsi(close_values, 9)
    rsi14 = pine_rsi(close_values, 14)
    ema3 = ema(rsi9, 3)
    wma21 = wma(rsi9, 21)
    result: dict[datetime, dict[str, float]] = {}
    previous_wma: float | None = None
    for (timestamp, _), r9, r14, e3, w21 in zip(closes, rsi9, rsi14, ema3, wma21):
        if r9 is None or r14 is None or e3 is None or w21 is None:
            if w21 is not None:
                previous_wma = float(w21)
            continue
        slope = None if previous_wma is None else float(w21) - previous_wma
        previous_wma = float(w21)
        if slope is None:
            continue
        result[timestamp] = {
            "rsi9": float(r9), "rsi14": float(r14),
            "ema3": float(e3), "wma21": float(w21),
            "gap": float(e3) - float(w21), "wma_slope": slope,
        }
    return result


def directional(value: float, direction: str) -> float:
    return value if direction == "BULLISH" else -value


def extreme(direction: str, rsi14: float) -> bool:
    return rsi14 >= 70.0 if direction == "BULLISH" else rsi14 <= 30.0


def outside_extreme(direction: str, rsi14: float) -> bool:
    return rsi14 < 70.0 if direction == "BULLISH" else rsi14 > 30.0


def simulate_structural_exit(
    *,
    timeline: list[tuple[datetime, float]],
    indicators: dict[datetime, dict[str, float]],
    direction: str,
    entry_price: float,
    control_exit_at: datetime,
    control_points: float,
    minimum_components: int,
    proof_points: float = 20.0,
) -> dict[str, Any]:
    running_mfe = 0.0
    proof_at: datetime | None = None
    armed_at: datetime | None = None
    warning_at: datetime | None = None
    warning: dict[str, float] | None = None
    warning_count = 0
    cancellation_count = 0
    for timestamp, close in timeline:
        if timestamp <= timeline[0][0] or timestamp >= control_exit_at:
            continue
        points = directional_points(direction, entry_price, close)
        running_mfe = max(running_mfe, points)
        if proof_at is None and running_mfe >= proof_points:
            proof_at = timestamp
        values = indicators.get(timestamp)
        if values is None or proof_at is None:
            continue
        rsi14 = values["rsi14"]
        directional_gap = directional(values["gap"], direction)
        directional_wma_slope = directional(values["wma_slope"], direction)
        if armed_at is None:
            if extreme(direction, rsi14):
                armed_at = timestamp
            continue
        if warning_at is None:
            if outside_extreme(direction, rsi14):
                warning_at = timestamp
                warning_count += 1
                warning = {
                    "rsi14": rsi14,
                    "directional_gap": directional_gap,
                    "directional_wma_slope": directional_wma_slope,
                }
            continue

        assert warning is not None
        if extreme(direction, rsi14):
            cancellation_count += 1
            warning_at = None
            warning = None
            continue
        if directional_gap > warning["directional_gap"]:
            cancellation_count += 1
            armed_at = None
            warning_at = None
            warning = None
            continue

        rsi_continues_adverse = (
            rsi14 < warning["rsi14"] if direction == "BULLISH"
            else rsi14 > warning["rsi14"]
        )
        gap_contracts = directional_gap < warning["directional_gap"]
        wma_weakens = directional_wma_slope < warning["directional_wma_slope"]
        component_count = sum((rsi_continues_adverse, gap_contracts, wma_weakens))
        if component_count >= minimum_components:
            return {
                "candidate_exit": True,
                "proof_timestamp": proof_at.isoformat(),
                "armed_timestamp": armed_at.isoformat(),
                "warning_timestamp": warning_at.isoformat(),
                "exit_timestamp": timestamp.isoformat(),
                "exit_price": close,
                "exit_points": points,
                "exit_rsi14": rsi14,
                "mfe_at_exit": running_mfe,
                "rsi_continues_adverse": rsi_continues_adverse,
                "gap_contracts": gap_contracts,
                "wma_weakens": wma_weakens,
                "component_count": component_count,
                "warning_count": warning_count,
                "cancellation_count": cancellation_count,
            }
        cancellation_count += 1
        armed_at = None
        warning_at = None
        warning = None

    return {
        "candidate_exit": False,
        "proof_timestamp": proof_at.isoformat() if proof_at else None,
        "armed_timestamp": armed_at.isoformat() if armed_at else None,
        "warning_timestamp": warning_at.isoformat() if warning_at else None,
        "exit_timestamp": control_exit_at.isoformat(),
        "exit_price": None,
        "exit_points": control_points,
        "exit_rsi14": None,
        "mfe_at_exit": running_mfe,
        "rsi_continues_adverse": None,
        "gap_contracts": None,
        "wma_weakens": None,
        "component_count": None,
        "warning_count": warning_count,
        "cancellation_count": cancellation_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proof-points", type=float, default=20.0)
    args = parser.parse_args()

    source = read_rows(args.input)
    timelines = load_timelines(source, args.cache_root)
    indicators = indicator_index(timelines)
    development = [
        row for row in source
        if str(row["evidence_block"]).startswith("DEVELOPMENT_BLOCK_")
    ]
    top_thresholds = {
        direction: percentile([
            float(row["candidate_mfe_close_points"])
            for row in development if row["direction"] == direction
        ], 0.90)
        for direction in DIRECTIONS
    }

    results: list[dict[str, Any]] = []
    for raw in source:
        base = {
            "trade_id": raw["trade_id"], "session_date": raw["session_date"],
            "evidence_block": raw["evidence_block"], "direction": raw["direction"],
            "signal_timestamp": raw.get("signal_timestamp"),
            "candidate_entry_timestamp": raw["candidate_entry_timestamp"],
            "candidate_entry_price": float(raw["candidate_entry_price"]),
            "control_exit_timestamp": raw["canonical_exit_completed_close_timestamp"],
            "control_exit_price": float(raw["canonical_exit_price"]),
            "control_points": float(raw["captured_points"]),
            "control_mfe_points": float(raw["candidate_mfe_close_points"]),
            "control_top_decile_move": (
                float(raw["candidate_mfe_close_points"]) >= top_thresholds[raw["direction"]]
            ),
        }
        timeline = trade_timeline(raw, timelines[raw["session_date"]])
        results.append({
            **base, "policy": CONTROL, "candidate_exit": False,
            "policy_exit_timestamp": base["control_exit_timestamp"],
            "policy_exit_price": base["control_exit_price"],
            "policy_points": base["control_points"], "delta_vs_control": 0.0,
            "mfe_at_exit": base["control_mfe_points"],
            "top_decile_reached_before_exit": base["control_top_decile_move"],
        })
        for policy, minimum in ((TWO_OF_THREE, 2), (THREE_OF_THREE, 3)):
            simulation = simulate_structural_exit(
                timeline=timeline, indicators=indicators,
                direction=base["direction"], entry_price=base["candidate_entry_price"],
                control_exit_at=datetime.fromisoformat(base["control_exit_timestamp"]),
                control_points=base["control_points"], minimum_components=minimum,
                proof_points=args.proof_points,
            )
            results.append({
                **base, "policy": policy, "minimum_components": minimum,
                **simulation,
                "policy_exit_timestamp": simulation["exit_timestamp"],
                "policy_exit_price": simulation["exit_price"],
                "policy_points": simulation["exit_points"],
                "delta_vs_control": simulation["exit_points"] - base["control_points"],
                "top_decile_reached_before_exit": (
                    simulation["mfe_at_exit"] >= top_thresholds[base["direction"]]
                ),
            })

    headline: list[dict[str, Any]] = []
    for block, block_rows in evidence_sets(source).items():
        ids = {row["trade_id"] for row in block_rows}
        for policy in POLICIES:
            policy_rows = [
                row for row in results if row["policy"] == policy and row["trade_id"] in ids
            ]
            for direction in ("ALL", *DIRECTIONS):
                selected = policy_rows if direction == "ALL" else [
                    row for row in policy_rows if row["direction"] == direction
                ]
                if selected:
                    headline.append({
                        "evidence_block": block, "direction": direction, "policy": policy,
                        **metrics(selected), **fixed_control_winner_metrics(selected),
                        "warnings": sum(int(row.get("warning_count") or 0) for row in selected),
                        "cancellations": sum(int(row.get("cancellation_count") or 0) for row in selected),
                    })

    selected_dates = [
        row for row in results if row["session_date"] in {"2026-09-30", "2026-10-01"}
    ]
    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "headline.csv", headline)
    write_csv(args.output_root / "policy-trades.csv", results)
    write_csv(args.output_root / "candidate-exits.csv", [row for row in results if row["candidate_exit"]])
    write_csv(args.output_root / "selected-date-examples.csv", selected_dates)
    report = {
        "model": "HILEGA_RSI14_STRUCTURAL_CONFIRMATION_EXIT_V1",
        "sessions": len({row["session_date"] for row in source}),
        "accepted_entries": len(source), "timeframe": "COMPLETED_5_MINUTE",
        "rule": {
            "proof": "+20 required",
            "arm": "Bullish RSI14 >=70; bearish RSI14 <=30",
            "warning": "RSI14 later leaves the directional extreme zone",
            "components": [
                "RSI14 continues against the trade on the next completed 5m close",
                "directional EMA3(RSI9)-WMA21(RSI9) gap contracts",
                "directional WMA21(RSI9) slope weakens",
            ],
            "recovery": "Cancel warning if RSI returns extreme or directional gap expands",
        },
        "headline": headline,
        "safety": {
            "research_only": True, "observation_only": True,
            "live_strategy_modified": False, "execution_enabled": False,
            "paper_order_enabled": False, "quantity": None, "order_sent": False,
        },
    }
    (args.output_root / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print("HILEGA RSI14 STRUCTURAL CONFIRMATION EXIT")
    print("Sessions", report["sessions"], "accepted entries", len(source))
    for row in headline:
        if row["evidence_block"] in {
            "DEVELOPMENT_ALL", "OBSERVED_FORWARD", "ALL_490",
            "RECENT_30", "PRIOR_30", "EARLIER_30",
        }:
            print(row)
    print("SELECTED DATES 2026-09-30 AND 2026-10-01")
    for row in selected_dates:
        print({
            "date": row["session_date"], "direction": row["direction"],
            "entry": row["candidate_entry_timestamp"], "policy": row["policy"],
            "warning": row.get("warning_timestamp"), "exit": row["policy_exit_timestamp"],
            "components": row.get("component_count"),
            "rsi_adverse": row.get("rsi_continues_adverse"),
            "gap_contracts": row.get("gap_contracts"),
            "wma_weakens": row.get("wma_weakens"),
            "control_mfe": row["control_mfe_points"],
            "control_points": row["control_points"],
            "policy_points": row["policy_points"], "delta": row["delta_vs_control"],
        })
    print("Output:", args.output_root / "report.json")
    print("Research only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
