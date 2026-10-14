#!/usr/bin/env python3
"""Validate post-signal WMA21 confirmation on selected Hilega sessions.

The canonical strategy remains the source of every entry signal.  This program
does not manufacture entries.  For each recorded canonical signal it rebuilds
the five-minute RSI9 -> EMA3 -> WMA21 indicator state, then values the forming
next five-minute candle after every completed one-minute candle through T+10.

The WMA change is always measured against the latest completed five-minute
candle.  A bullish signal confirms at change >= +0.75; a bearish signal
confirms at change <= -0.75.  Magnitude >= 1.00 is tagged STRONG.  Full
directional alignment is reported separately so WMA is never treated as a
standalone strategy.  The unchanged canonical signal/lifecycle is the other
required evidence; the optional full-alignment flag is diagnostic only.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from market_lab.domain import IST
from market_lab.hilega_milega_historical_replay_v1 import (
    UNDERLYING,
    _read_cache,
    aggregate_exact_5m,
)
from market_lab.hilega_milega_strategy_v1 import HilegaMilegaIndicatorEngineV1


DEFAULT_CACHE = Path("data/historical-evidence/hilega-milega-underlying-cache-v1")
DEFAULT_TRADES = Path(
    "data/historical-evidence/hilega-alignment-points-490-v1/"
    "trade-alignment-points.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/"
    "hilega-wma-delayed-confirmation-2026-09-30-2026-10-01-v2"
)


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


def directional_change(raw_change: float, direction: str) -> float:
    if direction == "BULLISH":
        return raw_change
    if direction == "BEARISH":
        return -raw_change
    raise ValueError(f"unsupported direction: {direction!r}")


def confirmation_tier(value: float, threshold: float, strong: float) -> str:
    if value >= strong:
        return "STRONG_GE_1_00"
    if value >= threshold:
        return "CONFIRMED_GE_0_75"
    if value > 0.0:
        return "WAIT_DEVELOPING"
    return "WAIT_OPPOSING_OR_ZERO"


def delayed_entry_decision(first_confirmed: dict[str, Any] | None) -> str:
    return (
        "DELAYED_ENTRY_CONFIRMED"
        if first_confirmed is not None
        else "NO_ENTRY_BY_T10"
    )


def full_alignment(snapshot: Any, direction: str) -> bool:
    if not snapshot.ready:
        return False
    rsi = float(snapshot.rsi9)
    ema = float(snapshot.ema3_rsi)
    wma = float(snapshot.wma21_rsi)
    if direction == "BULLISH":
        return rsi > 50.0 and rsi > ema > wma
    if direction == "BEARISH":
        return rsi < 50.0 and rsi < ema < wma
    raise ValueError(f"unsupported direction: {direction!r}")


def read_trades(path: Path, selected_dates: set[str]) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "trade_id", "session_date", "direction", "route",
        "entry_timestamp", "entry_price", "exit_timestamp", "exit_price",
        "captured_points", "mfe_points",
    }
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"trade CSV missing columns: {sorted(missing)}")
    output: list[dict[str, Any]] = []
    for raw in rows:
        if raw["session_date"] not in selected_dates:
            continue
        row = dict(raw)
        for field in (
            "entry_price", "exit_price", "captured_points", "mfe_points"
        ):
            row[field] = finite(row[field])
        if any(row[field] is None for field in (
            "entry_price", "exit_price", "captured_points", "mfe_points"
        )):
            raise ValueError(f"unavailable trade valuation: {row['trade_id']}")
        output.append(row)
    return sorted(output, key=lambda row: row["entry_timestamp"])


def cache_sessions(cache_root: Path, through: date) -> list[tuple[date, Path]]:
    result: list[tuple[date, Path]] = []
    for path in cache_root.glob("*.json"):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day <= through:
            result.append((day, path))
    return sorted(result)


def build_indicator_states(
    cache_root: Path,
    selected_dates: set[str],
) -> tuple[
    dict[tuple[str, datetime], Any],
    dict[tuple[str, datetime], Any],
    dict[str, list[Any]],
]:
    """Return post-bar engine states, snapshots, and selected 1m candles."""
    last_day = max(date.fromisoformat(value) for value in selected_dates)
    engine = HilegaMilegaIndicatorEngineV1()
    states: dict[tuple[str, datetime], Any] = {}
    snapshots: dict[tuple[str, datetime], Any] = {}
    selected_minutes: dict[str, list[Any]] = {}

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
        if len(bars) != 75:
            raise ValueError(f"{day}: expected 75 five-minute bars")
        for bar in bars:
            snapshot = engine.update(float(bar.close))
            if day.isoformat() in selected_dates:
                key = (day.isoformat(), bar.ts.astimezone(IST))
                states[key] = copy.deepcopy(engine)
                snapshots[key] = snapshot
        if day.isoformat() in selected_dates:
            selected_minutes[day.isoformat()] = sorted(
                candles,
                key=lambda candle: candle.timestamp,
            )

    missing = selected_dates - set(selected_minutes)
    if missing:
        raise ValueError(f"selected cache sessions unavailable: {sorted(missing)}")
    return states, snapshots, selected_minutes


def directional_points(direction: str, entry: float, mark: float) -> float:
    return mark - entry if direction == "BULLISH" else entry - mark


def validate_trade(
    trade: dict[str, Any],
    *,
    states: dict[tuple[str, datetime], Any],
    snapshots: dict[tuple[str, datetime], Any],
    candles: list[Any],
    threshold: float,
    strong_threshold: float,
    timeout_minutes: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    day = str(trade["session_date"])
    direction = str(trade["direction"])
    entry_label = datetime.fromisoformat(str(trade["entry_timestamp"])).astimezone(IST)
    exit_label = datetime.fromisoformat(str(trade["exit_timestamp"])).astimezone(IST)
    entry_price = float(trade["entry_price"])

    # A signal carrying a five-minute label becomes actionable only after all
    # five constituent one-minute candles have completed.
    actionable_at = entry_label + timedelta(minutes=5)
    expires_at = actionable_at + timedelta(minutes=timeout_minutes - 1)
    # The five-minute exit carrying label HH:MM becomes known on its final
    # constituent one-minute close at HH:MM+4.  Canonical exit has priority on
    # that close, so it cannot also become a delayed entry.
    canonical_exit_close = exit_label + timedelta(minutes=4)
    trace: list[dict[str, Any]] = []
    first_confirmed: dict[str, Any] | None = None
    first_strong: dict[str, Any] | None = None
    first_aligned: dict[str, Any] | None = None

    for candle in candles:
        minute = candle.timestamp.astimezone(IST).replace(second=0, microsecond=0)
        if minute < actionable_at:
            continue
        if minute >= canonical_exit_close:
            continue
        slot = floor_5m(minute)
        reference_label = slot - timedelta(minutes=5)
        key = (day, reference_label)
        base = states.get(key)
        reference = snapshots.get(key)
        if base is None or reference is None or reference.wma21_rsi is None:
            continue

        provisional = copy.deepcopy(base).update(float(candle.close))
        if provisional.wma21_rsi is None:
            continue
        raw = float(provisional.wma21_rsi) - float(reference.wma21_rsi)
        directional = directional_change(raw, direction)
        tier = confirmation_tier(directional, threshold, strong_threshold)
        aligned = full_alignment(provisional, direction)
        row = {
            "trade_id": trade["trade_id"],
            "session_date": day,
            "direction": direction,
            "route": trade["route"],
            "strategy_signal_timestamp": trade["entry_timestamp"],
            "minute_timestamp": minute.isoformat(),
            "minutes_observed": int((minute - actionable_at).total_seconds() // 60) + 1,
            "within_confirmation_window": minute <= expires_at,
            "reference_5m_timestamp": reference_label.isoformat(),
            "reference_rsi9": reference.rsi9,
            "reference_ema3_rsi": reference.ema3_rsi,
            "reference_wma21_rsi": float(reference.wma21_rsi),
            "provisional_rsi9": provisional.rsi9,
            "provisional_ema3_rsi": provisional.ema3_rsi,
            "provisional_wma21_rsi": provisional.wma21_rsi,
            "raw_wma_change": raw,
            "directional_wma_change": directional,
            "confirmation_tier": tier,
            "full_directional_alignment": aligned,
            "observed_close": float(candle.close),
            "observed_open": float(candle.open),
            "observed_high": float(candle.high),
            "observed_low": float(candle.low),
            "observed_volume": (
                None if candle.volume is None else float(candle.volume)
            ),
            "points_from_original_entry": directional_points(
                direction, entry_price, float(candle.close)
            ),
        }
        trace.append(row)
        if minute <= expires_at and first_confirmed is None and directional >= threshold:
            first_confirmed = row
        if minute <= expires_at and first_strong is None and directional >= strong_threshold:
            first_strong = row
        if minute <= expires_at and first_aligned is None and directional >= threshold and aligned:
            first_aligned = row

    # The original canonical Hilega signal/lifecycle supplies the strategy
    # evidence.  WMA is only its delayed confirmation; it is not required to
    # regenerate every original RSI/EMA entry predicate on the later minute.
    chosen = first_confirmed
    delayed_points = None
    delayed_entry_price = None
    if chosen is not None:
        delayed_entry_price = float(chosen["observed_close"])
        delayed_points = directional_points(
            direction, delayed_entry_price, float(trade["exit_price"])
        )

    summary = {
        "trade_id": trade["trade_id"],
        "session_date": day,
        "direction": direction,
        "route": trade["route"],
        "strategy_signal_timestamp": trade["entry_timestamp"],
        "original_entry_price": entry_price,
        "canonical_exit_timestamp": trade["exit_timestamp"],
        "canonical_exit_price": trade["exit_price"],
        "canonical_points": trade["captured_points"],
        "canonical_mfe_points": trade["mfe_points"],
        "canonical_reached_plus20": float(trade["mfe_points"]) >= 20.0,
        "first_wma_075_timestamp": (
            None if first_confirmed is None else first_confirmed["minute_timestamp"]
        ),
        "first_wma_075_change": (
            None if first_confirmed is None else first_confirmed["directional_wma_change"]
        ),
        "first_wma_100_timestamp": (
            None if first_strong is None else first_strong["minute_timestamp"]
        ),
        "first_wma_100_change": (
            None if first_strong is None else first_strong["directional_wma_change"]
        ),
        "first_fully_aligned_timestamp": (
            None if first_aligned is None else first_aligned["minute_timestamp"]
        ),
        "first_fully_aligned_wma_change": (
            None if first_aligned is None else first_aligned["directional_wma_change"]
        ),
        "candidate_decision": delayed_entry_decision(first_confirmed),
        "delayed_entry_price": delayed_entry_price,
        "delayed_entry_to_canonical_exit_points": delayed_points,
        "difference_vs_canonical_points": (
            None if delayed_points is None
            else delayed_points - float(trade["captured_points"])
        ),
        "bars_evaluated": len(trace),
        "observation_only": True,
    }
    return summary, trace


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


def aggregate(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    selected = list(rows)
    confirmed = [row for row in selected if row["candidate_decision"] == "DELAYED_ENTRY_CONFIRMED"]
    avoided = [row for row in selected if row["candidate_decision"] == "NO_ENTRY_BY_T10"]
    delayed = [float(row["delayed_entry_to_canonical_exit_points"]) for row in confirmed]
    return {
        "signals": len(selected),
        "confirmed_entries": len(confirmed),
        "no_entry_by_t10": len(avoided),
        "canonical_sum_points": sum(float(row["canonical_points"]) for row in selected),
        "confirmed_delayed_sum_points": sum(delayed),
        "confirmed_delayed_positive": sum(value > 0.0 for value in delayed),
        "confirmed_delayed_negative": sum(value < 0.0 for value in delayed),
        "avoided_canonical_sum_points": sum(float(row["canonical_points"]) for row in avoided),
        "avoided_positive_trades": sum(float(row["canonical_points"]) > 0.0 for row in avoided),
        "avoided_negative_trades": sum(float(row["canonical_points"]) < 0.0 for row in avoided),
        "avoided_plus20_moves": sum(bool(row["canonical_reached_plus20"]) for row in avoided),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dates", nargs="+", default=("2026-09-30", "2026-10-01"))
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--trades", type=Path, default=DEFAULT_TRADES)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument("--strong-threshold", type=float, default=1.00)
    parser.add_argument("--timeout-minutes", type=int, default=10)
    arguments = parser.parse_args()

    selected_dates = set(arguments.dates)
    if arguments.threshold <= 0.0 or arguments.strong_threshold < arguments.threshold:
        raise SystemExit("STOP: invalid WMA confirmation thresholds")
    if arguments.timeout_minutes < 1:
        raise SystemExit("STOP: timeout must be positive")

    trades = read_trades(arguments.trades, selected_dates)
    states, snapshots, minute_rows = build_indicator_states(
        arguments.cache_root, selected_dates
    )
    summaries: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    for trade in trades:
        summary, rows = validate_trade(
            trade,
            states=states,
            snapshots=snapshots,
            candles=minute_rows[str(trade["session_date"])],
            threshold=arguments.threshold,
            strong_threshold=arguments.strong_threshold,
            timeout_minutes=arguments.timeout_minutes,
        )
        summaries.append(summary)
        trace.extend(rows)

    arguments.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(arguments.output_root / "trade-validation.csv", summaries)
    write_csv(arguments.output_root / "minute-by-minute-wma.csv", trace)
    by_date = {
        day: aggregate(row for row in summaries if row["session_date"] == day)
        for day in sorted(selected_dates)
    }
    report = {
        "model": "HILEGA_POST_SIGNAL_WMA_DELAYED_CONFIRMATION_V2",
        "selected_dates": sorted(selected_dates),
        "rule": {
            "signal_source": "UNCHANGED_CANONICAL_HILEGA_STRATEGY",
            "reference": "LATEST_COMPLETED_FIVE_MINUTE_WMA21_OF_RSI9",
            "sampling": "EVERY_COMPLETED_ONE_MINUTE_CANDLE_AFTER_SIGNAL",
            "bullish_confirmation": "RAW_WMA_CHANGE >= +0.75",
            "bearish_confirmation": "RAW_WMA_CHANGE <= -0.75",
            "strong_confirmation": "DIRECTIONAL_WMA_CHANGE >= 1.00",
            "final_entry_gate": "ACTIVE_CANONICAL_SIGNAL_AND_WMA_CONFIRMATION",
            "full_alignment": "DIAGNOSTIC_ONLY_NOT_AN_ADDITIONAL_ENTRY_GATE",
            "timeout": "NO_ENTRY_AFTER_T10",
        },
        "overall": aggregate(summaries),
        "by_date": by_date,
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
    (arguments.output_root / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    print("HILEGA POST-SIGNAL WMA DELAYED CONFIRMATION")
    for row in summaries:
        print({
            "date": row["session_date"],
            "signal": str(row["strategy_signal_timestamp"])[11:16],
            "direction": row["direction"],
            "wma_0.75": row["first_wma_075_timestamp"],
            "wma_1.00": row["first_wma_100_timestamp"],
            "full_alignment_diagnostic": row["first_fully_aligned_timestamp"],
            "decision": row["candidate_decision"],
            "canonical_points": row["canonical_points"],
            "delayed_points": row["delayed_entry_to_canonical_exit_points"],
            "plus20": row["canonical_reached_plus20"],
        })
    print("OVERALL", report["overall"])
    print("BY DATE", report["by_date"])
    print("Output:", arguments.output_root / "report.json")
    print("Read only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
