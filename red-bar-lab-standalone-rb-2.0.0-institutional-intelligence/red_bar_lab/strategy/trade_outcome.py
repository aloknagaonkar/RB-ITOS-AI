from __future__ import annotations

from collections import defaultdict

ACTIONABLE_EXIT_MODELS = {
    "FIXED_TARGET",
    "RISK_REWARD",
    "TRAILING_STOP",
    "BREAK_EVEN_1R",
}
BENCHMARK_EXIT_MODEL = "EOD_HOLD"



def classify_trade_result(points) -> str:
    if points is None:
        return "UNKNOWN"
    value = float(points)
    if value > 0:
        return "WIN"
    if value < 0:
        return "LOSS"
    return "BREAKEVEN"


def decorate_trade_row(row: dict[str, object]) -> dict[str, object]:
    result = dict(row)
    points = row.get("points")
    result["trade_result"] = classify_trade_result(points)
    result["trade_success"] = classify_trade_success(points)
    result["points_gained"] = (
        round(float(points), 2) if points is not None else None
    )
    return result


def summarize_signal_trade_models(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        signal_id = row.get("signal_id")
        if signal_id:
            groups[str(signal_id)].append(row)

    summaries: list[dict[str, object]] = []
    for signal_id, signal_rows in groups.items():
        decorated = [decorate_trade_row(row) for row in signal_rows]
        winners = [row for row in decorated if row["trade_result"] == "WIN"]
        losers = [row for row in decorated if row["trade_result"] == "LOSS"]
        breakeven = [
            row for row in decorated if row["trade_result"] == "BREAKEVEN"
        ]
        unknown = [row for row in decorated if row["trade_result"] == "UNKNOWN"]
        points = [
            float(row["points"])
            for row in decorated
            if row.get("points") is not None
        ]
        open_models = sum(
            1 for row in decorated if str(row.get("status")) == "OPEN"
        )
        closed_models = sum(
            1 for row in decorated if str(row.get("status")) == "CLOSED"
        )

        lifecycle = (
            "TRADE_OPEN"
            if open_models > 0
            else "COMPLETED"
            if decorated and closed_models == len(decorated)
            else "ACTIVE"
        )

        sample = decorated[0]
        summaries.append(
            {
                "signal_id": signal_id,
                "level_type": sample.get("level_type"),
                "direction": sample.get("direction"),
                "entry_timestamp": sample.get("entry_timestamp"),
                "entry_price": sample.get("entry_price"),
                "trade_models": len(decorated),
                "open_models": open_models,
                "closed_models": closed_models,
                "winning_models": len(winners),
                "losing_models": len(losers),
                "breakeven_models": len(breakeven),
                "unknown_models": len(unknown),
                "win_rate_pct": (
                    len(winners)
                    / max(1, len(winners) + len(losers) + len(breakeven))
                    * 100.0
                ),
                "best_points": max(points) if points else None,
                "worst_points": min(points) if points else None,
                "net_model_points": sum(points) if points else None,
                "signal_lifecycle": lifecycle,
            }
        )

    summaries.sort(
        key=lambda row: (
            str(row.get("entry_timestamp") or ""),
            str(row.get("signal_id") or ""),
        )
    )
    return summaries



def classify_trade_success(points) -> str:
    """Business-friendly result label for the UI."""
    result = classify_trade_result(points)
    if result == "WIN":
        return "SUCCESS"
    if result == "LOSS":
        return "FAILED"
    if result == "BREAKEVEN":
        return "BREAKEVEN"
    return "UNKNOWN"



def is_actionable_trade(row: dict[str, object]) -> bool:
    return str(row.get("exit_model") or "") in ACTIONABLE_EXIT_MODELS


def is_benchmark_trade(row: dict[str, object]) -> bool:
    return str(row.get("exit_model") or "") == BENCHMARK_EXIT_MODEL


def actionable_trade_rows(rows):
    return [row for row in rows if is_actionable_trade(row)]


def benchmark_trade_rows(rows):
    return [row for row in rows if is_benchmark_trade(row)]


def summarize_actionable_models(rows):
    models = actionable_trade_rows(rows)
    decorated = [decorate_trade_row(row) for row in models]

    successes = [r for r in decorated if r["trade_result"] == "WIN"]
    failures = [r for r in decorated if r["trade_result"] == "LOSS"]
    breakevens = [r for r in decorated if r["trade_result"] == "BREAKEVEN"]
    unknown = [r for r in decorated if r["trade_result"] == "UNKNOWN"]
    open_models = [r for r in decorated if r.get("status") == "OPEN"]
    closed_models = [r for r in decorated if r.get("status") == "CLOSED"]

    points = [
        float(r["points"])
        for r in decorated
        if r.get("points") is not None
    ]
    total_closed_evaluable = (
        len(successes) + len(failures) + len(breakevens)
    )
    success_rate = (
        len(successes) / total_closed_evaluable * 100.0
        if total_closed_evaluable else 0.0
    )

    if len(closed_models) == 10 and len(open_models) == 0:
        lifecycle = "COMPLETED"
    elif open_models:
        lifecycle = "TRADE_OPEN"
    else:
        lifecycle = "ACTIVE"

    if lifecycle != "COMPLETED":
        quality = "IN_PROGRESS"
    elif success_rate >= 90 and not failures:
        quality = "STRONG_SUCCESS"
    elif success_rate >= 60:
        quality = "SUCCESS"
    elif success_rate >= 35:
        quality = "MIXED"
    elif successes:
        quality = "WEAK"
    elif breakevens and not failures:
        quality = "BREAKEVEN"
    else:
        quality = "FAILED"

    evaluated_models = [
        r for r in decorated if r.get("points") is not None
    ]
    best = (
        max(
            evaluated_models,
            key=lambda r: float(r["points"]),
        )
        if evaluated_models
        else None
    )
    worst = (
        min(
            evaluated_models,
            key=lambda r: float(r["points"]),
        )
        if evaluated_models
        else None
    )

    return {
        "actionable_total": len(models),
        "actionable_open": len(open_models),
        "actionable_closed": len(closed_models),
        "actionable_success": len(successes),
        "actionable_failed": len(failures),
        "actionable_breakeven": len(breakevens),
        "actionable_unknown": len(unknown),
        "actionable_success_rate_pct": round(success_rate, 1),
        "best_actionable_points": max(points) if points else None,
        "worst_actionable_points": min(points) if points else None,
        "best_actionable_exit": (
            f"{best.get('exit_model')} {best.get('model_parameter')}"
            if best else None
        ),
        "best_actionable_exit_time": best.get("exit_timestamp") if best else None,
        "best_actionable_exit_price": best.get("exit_price") if best else None,
        "worst_actionable_exit": (
            f"{worst.get('exit_model')} {worst.get('model_parameter')}"
            if worst else None
        ),
        "worst_actionable_exit_time": worst.get("exit_timestamp") if worst else None,
        "worst_actionable_exit_price": worst.get("exit_price") if worst else None,
        "actionable_completed_at": (
            max(
                (
                    str(row.get("exit_timestamp"))
                    for row in closed_models
                    if row.get("exit_timestamp")
                ),
                default=None,
            )
            if lifecycle == "COMPLETED"
            else None
        ),
        "signal_lifecycle": lifecycle,
        "signal_quality": quality,
    }


def benchmark_summary(rows, current_price=None, direction=None, entry_price=None):
    bench = benchmark_trade_rows(rows)
    if not bench:
        return {
            "benchmark_status": "NOT_AVAILABLE",
            "benchmark_current_points": None,
            "benchmark_final_points": None,
            "benchmark_mfe": None,
            "benchmark_mae": None,
        }

    row = bench[0]
    status = str(row.get("status") or "UNKNOWN")
    final_points = (
        float(row["points"]) if row.get("points") is not None else None
    )

    current_points = final_points
    if status == "OPEN" and current_price is not None and entry_price is not None:
        entry = float(entry_price)
        current = float(current_price)
        if direction == "BULLISH":
            current_points = current - entry
        elif direction == "BEARISH":
            current_points = entry - current

    return {
        "benchmark_status": (
            "RUNNING" if status == "OPEN"
            else "CLOSED" if status == "CLOSED"
            else status
        ),
        "benchmark_current_points": (
            round(float(current_points), 2)
            if current_points is not None else None
        ),
        "benchmark_final_points": (
            round(float(final_points), 2)
            if status == "CLOSED" and final_points is not None
            else None
        ),
        "benchmark_exit_time": row.get("exit_timestamp"),
        "benchmark_exit_price": row.get("exit_price"),
        "benchmark_mfe": row.get("session_mfe_points"),
        "benchmark_mae": row.get("session_mae_points"),
    }
