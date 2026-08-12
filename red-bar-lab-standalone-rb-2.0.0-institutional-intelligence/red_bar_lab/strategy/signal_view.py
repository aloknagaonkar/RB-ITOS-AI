from __future__ import annotations
from collections import defaultdict
from red_bar_lab.strategy.trade_outcome import (
    summarize_actionable_models,
    benchmark_summary,
)

SHORT_PREFIXES = {
    "NEXT_RED_CANDLE": "NRC",
    "FIRST_CANDLE": "FC",
    "MID_SESSION_1245": "MS",
}

def sequence_signal_attempts(rows):
    ordered = sorted(
        rows,
        key=lambda r: (
            str(r.get("cross_timestamp") or ""),
            str(r.get("confirmation_timestamp") or ""),
            str(r.get("signal_id") or ""),
        ),
    )
    counters = defaultdict(int)
    out = []
    for source in ordered:
        item = dict(source)
        level = str(item.get("level_type") or "UNKNOWN")
        counters[level] += 1
        seq = counters[level]
        item["signal_sequence"] = seq
        item["signal_label"] = f"{level}_{seq}"
        short = SHORT_PREFIXES.get(level)
        if short is None:
            short = level.replace("_315", "").replace("_", "")[:6]
        item["signal_marker"] = f"{short}-{seq}"
        out.append(item)
    return out

def summarize_completed_signals(
    signal_rows,
    trade_rows,
    current_price=None,
):
    sequenced = sequence_signal_attempts(signal_rows)
    signal_by_id = {
        str(r.get("signal_id")): r
        for r in sequenced if r.get("signal_id")
    }

    grouped = defaultdict(list)
    for row in trade_rows:
        if row.get("signal_id"):
            grouped[str(row["signal_id"])].append(row)

    summaries = []

    for signal_id, rows in grouped.items():
        signal = signal_by_id.get(signal_id)
        if signal is None:
            continue

        actionable = summarize_actionable_models(rows)
        if actionable["signal_lifecycle"] != "COMPLETED":
            continue

        benchmark = benchmark_summary(
            rows,
            current_price=current_price,
            direction=signal.get("direction"),
            entry_price=signal.get("underlying_entry"),
        )

        completion_timestamps = [
            str(r.get("exit_timestamp"))
            for r in rows
            if r.get("exit_timestamp")
            and str(r.get("exit_model")) != "EOD_HOLD"
        ]
        completed_at = (
            max(completion_timestamps)
            if completion_timestamps else None
        )

        mfe_values = [
            float(r["session_mfe_points"])
            for r in rows
            if str(r.get("exit_model")) != "EOD_HOLD"
            and r.get("session_mfe_points") is not None
        ]
        mae_values = [
            float(r["session_mae_points"])
            for r in rows
            if str(r.get("exit_model")) != "EOD_HOLD"
            and r.get("session_mae_points") is not None
        ]

        summaries.append({
            "signal_id": signal_id,
            "signal_label": signal.get("signal_label"),
            "signal_marker": signal.get("signal_marker"),
            "signal_sequence": signal.get("signal_sequence"),
            "level_type": signal.get("level_type"),
            "direction": signal.get("direction"),
            "entry_timestamp": signal.get("confirmation_timestamp"),
            "entry_price": signal.get("underlying_entry"),
            **actionable,
            "quality_explanation": quality_explanation(
                actionable["actionable_success"],
                actionable["actionable_failed"],
                actionable["actionable_breakeven"],
            ),
            "actionable_score": actionable_score(
                actionable["actionable_success"],
                10,
            ),
            "quality_band": quality_band(
                actionable["actionable_success"]
            ),
            "quality_symbol": quality_symbol(
                actionable["actionable_success"]
            ),
            "priority": priority_label(actionable["actionable_success"]),
            "trade_status": trader_status(
                actionable["signal_lifecycle"],
                benchmark.get("benchmark_status"),
            ),
            "current_result": current_result(
                benchmark.get("benchmark_current_points")
            ),
            "mfe_points": max(mfe_values) if mfe_values else None,
            "mae_points": max(mae_values) if mae_values else None,
            **benchmark,
            "completed_at": completed_at,
        })

    summaries.sort(
        key=lambda r: (
            str(r.get("completed_at") or ""),
            str(r.get("signal_label") or ""),
        )
    )
    return summaries



def quality_explanation(
    success: int,
    failed: int,
    breakeven: int,
) -> str:
    return f"{success}W / {failed}L / {breakeven}BE"


def actionable_score(success: int, total: int = 10) -> str:
    return f"{success}/{total}"


def quality_band(success: int) -> str:
    if success >= 9:
        return "GREEN"
    if success >= 6:
        return "YELLOW"
    if success >= 3:
        return "ORANGE"
    return "RED"


def quality_symbol(success: int) -> str:
    if success >= 9:
        return "🟢"
    if success >= 6:
        return "🟡"
    if success >= 3:
        return "🟠"
    return "🔴"



def trader_status(signal_lifecycle, benchmark_status) -> str:
    lifecycle = str(signal_lifecycle or "")
    benchmark = str(benchmark_status or "")
    if lifecycle == "COMPLETED" and benchmark == "RUNNING":
        return "BENCHMARK_RUNNING"
    if lifecycle == "COMPLETED" and benchmark == "CLOSED":
        return "CLOSED"
    if lifecycle == "COMPLETED":
        return "ACTIONABLE_DONE"
    if lifecycle in {"TRADE_OPEN", "ACTIVE"}:
        return "ACTIVE"
    return lifecycle or "WAITING"


def current_result(points) -> str:
    if points is None:
        return "UNKNOWN"
    value = float(points)
    if value > 0:
        return "PROFIT"
    if value < 0:
        return "LOSS"
    return "BREAKEVEN"


def priority_label(success: int) -> str:
    if success >= 9:
        return "HIGH"
    if success >= 6:
        return "MEDIUM"
    if success >= 3:
        return "LOW"
    return "IGNORE"
