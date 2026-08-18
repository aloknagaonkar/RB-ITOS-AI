from __future__ import annotations

from collections import defaultdict
import math
from typing import Mapping, Sequence

import streamlit as st

from red_bar_lab.ui.strategy_attribution import (
    normalize_strategy_source,
    strategy_label,
)


PERFORMANCE_LEDGER_VERSION = "STRATEGY-PERFORMANCE-LEDGER-V1"


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _metric(row: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = _number(row.get(name))
        if value is not None:
            return value
    return None


def _rank_bucket(value: object) -> str:
    number = _number(value)
    if number is None:
        return "UNAVAILABLE"
    return f"RANK_{int(number)}" if float(number).is_integer() else f"RANK_{number:g}"


def _entry_mode(row: Mapping[str, object]) -> str:
    return str(row.get("entry_mode") or "STANDARD").strip().upper() or "STANDARD"


def _closed_result(pnl: float, epsilon: float) -> str:
    if pnl > epsilon:
        return "WIN"
    if pnl < -epsilon:
        return "LOSS"
    return "BREAKEVEN"


def _aggregate(rows: Sequence[Mapping[str, object]], *, breakeven_epsilon: float) -> dict[str, object]:
    closed = [dict(row) for row in rows if str(row.get("status") or "").upper() == "CLOSED"]
    opened = [dict(row) for row in rows if str(row.get("status") or "").upper() == "OPEN"]

    realized = [float(_metric(row, "realized_pnl", "net_pnl", "pnl") or 0.0) for row in closed]
    wins = [value for value in realized if _closed_result(value, breakeven_epsilon) == "WIN"]
    losses = [value for value in realized if _closed_result(value, breakeven_epsilon) == "LOSS"]
    breakeven = [value for value in realized if _closed_result(value, breakeven_epsilon) == "BREAKEVEN"]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    completed = len(closed)
    decisive = len(wins) + len(losses)
    mfe_values = [
        value for row in closed
        if (value := _metric(row, "mfe_points", "maximum_favourable_excursion", "max_favourable_excursion")) is not None
    ]
    mae_values = [
        value for row in closed
        if (value := _metric(row, "mae_points", "maximum_adverse_excursion", "max_adverse_excursion")) is not None
    ]

    return {
        "total_trades": len(rows),
        "open_trades": len(opened),
        "completed_trades": completed,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate_pct": round(100.0 * len(wins) / decisive, 2) if decisive else None,
        "realized_net_pnl": round(sum(realized), 2),
        "open_pnl": round(sum(float(_metric(row, "unrealized_pnl", "mtm") or 0.0) for row in opened), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "average_win": round(gross_profit / len(wins), 2) if wins else None,
        "average_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
        "expectancy_per_completed_trade": round(sum(realized) / completed, 2) if completed else None,
        "average_mfe_points": round(sum(mfe_values) / len(mfe_values), 2) if mfe_values else None,
        "average_mae_points": round(sum(mae_values) / len(mae_values), 2) if mae_values else None,
        "mfe_sample_size": len(mfe_values),
        "mae_sample_size": len(mae_values),
    }


def build_strategy_performance_ledger(
    orders: Sequence[Mapping[str, object]],
    *,
    breakeven_epsilon: float = 0.01,
) -> dict[str, object]:
    """Build an immutable, strategy-owned paper-performance ledger."""
    copied = [dict(row) for row in orders]
    by_strategy: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in copied:
        by_strategy[normalize_strategy_source(row)].append(row)

    strategy_rows: list[dict[str, object]] = []
    entry_mode_rows: list[dict[str, object]] = []
    rank_rows: list[dict[str, object]] = []

    for source, rows in by_strategy.items():
        strategy_rows.append({
            "strategy_source": source,
            "strategy": strategy_label(source),
            **_aggregate(rows, breakeven_epsilon=breakeven_epsilon),
        })

        modes: dict[str, list[dict[str, object]]] = defaultdict(list)
        ranks: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            modes[_entry_mode(row)].append(row)
            ranks[_rank_bucket(row.get("candidate_rank"))].append(row)
        for mode, mode_rows in modes.items():
            entry_mode_rows.append({
                "strategy_source": source,
                "strategy": strategy_label(source),
                "entry_mode": mode,
                **_aggregate(mode_rows, breakeven_epsilon=breakeven_epsilon),
            })
        for rank, ranked_rows in ranks.items():
            rank_rows.append({
                "strategy_source": source,
                "strategy": strategy_label(source),
                "candidate_rank": rank,
                **_aggregate(ranked_rows, breakeven_epsilon=breakeven_epsilon),
            })

    strategy_rows.sort(key=lambda row: (-int(row["completed_trades"]), str(row["strategy"])))
    entry_mode_rows.sort(key=lambda row: (str(row["strategy"]), -int(row["completed_trades"]), str(row["entry_mode"])))
    rank_rows.sort(key=lambda row: (str(row["strategy"]), str(row["candidate_rank"])))

    return {
        "ledger_version": PERFORMANCE_LEDGER_VERSION,
        "strategy_rows": strategy_rows,
        "entry_mode_rows": entry_mode_rows,
        "candidate_rank_rows": rank_rows,
        "trade_count": len(copied),
        "closed_trade_count": sum(int(row["completed_trades"]) for row in strategy_rows),
        "open_trade_count": sum(int(row["open_trades"]) for row in strategy_rows),
        "source_read_only": True,
        "persisted": False,
        "execution_allowed": False,
    }


def _summary_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [{
        "Strategy": row.get("strategy"),
        "Completed": row.get("completed_trades"),
        "Wins": row.get("wins"),
        "Losses": row.get("losses"),
        "Breakeven": row.get("breakeven"),
        "Win Rate %": row.get("win_rate_pct"),
        "Net P&L": row.get("realized_net_pnl"),
        "Avg Win": row.get("average_win"),
        "Avg Loss": row.get("average_loss"),
        "Profit Factor": row.get("profit_factor"),
        "Expectancy / Trade": row.get("expectancy_per_completed_trade"),
        "Open": row.get("open_trades"),
        "Open P&L": row.get("open_pnl"),
        "Avg MFE": row.get("average_mfe_points"),
        "Avg MAE": row.get("average_mae_points"),
    } for row in rows]


def render_strategy_performance_ledger(result: Mapping[str, object]) -> None:
    st.markdown("### 10B. Strategy-Level Performance Ledger")
    st.caption(
        "Completed outcomes remain owned by their originating strategy. Open P&L is shown separately and is not counted as a win or loss."
    )
    rows = list(result.get("strategy_rows") or [])
    if not rows:
        st.info("No attributed paper trades are available for the performance ledger.")
        return

    st.dataframe(_summary_rows(rows), width="stretch", hide_index=True)
    mode_tab, rank_tab = st.tabs(["Entry Mode", "Candidate Rank"])
    with mode_tab:
        st.dataframe([
            {
                "Strategy": row.get("strategy"),
                "Entry Mode": row.get("entry_mode"),
                "Completed": row.get("completed_trades"),
                "Win Rate %": row.get("win_rate_pct"),
                "Net P&L": row.get("realized_net_pnl"),
                "Profit Factor": row.get("profit_factor"),
                "Expectancy / Trade": row.get("expectancy_per_completed_trade"),
            }
            for row in result.get("entry_mode_rows") or []
        ], width="stretch", hide_index=True)
    with rank_tab:
        st.dataframe([
            {
                "Strategy": row.get("strategy"),
                "Rank": row.get("candidate_rank"),
                "Completed": row.get("completed_trades"),
                "Win Rate %": row.get("win_rate_pct"),
                "Net P&L": row.get("realized_net_pnl"),
                "Profit Factor": row.get("profit_factor"),
                "Expectancy / Trade": row.get("expectancy_per_completed_trade"),
            }
            for row in result.get("candidate_rank_rows") or []
        ], width="stretch", hide_index=True)
    st.write("**Boundary:** read-only aggregation only; no trade, queue, strategy or risk state is changed.")


__all__ = [
    "PERFORMANCE_LEDGER_VERSION",
    "build_strategy_performance_ledger",
    "render_strategy_performance_ledger",
]
