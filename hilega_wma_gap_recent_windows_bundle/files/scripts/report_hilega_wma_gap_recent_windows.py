#!/usr/bin/env python3
"""Report Hilega candidate capture/failures over recent 30/60/90 sessions."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable


DEFAULT_INPUT = Path(
    "data/historical-evidence/hilega-wma-gap-capture-failures-490-v1/"
    "capture-trade-view.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-wma-gap-recent-windows-v1"
)
WINDOWS = (30, 60, 90)
DIRECTIONS = ("BULLISH", "BEARISH")


def finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


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
    selected = sorted(
        list(rows),
        key=lambda row: (
            str(row["session_date"]),
            str(row["candidate_entry_timestamp"]),
        ),
    )
    winners = [row for row in selected if float(row["captured_points"]) > 0]
    losers = [row for row in selected if float(row["captured_points"]) < 0]
    values = [float(row["captured_points"]) for row in selected]
    gross_wins = sum(float(row["captured_points"]) for row in winners)
    gross_losses = -sum(float(row["captured_points"]) for row in losers)
    winner_mfe = sum(float(row["candidate_mfe_close_points"]) for row in winners)
    winner_giveback = sum(float(row["giveback_from_mfe_points"]) for row in winners)
    capture_values = [
        float(row["winner_capture_ratio_pct"]) for row in winners
        if finite(row.get("winner_capture_ratio_pct")) is not None
    ]
    return {
        "trades": len(selected),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate_pct": 100.0 * len(winners) / len(selected) if selected else None,
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
            sum(capture_values) / len(capture_values) if capture_values else None
        ),
        "median_winner_capture_pct": (
            median(capture_values) if capture_values else None
        ),
        "losers_that_reached_plus20": sum(
            float(row["candidate_mfe_close_points"]) >= 20 for row in losers
        ),
        "loss_points_after_reaching_plus20": -sum(
            float(row["captured_points"]) for row in losers
            if float(row["candidate_mfe_close_points"]) >= 20
        ),
        "same_exit_5m_trades": sum(
            truthy(row.get("own_same_exit_5m_candle")) for row in selected
        ),
        "same_exit_5m_points": sum(
            float(row["captured_points"]) for row in selected
            if truthy(row.get("own_same_exit_5m_candle"))
        ),
    }


def grouped(
    rows: list[dict[str, Any]], fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    groups: defaultdict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[field] for field in fields)].append(row)
    return [
        {**dict(zip(fields, key)), **metrics(groups[key])}
        for key in sorted(groups, key=lambda item: tuple(str(value) for value in item))
    ]


def window_rows(
    rows: list[dict[str, str]], size: int
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    sessions = sorted({row["session_date"] for row in rows})
    if len(sessions) < size:
        raise ValueError(
            f"requested {size} sessions but only {len(sessions)} are available"
        )
    selected_sessions = sessions[-size:]
    selected_set = set(selected_sessions)
    return (
        [row for row in rows if row["session_date"] in selected_set],
        {
            "window": f"LAST_{size}_SESSIONS",
            "session_count": size,
            "start_date": selected_sessions[0],
            "end_date": selected_sessions[-1],
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    rows = read_csv(args.input)

    headline: list[dict[str, Any]] = []
    loss_groups: list[dict[str, Any]] = []
    periods: list[dict[str, Any]] = []
    same_exit: list[dict[str, Any]] = []
    opposite: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []

    for size in WINDOWS:
        selected, definition = window_rows(rows, size)
        windows.append(definition)
        common = {
            "window": definition["window"],
            "session_count": size,
            "start_date": definition["start_date"],
            "end_date": definition["end_date"],
        }
        for direction in ("ALL", *DIRECTIONS):
            subset = (
                selected if direction == "ALL"
                else [row for row in selected if row["direction"] == direction]
            )
            headline.append({**common, "direction": direction, **metrics(subset)})

        for row in grouped(
            [row for row in selected if row["failure_group"] != "NOT_A_LOSS"],
            ("direction", "failure_group"),
        ):
            loss_groups.append({**common, **row})
        for row in grouped(selected, ("direction", "signal_period")):
            periods.append({**common, **row})
        for row in grouped(
            [row for row in selected if truthy(row.get("own_same_exit_5m_candle"))],
            ("direction",),
        ):
            same_exit.append({**common, **row})
        for row in grouped(
            selected, ("direction", "opposite_signal_within_10m")
        ):
            opposite.append({**common, **row})

    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "headline.csv", headline)
    write_csv(args.output_root / "loss-groups.csv", loss_groups)
    write_csv(args.output_root / "signal-periods.csv", periods)
    write_csv(args.output_root / "same-exit-candle.csv", same_exit)
    write_csv(args.output_root / "opposite-signals.csv", opposite)
    report = {
        "model": "HILEGA_WMA_GAP_RECENT_WINDOWS_V1",
        "window_basis": "MOST_RECENT_COMPLETED_TRADING_SESSIONS",
        "windows": windows,
        "headline": headline,
        "loss_groups": loss_groups,
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

    print("HILEGA WMA-GAP RECENT 30/60/90 TRADING SESSIONS")
    for definition in windows:
        print("WINDOW", definition)
        for row in headline:
            if row["window"] == definition["window"]:
                print("HEADLINE", row)
        print("LOSS GROUPS")
        for row in loss_groups:
            if row["window"] == definition["window"]:
                print(row)
    print("Output:", args.output_root / "report.json")
    print("Read only: strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
