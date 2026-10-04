#!/usr/bin/env python3
"""Attribute ordered Hilega WMA-gap losses by fixed confirmation conditions."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable


DEFAULT_INPUT = Path("data/historical-evidence/hilega-wma-gap-490-v1")
DEFAULT_OUTPUT = DEFAULT_INPUT / "loss-attribution"
DIRECTIONS = ("BULLISH", "BEARISH")


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


def latency_bucket(minutes: float) -> str:
    if minutes <= 2:
        return "00_0_TO_2_MIN"
    if minutes <= 5:
        return "01_3_TO_5_MIN"
    if minutes <= 10:
        return "02_6_TO_10_MIN"
    return "03_OVER_10_MIN"


def wma_bucket(strength: float) -> str:
    return "00_0_75_TO_0_99" if strength < 1.0 else "01_GE_1_00"


def expansion_bucket(delta: float) -> str:
    if delta <= 0.25:
        return "00_WEAK_LE_0_25"
    if delta <= 0.75:
        return "01_MEDIUM_0_25_TO_0_75"
    return "02_STRONG_GT_0_75"


def absolute_gap_bucket(gap: float) -> str:
    if gap < 3.0:
        return "00_NARROW_LT_3"
    if gap < 6.0:
        return "01_MODERATE_3_TO_6"
    return "02_WIDE_GE_6"


def passed_attempt_index(
    attempts: list[dict[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in attempts:
        if not truthy(row.get("passed")):
            continue
        key = (str(row["trade_id"]), str(row["confirmation_timestamp"]))
        if key in result:
            raise ValueError(f"duplicate passed confirmation: {key}")
        result[key] = row
    return result


def enrich(
    trades: list[dict[str, str]],
    attempts: list[dict[str, str]],
    thresholds: dict[str, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    index = passed_attempt_index(attempts)
    accepted: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []
    for raw in trades:
        direction = str(raw["direction"])
        canonical = float(raw["canonical_points"])
        mfe = float(raw["mfe_points"])
        plus20 = mfe >= 20.0
        top = mfe >= thresholds[direction]
        if raw.get("candidate_decision") != "ENTRY":
            denied.append({
                "session_date": raw["session_date"],
                "evidence_block": raw.get("evidence_block"),
                "trade_id": raw["trade_id"],
                "direction": direction,
                "route": raw.get("route"),
                "signal_timestamp": raw["entry_timestamp"],
                "canonical_points": canonical,
                "mfe_points": mfe,
                "mae_points": float(raw["mae_points"]),
                "plus20_destroyed": plus20,
                "top_decile_destroyed": top,
                "denied_winner": canonical > 0,
                "denied_winner_points": max(0.0, canonical),
                "denied_loss_saved": canonical < 0,
                "saved_loss_points": max(0.0, -canonical),
            })
            continue
        entry_timestamp = str(raw["candidate_entry_timestamp"])
        key = (str(raw["trade_id"]), entry_timestamp)
        attempt = index.get(key)
        if attempt is None:
            raise ValueError(f"passed confirmation unavailable for accepted trade: {key}")
        signal_at = datetime.fromisoformat(str(raw["entry_timestamp"]))
        entry_at = datetime.fromisoformat(entry_timestamp)
        latency = (entry_at - signal_at).total_seconds() / 60.0
        if latency < 0:
            raise ValueError(f"negative confirmation latency: {key}")
        candidate = float(raw["candidate_points"])
        delta = candidate - canonical
        wma = float(attempt["confirmation_wma_strength"])
        gap = float(attempt["confirmation_directional_gap"])
        gap_delta = float(attempt["directional_gap_delta"])
        accepted.append({
            "session_date": raw["session_date"],
            "evidence_block": raw.get("evidence_block"),
            "trade_id": raw["trade_id"],
            "direction": direction,
            "route": raw.get("route"),
            "signal_timestamp": raw["entry_timestamp"],
            "candidate_entry_timestamp": entry_timestamp,
            "confirmation_latency_minutes": latency,
            "latency_bucket": latency_bucket(latency),
            "confirmation_wma_strength": wma,
            "wma_tier": wma_bucket(wma),
            "confirmation_directional_gap": gap,
            "absolute_gap_tier": absolute_gap_bucket(gap),
            "directional_gap_delta": gap_delta,
            "gap_expansion_tier": expansion_bucket(gap_delta),
            "canonical_points": canonical,
            "candidate_points": candidate,
            "delta_vs_canonical": delta,
            "adverse_entry_delay_cost_points": max(0.0, -delta),
            "favourable_entry_timing_points": max(0.0, delta),
            "accepted_winner": candidate > 0,
            "accepted_loser": candidate < 0,
            "accepted_loss_points": max(0.0, -candidate),
            "mfe_points": mfe,
            "mae_points": float(raw["mae_points"]),
            "plus20_retained": plus20,
            "top_decile_retained": top,
        })
    return accepted, denied


def metrics(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    selected = list(rows)
    values = [float(row["candidate_points"]) for row in selected]
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    gross_win = sum(winners)
    gross_loss = -sum(losers)
    return {
        "entries": len(selected),
        "positive": len(winners),
        "negative": len(losers),
        "win_rate_pct": 100.0 * len(winners) / len(selected) if selected else None,
        "candidate_points": sum(values),
        "mean_points": sum(values) / len(values) if values else None,
        "median_points": median(values) if values else None,
        "gross_winning_points": gross_win,
        "gross_losing_points": gross_loss,
        "profit_factor": gross_win / gross_loss if gross_loss else None,
        "canonical_points_same_trades": sum(
            float(row["canonical_points"]) for row in selected
        ),
        "delta_vs_canonical": sum(
            float(row["delta_vs_canonical"]) for row in selected
        ),
        "adverse_entry_delay_cost_points": sum(
            float(row["adverse_entry_delay_cost_points"]) for row in selected
        ),
        "favourable_entry_timing_points": sum(
            float(row["favourable_entry_timing_points"]) for row in selected
        ),
        "plus20_retained": sum(bool(row["plus20_retained"]) for row in selected),
        "top_decile_retained": sum(
            bool(row["top_decile_retained"]) for row in selected
        ),
    }


def grouped_metrics(
    rows: list[dict[str, Any]], fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    groups: defaultdict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[field] for field in fields)].append(row)
    output: list[dict[str, Any]] = []
    for key in sorted(groups, key=lambda item: tuple(str(value) for value in item)):
        output.append({
            **dict(zip(fields, key)),
            **metrics(groups[key]),
        })
    return output


def denial_metrics(rows: list[dict[str, Any]], direction: str) -> dict[str, Any]:
    selected = [row for row in rows if row["direction"] == direction]
    return {
        "direction": direction,
        "denied": len(selected),
        "denied_winners": sum(bool(row["denied_winner"]) for row in selected),
        "denied_winner_points": sum(
            float(row["denied_winner_points"]) for row in selected
        ),
        "denied_losses_saved": sum(
            bool(row["denied_loss_saved"]) for row in selected
        ),
        "saved_loss_points": sum(
            float(row["saved_loss_points"]) for row in selected
        ),
        "plus20_destroyed": sum(
            bool(row["plus20_destroyed"]) for row in selected
        ),
        "top_decile_destroyed": sum(
            bool(row["top_decile_destroyed"]) for row in selected
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--worst-trades", type=int, default=25)
    args = parser.parse_args()
    report = json.loads((args.input_root / "report.json").read_text(encoding="utf-8"))
    thresholds = {
        direction: float(value)
        for direction, value in report[
            "development_top_decile_mfe_thresholds"
        ].items()
    }
    accepted, denied = enrich(
        read_csv(args.input_root / "trade-results.csv"),
        read_csv(args.input_root / "confirmation-attempts.csv"),
        thresholds,
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "accepted-trades.csv", accepted)
    write_csv(
        args.output_root / "accepted-loss-trades.csv",
        sorted(
            [row for row in accepted if row["accepted_loser"]],
            key=lambda row: float(row["candidate_points"]),
        ),
    )
    write_csv(args.output_root / "denied-trades.csv", denied)
    latency = grouped_metrics(accepted, ("evidence_block", "direction", "latency_bucket"))
    wma = grouped_metrics(accepted, ("evidence_block", "direction", "wma_tier"))
    expansion = grouped_metrics(
        accepted, ("evidence_block", "direction", "gap_expansion_tier")
    )
    absolute_gap = grouped_metrics(
        accepted, ("evidence_block", "direction", "absolute_gap_tier")
    )
    cells = grouped_metrics(
        accepted,
        (
            "evidence_block", "direction", "latency_bucket", "wma_tier",
            "gap_expansion_tier", "absolute_gap_tier",
        ),
    )
    write_csv(args.output_root / "latency-summary.csv", latency)
    write_csv(args.output_root / "wma-tier-summary.csv", wma)
    write_csv(args.output_root / "gap-expansion-summary.csv", expansion)
    write_csv(args.output_root / "absolute-gap-summary.csv", absolute_gap)
    write_csv(args.output_root / "combined-cells.csv", cells)

    direction_summary = [
        {"direction": direction, **metrics(
            [row for row in accepted if row["direction"] == direction]
        )}
        for direction in DIRECTIONS
    ]
    denial_summary = [denial_metrics(denied, direction) for direction in DIRECTIONS]
    output = {
        "model": "HILEGA_WMA_GAP_LOSS_ATTRIBUTION_V1",
        "input_root": str(args.input_root),
        "accepted_entries": len(accepted),
        "denied_signals": len(denied),
        "fixed_buckets": {
            "latency": ["0-2m", "3-5m", "6-10m", ">10m"],
            "wma": ["0.75-0.99", ">=1.00"],
            "gap_expansion": ["0-0.25", ">0.25-0.75", ">0.75"],
            "absolute_gap": ["0-3", "3-6", ">=6"],
        },
        "direction_summary": direction_summary,
        "denial_summary": denial_summary,
        "warning": (
            "Accepted loss, denied-winner opportunity and delay cost overlap "
            "economically and must not be added into a single loss total."
        ),
        "evidence_status": (
            "All 490 sessions are already-inspected development evidence; "
            "future sessions are required for untouched confirmation."
        ),
        "safety": report["safety"],
    }
    (args.output_root / "report.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )

    print("HILEGA WMA-GAP LOSS ATTRIBUTION")
    print("Accepted", len(accepted), "Denied", len(denied))
    for row in direction_summary:
        print("DIRECTION", row)
    for row in denial_summary:
        print("DENIAL", row)
    for name, rows in (
        ("LATENCY", latency),
        ("WMA", wma),
        ("GAP EXPANSION", expansion),
        ("ABSOLUTE GAP", absolute_gap),
    ):
        print(name)
        for row in rows:
            if row["evidence_block"] == "OBSERVED_FORWARD":
                continue
            print(row)
    print("WORST ACCEPTED LOSSES")
    for row in sorted(
        accepted, key=lambda item: float(item["candidate_points"])
    )[:args.worst_trades]:
        print({
            "date": row["session_date"],
            "direction": row["direction"],
            "signal": row["signal_timestamp"],
            "entry": row["candidate_entry_timestamp"],
            "latency": row["confirmation_latency_minutes"],
            "wma": round(float(row["confirmation_wma_strength"]), 4),
            "gap": round(float(row["confirmation_directional_gap"]), 4),
            "gap_delta": round(float(row["directional_gap_delta"]), 4),
            "canonical": round(float(row["canonical_points"]), 2),
            "candidate": round(float(row["candidate_points"]), 2),
            "delay_cost": round(
                float(row["adverse_entry_delay_cost_points"]), 2
            ),
        })
    print("Output:", args.output_root / "report.json")
    print("Read only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
