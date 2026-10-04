#!/usr/bin/env python3
"""Test RSI9/RSI14 extreme-zone reversal exits against Hilega control."""

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
    "data/historical-evidence/hilega-rsi-extreme-reversal-exits-490-v1"
)
POLICY_CONFIGS = (
    ("RSI9_EXTREME_REVERSAL_5M", 9, False),
    ("RSI9_EXTREME_REVERSAL_AFTER_PLUS20_5M", 9, True),
    ("RSI14_EXTREME_REVERSAL_5M", 14, False),
    ("RSI14_EXTREME_REVERSAL_AFTER_PLUS20_5M", 14, True),
)
POLICIES = (CONTROL, *(item[0] for item in POLICY_CONFIGS))


def rsi_index(
    timelines: dict[str, list[tuple[datetime, float]]], period: int,
) -> dict[datetime, float]:
    closes = completed_five_minute_closes(timelines)
    values = pine_rsi([close for _, close in closes], period)
    return {
        timestamp: float(value)
        for (timestamp, _), value in zip(closes, values)
        if value is not None
    }


def is_extreme(direction: str, value: float) -> bool:
    return value >= 70.0 if direction == "BULLISH" else value <= 30.0


def left_extreme(direction: str, value: float) -> bool:
    return value < 70.0 if direction == "BULLISH" else value > 30.0


def simulate_reversal_exit(
    *,
    timeline: list[tuple[datetime, float]],
    rsi_by_timestamp: dict[datetime, float],
    direction: str,
    entry_price: float,
    control_exit_at: datetime,
    control_points: float,
    require_proof: bool,
    proof_points: float = 20.0,
) -> dict[str, Any]:
    running_mfe = 0.0
    proof_at: datetime | None = None
    armed_at: datetime | None = None
    armed_rsi: float | None = None
    peak_extreme_rsi: float | None = None
    observations = 0
    for timestamp, close in timeline:
        if timestamp <= timeline[0][0] or timestamp >= control_exit_at:
            continue
        points = directional_points(direction, entry_price, close)
        running_mfe = max(running_mfe, points)
        if proof_at is None and running_mfe >= proof_points:
            proof_at = timestamp
        rsi = rsi_by_timestamp.get(timestamp)
        if rsi is None:
            continue
        observations += 1
        eligible = not require_proof or proof_at is not None
        if armed_at is None:
            if eligible and is_extreme(direction, rsi):
                armed_at = timestamp
                armed_rsi = rsi
                peak_extreme_rsi = rsi
            continue
        if direction == "BULLISH":
            peak_extreme_rsi = max(float(peak_extreme_rsi), rsi)
        else:
            peak_extreme_rsi = min(float(peak_extreme_rsi), rsi)
        if timestamp > armed_at and left_extreme(direction, rsi):
            return {
                "candidate_exit": True,
                "proof_timestamp": proof_at.isoformat() if proof_at else None,
                "armed_timestamp": armed_at.isoformat(),
                "armed_rsi": armed_rsi,
                "peak_extreme_rsi": peak_extreme_rsi,
                "exit_timestamp": timestamp.isoformat(),
                "exit_price": close,
                "exit_points": points,
                "exit_rsi": rsi,
                "mfe_at_exit": running_mfe,
                "rsi_observations": observations,
            }
    return {
        "candidate_exit": False,
        "proof_timestamp": proof_at.isoformat() if proof_at else None,
        "armed_timestamp": armed_at.isoformat() if armed_at else None,
        "armed_rsi": armed_rsi,
        "peak_extreme_rsi": peak_extreme_rsi,
        "exit_timestamp": control_exit_at.isoformat(),
        "exit_price": None,
        "exit_points": control_points,
        "exit_rsi": None,
        "mfe_at_exit": running_mfe,
        "rsi_observations": observations,
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
    rsi_indexes = {period: rsi_index(timelines, period) for period in (9, 14)}
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
            "trade_id": raw["trade_id"],
            "session_date": raw["session_date"],
            "evidence_block": raw["evidence_block"],
            "direction": raw["direction"],
            "signal_timestamp": raw.get("signal_timestamp"),
            "candidate_entry_timestamp": raw["candidate_entry_timestamp"],
            "candidate_entry_price": float(raw["candidate_entry_price"]),
            "control_exit_timestamp": raw["canonical_exit_completed_close_timestamp"],
            "control_exit_price": float(raw["canonical_exit_price"]),
            "control_points": float(raw["captured_points"]),
            "control_mfe_points": float(raw["candidate_mfe_close_points"]),
            "control_top_decile_move": (
                float(raw["candidate_mfe_close_points"])
                >= top_thresholds[raw["direction"]]
            ),
        }
        timeline = trade_timeline(raw, timelines[raw["session_date"]])
        results.append({
            **base,
            "policy": CONTROL,
            "rsi_period": None,
            "candidate_exit": False,
            "policy_exit_timestamp": base["control_exit_timestamp"],
            "policy_exit_price": base["control_exit_price"],
            "policy_points": base["control_points"],
            "delta_vs_control": 0.0,
            "mfe_at_exit": base["control_mfe_points"],
            "top_decile_reached_before_exit": base["control_top_decile_move"],
        })
        for policy, period, require_proof in POLICY_CONFIGS:
            simulation = simulate_reversal_exit(
                timeline=timeline,
                rsi_by_timestamp=rsi_indexes[period],
                direction=base["direction"],
                entry_price=base["candidate_entry_price"],
                control_exit_at=datetime.fromisoformat(base["control_exit_timestamp"]),
                control_points=base["control_points"],
                require_proof=require_proof,
                proof_points=args.proof_points,
            )
            results.append({
                **base,
                "policy": policy,
                "rsi_period": period,
                "require_plus20_proof": require_proof,
                "candidate_exit": simulation["candidate_exit"],
                "proof_timestamp": simulation["proof_timestamp"],
                "armed_timestamp": simulation["armed_timestamp"],
                "armed_rsi": simulation["armed_rsi"],
                "peak_extreme_rsi": simulation["peak_extreme_rsi"],
                "policy_exit_timestamp": simulation["exit_timestamp"],
                "policy_exit_price": simulation["exit_price"],
                "exit_rsi": simulation["exit_rsi"],
                "policy_points": simulation["exit_points"],
                "delta_vs_control": simulation["exit_points"] - base["control_points"],
                "mfe_at_exit": simulation["mfe_at_exit"],
                "rsi_observations": simulation["rsi_observations"],
                "top_decile_reached_before_exit": (
                    simulation["mfe_at_exit"] >= top_thresholds[base["direction"]]
                ),
            })

    headline: list[dict[str, Any]] = []
    for block, block_rows in evidence_sets(source).items():
        ids = {row["trade_id"] for row in block_rows}
        for policy in POLICIES:
            policy_rows = [
                row for row in results
                if row["policy"] == policy and row["trade_id"] in ids
            ]
            for direction in ("ALL", *DIRECTIONS):
                selected = policy_rows if direction == "ALL" else [
                    row for row in policy_rows if row["direction"] == direction
                ]
                if selected:
                    headline.append({
                        "evidence_block": block,
                        "direction": direction,
                        "policy": policy,
                        **metrics(selected),
                        **fixed_control_winner_metrics(selected),
                        "armed_trades": sum(bool(row.get("armed_timestamp")) for row in selected),
                    })

    selected_dates = [
        row for row in results
        if row["session_date"] in {"2026-09-30", "2026-10-01"}
    ]
    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "headline.csv", headline)
    write_csv(args.output_root / "policy-trades.csv", results)
    write_csv(
        args.output_root / "candidate-exits.csv",
        [row for row in results if row["candidate_exit"]],
    )
    write_csv(args.output_root / "selected-date-examples.csv", selected_dates)
    report = {
        "model": "HILEGA_RSI_EXTREME_REVERSAL_EXIT_RESEARCH_V1",
        "sessions": len({row["session_date"] for row in source}),
        "accepted_entries": len(source),
        "timeframe": "COMPLETED_5_MINUTE",
        "rule": (
            "Arm bullish at RSI >=70 and exit on a later close below 70; "
            "arm bearish at RSI <=30 and exit on a later close above 30."
        ),
        "policies": POLICIES,
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

    print("HILEGA RSI EXTREME-ZONE REVERSAL EXIT")
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
            "armed": row.get("armed_timestamp"), "armed_rsi": row.get("armed_rsi"),
            "exit": row["policy_exit_timestamp"], "exit_rsi": row.get("exit_rsi"),
            "control_mfe": row["control_mfe_points"],
            "control_points": row["control_points"],
            "policy_points": row["policy_points"], "delta": row["delta_vs_control"],
        })
    print("Output:", args.output_root / "report.json")
    print("Research only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
