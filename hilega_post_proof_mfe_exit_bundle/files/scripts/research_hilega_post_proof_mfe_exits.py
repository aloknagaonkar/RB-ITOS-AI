#!/usr/bin/env python3
"""Compare post-+20 dynamic MFE exits with canonical Hilega exits."""

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
    "data/historical-evidence/hilega-wma-gap-capture-failures-490-v1/"
    "capture-trade-view.csv"
)
DEFAULT_CACHE = Path("data/historical-evidence/hilega-milega-underlying-cache-v1")
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-post-proof-mfe-exits-490-v1"
)
DIRECTIONS = ("BULLISH", "BEARISH")
GIVEBACKS = (0.25, 0.35, 0.45)
MODES = (
    "ONE_MINUTE_DIRECT",
    "ONE_MINUTE_ARM_FIVE_MINUTE_CONFIRM",
    "FIVE_MINUTE_DIRECT",
)
CONTROL = "CURRENT_RSI9_WMA21_5M_EXIT"


def finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate percentile of empty values")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


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


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    required = {
        "trade_id", "session_date", "direction", "evidence_block",
        "candidate_entry_timestamp", "candidate_entry_price",
        "canonical_exit_completed_close_timestamp", "canonical_exit_price",
        "captured_points", "candidate_mfe_close_points",
    }
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"input CSV missing columns: {sorted(missing)}")
    rows.sort(key=lambda row: row["candidate_entry_timestamp"])
    return rows


def directional_points(direction: str, entry: float, close: float) -> float:
    return close - entry if direction == "BULLISH" else entry - close


def is_completed_5m(timestamp: datetime) -> bool:
    """Cached 1m timestamps are candle labels; minute 4/9/... closes a 5m bar."""
    return timestamp.minute % 5 == 4


def simulate_policy(
    *,
    timeline: list[tuple[datetime, float]],
    direction: str,
    entry_price: float,
    control_exit_at: datetime,
    control_points: float,
    giveback_fraction: float,
    mode: str,
    proof_points: float = 20.0,
) -> dict[str, Any]:
    running_mfe = 0.0
    proof_at: datetime | None = None
    armed = False
    armed_at: datetime | None = None
    for timestamp, close in timeline:
        if timestamp <= timeline[0][0]:
            continue
        if timestamp >= control_exit_at:
            break
        if mode == "FIVE_MINUTE_DIRECT" and not is_completed_5m(timestamp):
            continue
        points = directional_points(direction, entry_price, close)
        running_mfe = max(running_mfe, points)
        if proof_at is None and running_mfe >= proof_points:
            proof_at = timestamp
        if proof_at is None:
            continue
        floor = running_mfe * (1.0 - giveback_fraction)
        breached = points <= floor and points < running_mfe
        if mode in {"ONE_MINUTE_DIRECT", "FIVE_MINUTE_DIRECT"}:
            if breached:
                return {
                    "candidate_exit": True,
                    "proof_timestamp": proof_at.isoformat(),
                    "exit_timestamp": timestamp.isoformat(),
                    "exit_price": close,
                    "exit_points": points,
                    "mfe_at_exit": running_mfe,
                    "floor_at_exit": floor,
                    "giveback_points_at_exit": running_mfe - points,
                    "giveback_pct_at_exit": 100.0 * (running_mfe - points) / running_mfe,
                    "armed_timestamp": None,
                }
        elif mode == "ONE_MINUTE_ARM_FIVE_MINUTE_CONFIRM":
            if breached and not armed:
                armed = True
                armed_at = timestamp
            if is_completed_5m(timestamp) and armed:
                if breached:
                    return {
                        "candidate_exit": True,
                        "proof_timestamp": proof_at.isoformat(),
                        "exit_timestamp": timestamp.isoformat(),
                        "exit_price": close,
                        "exit_points": points,
                        "mfe_at_exit": running_mfe,
                        "floor_at_exit": floor,
                        "giveback_points_at_exit": running_mfe - points,
                        "giveback_pct_at_exit": 100.0 * (running_mfe - points) / running_mfe,
                        "armed_timestamp": armed_at.isoformat() if armed_at else None,
                    }
                armed = False
                armed_at = None
        else:
            raise ValueError(f"unsupported mode: {mode}")
    return {
        "candidate_exit": False,
        "proof_timestamp": proof_at.isoformat() if proof_at else None,
        "exit_timestamp": control_exit_at.isoformat(),
        "exit_price": None,
        "exit_points": control_points,
        "mfe_at_exit": running_mfe,
        "floor_at_exit": None,
        "giveback_points_at_exit": None,
        "giveback_pct_at_exit": None,
        "armed_timestamp": armed_at.isoformat() if armed_at else None,
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
    exits = [row for row in rows if row["candidate_exit"]]
    control_winners = [row for row in rows if float(row["control_points"]) > 0]
    policy_winners = [row for row in rows if float(row["policy_points"]) > 0]
    winner_mfe = sum(float(row["control_mfe_points"]) for row in policy_winners)
    captured = sum(float(row["policy_points"]) for row in policy_winners)
    giveback = winner_mfe - captured
    destroyed_top = [
        row for row in exits
        if row["control_top_decile_move"] and not row["top_decile_reached_before_exit"]
    ]
    return {
        "trades": len(rows),
        "candidate_exits": len(exits),
        "control_total_points": sum(controls),
        "policy_total_points": sum(values),
        "delta_vs_control_sum": sum(values) - sum(controls),
        "positive": len(wins),
        "negative": len(losses),
        "win_rate_pct": 100.0 * len(wins) / len(values) if values else None,
        "gross_winning_points": sum(wins),
        "gross_losing_points": sum(losses),
        "profit_factor": sum(wins) / sum(losses) if losses else None,
        "max_drawdown_points": maximum_drawdown(values),
        "winner_mfe_points": winner_mfe,
        "winner_captured_points": captured,
        "winner_giveback_points": giveback,
        "weighted_winner_capture_pct": (
            100.0 * captured / winner_mfe if winner_mfe else None
        ),
        "weighted_winner_giveback_pct": (
            100.0 * giveback / winner_mfe if winner_mfe else None
        ),
        "control_winners": len(control_winners),
        "control_winners_exited_early": sum(
            row["candidate_exit"] for row in control_winners
        ),
        "control_winners_harmed": sum(
            float(row["policy_points"]) < float(row["control_points"])
            for row in control_winners
        ),
        "points_lost_on_control_winners": sum(
            max(0.0, float(row["control_points"]) - float(row["policy_points"]))
            for row in control_winners
        ),
        "control_losers_saved": sum(
            row["candidate_exit"] and float(row["policy_points"]) > float(row["control_points"])
            for row in rows if float(row["control_points"]) < 0
        ),
        "points_saved_on_control_losers": sum(
            max(0.0, float(row["policy_points"]) - float(row["control_points"]))
            for row in rows if float(row["control_points"]) < 0
        ),
        "control_top_decile_moves": sum(row["control_top_decile_move"] for row in rows),
        "top_decile_moves_destroyed": len(destroyed_top),
    }


def policy_name(mode: str, fraction: float) -> str:
    return f"{mode}_GIVEBACK_{int(fraction * 100)}PCT"


def evidence_sets(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    sessions = sorted({row["session_date"] for row in rows})
    development = [
        row for row in rows
        if str(row["evidence_block"]).startswith("DEVELOPMENT_BLOCK_")
    ]
    result = {
        "DEVELOPMENT_ALL": development,
        "DEVELOPMENT_BLOCK_1": [row for row in rows if row["evidence_block"] == "DEVELOPMENT_BLOCK_1"],
        "DEVELOPMENT_BLOCK_2": [row for row in rows if row["evidence_block"] == "DEVELOPMENT_BLOCK_2"],
        "DEVELOPMENT_BLOCK_3": [row for row in rows if row["evidence_block"] == "DEVELOPMENT_BLOCK_3"],
        "OBSERVED_FORWARD": [row for row in rows if row["evidence_block"] == "OBSERVED_FORWARD"],
        "ALL_490": rows,
    }
    for name, dates in (
        ("RECENT_30", sessions[-30:]),
        ("PRIOR_30", sessions[-60:-30]),
        ("EARLIER_30", sessions[-90:-60]),
    ):
        wanted = set(dates)
        result[name] = [row for row in rows if row["session_date"] in wanted]
    return result


def load_timelines(
    rows: list[dict[str, Any]], cache_root: Path
) -> dict[str, list[tuple[datetime, float]]]:
    from market_lab.hilega_milega_historical_replay_v1 import UNDERLYING, _read_cache

    result: dict[str, list[tuple[datetime, float]]] = {}
    for day_text in sorted({row["session_date"] for row in rows}):
        path = cache_root / f"{day_text}.json"
        if not path.is_file():
            raise FileNotFoundError(f"minute cache unavailable: {path}")
        day = date.fromisoformat(day_text)
        candles = _read_cache(path, UNDERLYING, day)
        result[day_text] = sorted(
            [(candle.timestamp, float(candle.close)) for candle in candles],
            key=lambda item: item[0],
        )
    return result


def trade_timeline(
    row: dict[str, Any], day_rows: list[tuple[datetime, float]]
) -> list[tuple[datetime, float]]:
    entry = datetime.fromisoformat(row["candidate_entry_timestamp"])
    exit_at = datetime.fromisoformat(row["canonical_exit_completed_close_timestamp"])
    selected = [(entry, float(row["candidate_entry_price"]))]
    selected.extend(
        (timestamp, close) for timestamp, close in day_rows
        if entry < timestamp <= exit_at
    )
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proof-points", type=float, default=20.0)
    args = parser.parse_args()

    source = read_rows(args.input)
    timelines = load_timelines(source, args.cache_root)
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
    policies = [CONTROL] + [
        policy_name(mode, fraction) for mode in MODES for fraction in GIVEBACKS
    ]
    results: list[dict[str, Any]] = []
    base_by_id: dict[str, dict[str, Any]] = {}
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
                float(raw["candidate_mfe_close_points"]) >= top_thresholds[raw["direction"]]
            ),
        }
        base_by_id[raw["trade_id"]] = base
        timeline = trade_timeline(raw, timelines[raw["session_date"]])
        results.append({
            **base,
            "policy": CONTROL,
            "mode": "CONTROL",
            "giveback_fraction": None,
            "candidate_exit": False,
            "proof_timestamp": None,
            "policy_exit_timestamp": base["control_exit_timestamp"],
            "policy_exit_price": base["control_exit_price"],
            "policy_points": base["control_points"],
            "delta_vs_control": 0.0,
            "mfe_at_exit": base["control_mfe_points"],
            "floor_at_exit": None,
            "giveback_points_at_exit": (
                base["control_mfe_points"] - base["control_points"]
            ),
            "giveback_pct_at_exit": (
                100.0 * (base["control_mfe_points"] - base["control_points"])
                / base["control_mfe_points"]
                if base["control_mfe_points"] > 0 else None
            ),
            "top_decile_reached_before_exit": base["control_top_decile_move"],
        })
        for mode in MODES:
            for fraction in GIVEBACKS:
                simulation = simulate_policy(
                    timeline=timeline,
                    direction=base["direction"],
                    entry_price=base["candidate_entry_price"],
                    control_exit_at=datetime.fromisoformat(base["control_exit_timestamp"]),
                    control_points=base["control_points"],
                    giveback_fraction=fraction,
                    mode=mode,
                    proof_points=args.proof_points,
                )
                threshold = top_thresholds[base["direction"]]
                results.append({
                    **base,
                    "policy": policy_name(mode, fraction),
                    "mode": mode,
                    "giveback_fraction": fraction,
                    **{f"policy_{key}": value for key, value in simulation.items()
                       if key in {"exit_timestamp", "exit_price"}},
                    "candidate_exit": simulation["candidate_exit"],
                    "proof_timestamp": simulation["proof_timestamp"],
                    "armed_timestamp": simulation["armed_timestamp"],
                    "policy_points": simulation["exit_points"],
                    "delta_vs_control": simulation["exit_points"] - base["control_points"],
                    "mfe_at_exit": simulation["mfe_at_exit"],
                    "floor_at_exit": simulation["floor_at_exit"],
                    "giveback_points_at_exit": simulation["giveback_points_at_exit"],
                    "giveback_pct_at_exit": simulation["giveback_pct_at_exit"],
                    "top_decile_reached_before_exit": simulation["mfe_at_exit"] >= threshold,
                })

    sets = evidence_sets(source)
    headline: list[dict[str, Any]] = []
    for block, block_rows in sets.items():
        ids = {row["trade_id"] for row in block_rows}
        for policy in policies:
            policy_rows = [
                row for row in results if row["policy"] == policy and row["trade_id"] in ids
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
        "model": "HILEGA_POST_PROOF_DYNAMIC_MFE_EXIT_V1",
        "sessions": len({row["session_date"] for row in source}),
        "accepted_entries": len(source),
        "proof_points": args.proof_points,
        "giveback_fractions": GIVEBACKS,
        "modes": MODES,
        "control": (
            "Completed 5m RSI9/WMA21 structural cross or existing session cutoff."
        ),
        "top_decile_thresholds": top_thresholds,
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

    print("HILEGA POST-PROOF DYNAMIC MFE EXIT")
    print("Sessions", report["sessions"], "accepted entries", len(source))
    print("HEADLINE")
    for row in headline:
        if row["evidence_block"] in {
            "DEVELOPMENT_ALL", "OBSERVED_FORWARD", "ALL_490",
            "RECENT_30", "PRIOR_30", "EARLIER_30",
        } and row["direction"] == "ALL":
            print(row)
    print("SELECTED DATES 2026-09-30 AND 2026-10-01")
    for row in selected_dates:
        if row["policy"] == CONTROL or row["candidate_exit"]:
            print({
                "date": row["session_date"],
                "direction": row["direction"],
                "entry": row["candidate_entry_timestamp"],
                "policy": row["policy"],
                "control_mfe": row["control_mfe_points"],
                "control_points": row["control_points"],
                "policy_exit": row.get("policy_exit_timestamp"),
                "policy_points": row["policy_points"],
                "delta": row["delta_vs_control"],
            })
    print("Output:", args.output_root / "report.json")
    print("Research only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
