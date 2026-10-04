#!/usr/bin/env python3
"""Compare completed-5m RSI9 extreme exits with the canonical Hilega exit."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.research_hilega_post_proof_mfe_exits import (
    CONTROL, DIRECTIONS, evidence_sets, load_timelines, metrics, percentile,
    read_rows, trade_timeline, write_csv,
)
from scripts.research_hilega_rsi14_extreme_exits import (
    completed_five_minute_closes, fixed_control_winner_metrics, pine_rsi,
    simulate_rsi14_exit,
)


DEFAULT_INPUT = Path(
    "data/historical-evidence/hilega-wma-gap-capture-failures-490-v1/"
    "capture-trade-view.csv"
)
DEFAULT_CACHE = Path("data/historical-evidence/hilega-milega-underlying-cache-v1")
DEFAULT_OUTPUT = Path("data/historical-evidence/hilega-rsi9-extreme-exits-490-v1")
DIRECT = "RSI9_EXTREME_LEVEL_5M"
POST_PROOF = "RSI9_EXTREME_AFTER_PLUS20_5M"
POLICIES = (CONTROL, DIRECT, POST_PROOF)


def rsi9_index(
    timelines: dict[str, list[tuple[datetime, float]]],
) -> dict[datetime, float]:
    closes = completed_five_minute_closes(timelines)
    values = pine_rsi([close for _, close in closes], 9)
    return {
        timestamp: float(value)
        for (timestamp, _), value in zip(closes, values)
        if value is not None
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
    rsi_by_timestamp = rsi9_index(timelines)
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
            "candidate_exit": False,
            "policy_exit_timestamp": base["control_exit_timestamp"],
            "policy_exit_price": base["control_exit_price"],
            "policy_points": base["control_points"],
            "delta_vs_control": 0.0,
            "exit_rsi9": None,
            "mfe_at_exit": base["control_mfe_points"],
            "top_decile_reached_before_exit": base["control_top_decile_move"],
        })
        for policy, require_proof in ((DIRECT, False), (POST_PROOF, True)):
            simulation = simulate_rsi14_exit(
                timeline=timeline,
                rsi_by_timestamp=rsi_by_timestamp,
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
                "candidate_exit": simulation["candidate_exit"],
                "proof_timestamp": simulation["proof_timestamp"],
                "policy_exit_timestamp": simulation["exit_timestamp"],
                "policy_exit_price": simulation["exit_price"],
                "policy_points": simulation["exit_points"],
                "delta_vs_control": simulation["exit_points"] - base["control_points"],
                "exit_rsi9": simulation["exit_rsi14"],
                "mfe_at_exit": simulation["mfe_at_exit"],
                "rsi9_observations": simulation["rsi14_observations"],
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
        "model": "HILEGA_RSI9_EXTREME_EXIT_RESEARCH_V1",
        "sessions": len({row["session_date"] for row in source}),
        "accepted_entries": len(source),
        "timeframe": "COMPLETED_5_MINUTE",
        "rules": {
            DIRECT: "Bullish RSI9 >= 70; bearish RSI9 <= 30.",
            POST_PROOF: (
                "Same RSI9 extreme, but only after the trade first reaches +20 points."
            ),
            CONTROL: (
                "Existing completed-5m RSI9/WMA21 structural cross or session cutoff."
            ),
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
    }
    (args.output_root / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    print("HILEGA RSI9 EXTREME EXIT COMPARISON")
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
            "date": row["session_date"],
            "direction": row["direction"],
            "entry": row["candidate_entry_timestamp"],
            "policy": row["policy"],
            "exit": row["policy_exit_timestamp"],
            "exit_rsi9": row.get("exit_rsi9"),
            "control_mfe": row["control_mfe_points"],
            "control_points": row["control_points"],
            "policy_points": row["policy_points"],
            "delta": row["delta_vs_control"],
        })
    print("Output:", args.output_root / "report.json")
    print("Research only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
