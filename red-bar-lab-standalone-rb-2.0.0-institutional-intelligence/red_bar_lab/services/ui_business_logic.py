"""Business logic extracted from ui/_shared.py for testability and reuse."""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

import pandas as pd

from red_bar_lab.utils import IST, safe_float


def is_session_complete(trading_date: date) -> bool:
    """Check if the trading session is over based on IST time."""
    now = datetime.now(IST)
    if trading_date < now.date():
        return True
    if trading_date > now.date():
        return False
    return now.time().replace(tzinfo=None) >= time(15, 30)


def format_ist_time(value: Any) -> str | None:
    """Format a timestamp value to IST HH:MM:SS string."""
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("Asia/Kolkata")
        else:
            ts = ts.tz_convert("Asia/Kolkata")
        return ts.strftime("%H:%M:%S")
    except Exception:
        return str(value)


def round_points(value: Any) -> float | None:
    """Round a points value to 2 decimal places."""
    if value is None:
        return None
    return round(float(value), 2)


def actionable_completion_exit(trade_rows: list[dict]) -> tuple[str | None, Any]:
    """Determine the last actionable closed trade exit time/price.

    Returns (exit_time_ist, exit_price) or (None, None) if fewer than 10
    closed actionable trades exist.
    """
    actionable = [
        row for row in trade_rows
        if str(row.get("exit_model") or "") != "EOD_HOLD"
    ]
    closed = [
        row for row in actionable
        if row.get("status") == "CLOSED" and row.get("exit_timestamp")
    ]
    if len(closed) < 10:
        return None, None

    last = max(closed, key=lambda row: pd.Timestamp(row["exit_timestamp"]))
    return (
        format_ist_time(last.get("exit_timestamp")),
        last.get("exit_price"),
    )


def filter_backtest_rows(
    rows: list[dict],
    *,
    signal_type: str,
    direction: str,
    exit_model: str,
    trade_result: str,
    signal_quality: str = "ALL",
    min_success_score: int = 0,
) -> list[dict]:
    """Filter trade rows by signal_type, direction, exit_model, trade_result, signal_quality."""
    filtered = list(rows)
    if signal_type != "ALL":
        filtered = [r for r in filtered if str(r.get("level_type")) == signal_type]
    if direction != "ALL":
        filtered = [r for r in filtered if str(r.get("direction")) == direction]
    if exit_model != "ALL":
        filtered = [r for r in filtered if str(r.get("exit_model")) == exit_model]
    if trade_result != "ALL":
        from red_bar_lab.strategy.trade_outcome import classify_trade_result
        filtered = [
            r for r in filtered
            if classify_trade_result(r.get("points")) == trade_result
        ]

    if signal_quality != "ALL" or min_success_score > 0:
        from red_bar_lab.strategy.trade_outcome import summarize_actionable_models

        grouped: dict[str, list[dict]] = {}
        for row in rows:
            signal_id = row.get("signal_id")
            if signal_id:
                grouped.setdefault(str(signal_id), []).append(row)

        allowed_signal_ids: set[str] = set()
        for signal_id, signal_rows in grouped.items():
            summary = summarize_actionable_models(signal_rows)
            quality = str(summary.get("signal_quality") or "")
            success = int(summary.get("actionable_success") or 0)

            quality_match = signal_quality == "ALL" or quality == signal_quality
            score_match = success >= int(min_success_score)

            if quality_match and score_match:
                allowed_signal_ids.add(signal_id)

        filtered = [
            r for r in filtered
            if str(r.get("signal_id")) in allowed_signal_ids
        ]

    return filtered


def filtered_backtest_summary(rows: list[dict]) -> dict[str, Any]:
    """Compute summary statistics from trade rows."""
    from red_bar_lab.strategy.trade_outcome import (
        actionable_trade_rows,
        benchmark_trade_rows,
    )

    actionable = actionable_trade_rows(rows)
    benchmark = benchmark_trade_rows(rows)

    points = [
        float(r["points"])
        for r in actionable
        if r.get("points") is not None
    ]
    wins = [p for p in points if p > 0]
    losses = [p for p in points if p < 0]
    breakeven = [p for p in points if p == 0]

    return {
        "actionable_rows": len(actionable),
        "benchmark_rows": len(benchmark),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate": (
            len(wins) / max(1, len(wins) + len(losses) + len(breakeven)) * 100.0
        ),
        "average_points": sum(points) / len(points) if points else 0.0,
        "best_points": max(points) if points else None,
        "worst_points": min(points) if points else None,
    }


def current_dashboard_rows(
    database,
    instrument_key: str,
    trading_date: str,
    active_attempts: list[dict],
    completed_attempts: list[dict],
) -> list[dict]:
    """Aggregate trade outcomes and apply priority ordering for the dashboard."""
    from red_bar_lab.strategy.trade_outcome import summarize_actionable_models

    rows: list[dict] = []
    trade_rows = database.read_paper_trade_outcomes(instrument_key, trading_date)
    by_signal: dict[str, list[dict]] = {}
    for row in trade_rows:
        signal_id = row.get("signal_id")
        if signal_id:
            by_signal.setdefault(str(signal_id), []).append(row)

    def append_item(item: dict, completed: bool = False) -> None:
        signal_id = str(item.get("signal_id") or "")
        linked = by_signal.get(signal_id, [])
        summarize_actionable_models(linked)

        if completed:
            entry_time = item.get("entry_timestamp")
            entry_price = item.get("entry_price")
            current_price = item.get("current_price")
            current_pl = item.get("benchmark_current_points")
            status = item.get("trade_status") or "COMPLETED"
            score = item.get("actionable_score")
            quality = item.get("signal_quality")
            best_points = item.get("best_actionable_points")
        else:
            entry_time = item.get("confirmation_timestamp")
            entry_price = item.get("underlying_entry")
            current_price = item.get("current_price")
            current_pl = item.get("live_points")
            status = item.get("trade_status")
            score = item.get("actionable_score")
            quality = item.get("signal_quality")
            best_points = item.get("best_actionable_points")

        exit_time, exit_price = actionable_completion_exit(linked)

        rows.append({
            "priority": item.get("priority"),
            "signal": item.get("signal_label"),
            "status": status,
            "entry_time_ist": format_ist_time(entry_time),
            "entry_price": entry_price,
            "current_price": current_price,
            "current_p_l": round_points(current_pl),
            "exit_time_ist": exit_time,
            "exit_price": exit_price,
            "best_p_l": round_points(best_points),
            "score": score,
            "quality": quality,
        })

    for item in active_attempts:
        append_item(item, completed=False)
    for item in completed_attempts:
        append_item(item, completed=True)

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "IGNORE": 3}
    rows.sort(
        key=lambda row: (
            priority_order.get(str(row.get("priority")), 9),
            str(row.get("signal") or ""),
        )
    )
    return rows


def build_and_store_levels(
    database,
    historical,
    instrument_key: str,
    selected_date: date,
    dates: tuple[date, ...],
) -> int:
    """Read historical data, compute levels, and persist to DB."""
    from red_bar_lab.strategy.level_engine import build_daily_levels

    current = historical.read_day(instrument_key, selected_date, interval_minutes=1)
    previous_dates = [day for day in dates if day < selected_date][-10:]
    previous = [
        (day, historical.read_day(instrument_key, day, interval_minutes=1))
        for day in previous_dates
    ]
    levels = build_daily_levels(selected_date, current, previous, previous_days=10)
    all_levels = list(levels.previous_day_levels)
    all_levels.extend(
        level
        for level in (
            levels.first_candle,
            levels.next_red_candle,
            levels.mid_session_candle,
        )
        if level is not None
    )
    return database.replace_reference_levels(
        instrument_key, selected_date.isoformat(), all_levels
    )
