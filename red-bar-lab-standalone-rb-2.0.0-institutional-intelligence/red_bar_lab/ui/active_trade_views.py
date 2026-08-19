from __future__ import annotations

from datetime import datetime
from functools import wraps
import sqlite3
from zoneinfo import ZoneInfo

import streamlit as st

from red_bar_lab.ui.strategy_attribution import (
    build_strategy_attribution,
    build_strategy_performance_summary,
)
from red_bar_lab.ui.strategy_performance_ledger import (
    build_strategy_performance_ledger,
    render_strategy_performance_ledger,
)


ARCHIVED_STATUSES = {"ARCHIVED", "DUPLICATE", "DUPLICATE_TRADE"}
ACTIVE_QUEUE_STATUSES = {"QUALIFIED", "APPROVED", "PENDING", "EXECUTING", "ACTIVE"}


def _is_duplicate(row: dict[str, object]) -> bool:
    status = str(row.get("status") or row.get("state") or "").upper()
    reason = str(row.get("reason") or "").upper()
    return bool(row.get("duplicate")) or status in ARCHIVED_STATUSES or "DUPLICATE" in reason


def _fragment(run_every: str):
    fragment = getattr(st, "fragment", None)
    return (lambda function: function) if fragment is None else fragment(run_every=run_every)


def _latest_signal(database, instrument_key: str, trading_date: str):
    try:
        rows = list(database.read_signal_attempts(instrument_key, trading_date) or [])
    except Exception:
        return None
    confirmed = [
        row for row in rows
        if row.get("confirmation_timestamp")
        and str(row.get("direction") or "").upper() in {"BULLISH", "BEARISH"}
    ]
    return max(confirmed, key=lambda row: str(row.get("confirmation_timestamp") or "")) if confirmed else None


def _safe_queue(database) -> list[dict[str, object]]:
    try:
        rows = list(database.read_execution_queue(limit=500) or [])
    except TypeError:
        rows = list(database.read_execution_queue() or [])
    except Exception:
        rows = []
    return [dict(row) for row in rows if not _is_duplicate(dict(row))]


def _safe_ranking(database, trading_date: str) -> list[dict[str, object]]:
    try:
        rows = list(database.read_trade_selection_evaluations(trading_date=trading_date, limit=500) or [])
    except TypeError:
        rows = list(database.read_trade_selection_evaluations(limit=500) or [])
    except Exception:
        rows = []
    rows = [dict(row) for row in rows if not _is_duplicate(dict(row))]
    rows.sort(
        key=lambda row: (float(row.get("selection_score") or 0.0), float(row.get("candidate_score") or 0.0)),
        reverse=True,
    )
    return rows


def _row_identity(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("signal_id") or ""),
        str(row.get("candidate_id") or ""),
        str(row.get("candidate_symbol") or row.get("tradingsymbol") or ""),
    )


def _active_ranking_from_queue(
    ranking: list[dict[str, object]],
    active_queue: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not active_queue:
        return []
    queue_signal_ids = {str(row.get("signal_id") or "") for row in active_queue if row.get("signal_id")}
    queue_candidate_ids = {str(row.get("candidate_id") or "") for row in active_queue if row.get("candidate_id")}
    queue_symbols = {
        str(row.get("candidate_symbol") or row.get("tradingsymbol") or "")
        for row in active_queue
        if row.get("candidate_symbol") or row.get("tradingsymbol")
    }
    filtered = []
    for row in ranking:
        signal_id, candidate_id, symbol = _row_identity(row)
        matches = (
            (candidate_id and candidate_id in queue_candidate_ids)
            or (signal_id and signal_id in queue_signal_ids and (not queue_symbols or symbol in queue_symbols))
            or (symbol and symbol in queue_symbols)
        )
        if matches and bool(row.get("eligible")):
            filtered.append(row)
    deduped: dict[tuple[str, str], dict[str, object]] = {}
    for row in filtered:
        signal_id, _, symbol = _row_identity(row)
        current = deduped.get((signal_id, symbol))
        if current is None or float(row.get("selection_score") or 0.0) > float(current.get("selection_score") or 0.0):
            deduped[(signal_id, symbol)] = row
    result = list(deduped.values())
    result.sort(
        key=lambda row: (float(row.get("selection_score") or 0.0), float(row.get("candidate_score") or 0.0)),
        reverse=True,
    )
    return result


def _safe_checkpoint(database, order: dict[str, object]):
    horizon = int(order.get("evaluation_horizon_minutes") or 0)
    order_id = str(order.get("order_id") or "")
    if not order_id or horizon <= 0:
        return None
    try:
        return database.read_paper_trade_checkpoint(order_id=order_id, horizon_minutes=horizon)
    except Exception:
        return None


def _safe_latest_telemetry(database, order_id: str):
    try:
        return database.read_latest_option_execution_telemetry(order_id)
    except Exception:
        return None


def _attribution(database, order: dict[str, object]) -> dict[str, object]:
    return build_strategy_attribution(
        order,
        _safe_checkpoint(database, order),
        _safe_latest_telemetry(database, str(order.get("order_id") or "")),
    )


def _attributed_orders(database, orders: list[dict[str, object]]) -> list[dict[str, object]]:
    result = []
    for raw in orders:
        order = dict(raw)
        result.append({**order, "_attribution": _attribution(database, order)})
    return result


def _compact_trade_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result = []
    for row in rows:
        item = dict(row.get("_attribution") or {})
        result.append({
            "Order": row.get("order_id"),
            "Strategy": item.get("strategy"),
            "Signal": item.get("signal_id"),
            "Role": item.get("entry_role"),
            "Contract": row.get("tradingsymbol"),
            "Side": row.get("option_type"),
            "Qty": row.get("quantity"),
            "Entry": row.get("entry_price"),
            "Current": row.get("current_price"),
            "P&L": row.get("unrealized_pnl"),
            "Entry Mode": item.get("entry_mode"),
            "Rank": item.get("candidate_rank"),
            "Probability %": item.get("execution_probability_pct"),
            "Opened By": item.get("opened_by"),
            "Support": item.get("supporting_intelligence_text"),
            "Entry Time": row.get("entry_timestamp"),
        })
    return result


def _compact_exit_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result = []
    for row in rows:
        item = dict(row.get("_attribution") or {})
        result.append({
            "Order": row.get("order_id"),
            "Strategy": item.get("strategy"),
            "Signal": item.get("signal_id"),
            "Contract": row.get("tradingsymbol"),
            "Entry": row.get("entry_price"),
            "Exit": row.get("exit_price"),
            "P&L": row.get("realized_pnl"),
            "Exit Policy Owner": item.get("exit_policy_owner"),
            "Exit Mode": item.get("exit_mode"),
            "Exit Time": row.get("exit_timestamp"),
            "Exit Reason": row.get("exit_reason"),
        })
    return result


def _compact_rank_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{
        "Rank": row.get("candidate_rank"),
        "Candidate": row.get("candidate_symbol"),
        "Candidate Score": row.get("candidate_score"),
        "Opportunity": row.get("opportunity_score"),
        "TSS": row.get("selection_score"),
        "Execute": "YES" if row.get("eligible") else "NO",
        "Reason": row.get("reason"),
    } for row in rows]


def _compact_queue_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{
        "Strategy Source": row.get("execution_strategy_source") or "UNATTRIBUTED",
        "Signal": row.get("signal_id"),
        "Rank": row.get("candidate_rank"),
        "Candidate": row.get("candidate_symbol"),
        "Direction": row.get("direction"),
        "Entry Mode": row.get("entry_mode"),
        "Status": row.get("status"),
        "Reason": row.get("reason"),
        "Order": row.get("order_id"),
        "Updated": row.get("updated_at"),
    } for row in rows]


class ActiveTradeViewDatabaseProxy:
    """Archive duplicate candidates and hide them from active UI reads."""

    def __init__(self, database) -> None:
        self._database = database

    def __getattr__(self, name: str):
        return getattr(self._database, name)

    def _archive_duplicate_rows(self) -> None:
        path = getattr(self._database, "path", None)
        if path is None:
            return
        now = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
        try:
            with sqlite3.connect(path) as conn:
                try:
                    conn.execute("""
                        UPDATE candidate_lifecycle
                        SET state='ARCHIVED', reason='DUPLICATE_TRADE', action='ARCHIVE'
                        WHERE duplicate=1 AND UPPER(COALESCE(state,''))!='ARCHIVED'
                    """)
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("""
                        UPDATE execution_queue
                        SET status='ARCHIVED', reason='DUPLICATE_TRADE', updated_at=?
                        WHERE UPPER(COALESCE(status,''))!='ARCHIVED'
                          AND (UPPER(COALESCE(status,'')) IN ('DUPLICATE','DUPLICATE_TRADE')
                               OR UPPER(COALESCE(reason,'')) LIKE '%DUPLICATE%')
                    """, (now,))
                except sqlite3.OperationalError:
                    pass
                conn.commit()
        except Exception:
            return

    def read_candidate_lifecycle(self, *args, **kwargs):
        return [row for row in self._database.read_candidate_lifecycle(*args, **kwargs) if not _is_duplicate(row)]

    def read_trade_selection_evaluations(self, *args, **kwargs):
        return [row for row in self._database.read_trade_selection_evaluations(*args, **kwargs) if not _is_duplicate(row)]

    def read_execution_queue(self, *args, **kwargs):
        return [row for row in self._database.read_execution_queue(*args, **kwargs) if not _is_duplicate(row)]


@_fragment("5s")
def render_trading_overview(database, instrument_key: str, trading_date: str) -> None:
    orders = [dict(row) for row in (database.read_paper_execution_orders("PAPER-STD") or [])]
    open_rows = [row for row in orders if str(row.get("status") or "").upper() == "OPEN"]
    closed_rows = [row for row in orders if str(row.get("status") or "").upper() == "CLOSED"]
    active_queue = [row for row in _safe_queue(database) if str(row.get("status") or "").upper() in ACTIVE_QUEUE_STATUSES]
    signal = _latest_signal(database, instrument_key, trading_date)
    direction = str(signal.get("direction") or "WAIT") if signal else "WAIT"
    action = "LOOK FOR CE" if direction == "BULLISH" else "LOOK FOR PE" if direction == "BEARISH" else "WAIT"
    open_pnl = sum(float(row.get("unrealized_pnl") or 0.0) for row in open_rows)
    closed_pnl = sum(float(row.get("realized_pnl") or 0.0) for row in closed_rows)

    st.subheader("Paper Trading")
    st.caption("Operational view · duplicates hidden from display · live panels refresh without rerunning Committee or execution logic.")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Direction", direction)
    c2.metric("Action", action)
    c3.metric("Open Trades", len(open_rows))
    c4.metric("Active Queue", len(active_queue))
    c5.metric("Open P&L", f"INR {open_pnl:+,.2f}")
    c6.metric("Closed P&L", f"INR {closed_pnl:+,.2f}")
    st.caption(
        f"Latest signal: {signal.get('signal_id')} · confirmed {signal.get('confirmation_timestamp')}"
        if signal else "No confirmed bullish or bearish signal is stored for today."
    )


@_fragment("5s")
def render_current_trades(database) -> None:
    rows = [dict(row) for row in (database.read_paper_execution_orders("PAPER-STD") or [])]
    open_rows = [row for row in rows if str(row.get("status") or "").upper() == "OPEN"]
    st.markdown("### Current Trades")
    st.caption("Primary strategy and supporting intelligence are shown separately. Support does not become strategy ownership.")
    if open_rows:
        st.dataframe(_compact_trade_rows(_attributed_orders(database, open_rows)), width="stretch", hide_index=True)
    else:
        st.info("No open paper trades.")


@_fragment("5s")
def render_strategy_attribution(database) -> None:
    orders = [dict(row) for row in (database.read_paper_execution_orders("PAPER-STD") or [])]
    orders.sort(key=lambda row: str(row.get("entry_timestamp") or ""), reverse=True)
    st.markdown("### Strategy Attribution & Provenance")
    st.caption("Read-only attribution of primary strategy, signal lineage, queue executor, support layers and exit-policy ownership.")
    if not orders:
        st.info("No paper trades recorded yet.")
        return

    summary = build_strategy_performance_summary(orders)
    st.dataframe([{
        "Strategy": row.get("strategy"),
        "Open": row.get("open_trades"),
        "Closed": row.get("closed_trades"),
        "Open P&L": round(float(row.get("open_pnl") or 0.0), 2),
        "Closed P&L": round(float(row.get("closed_pnl") or 0.0), 2),
        "Total": row.get("total_trades"),
    } for row in summary], width="stretch", hide_index=True)

    for item in [_attribution(database, row) for row in orders[:20]]:
        with st.expander(f"{item['strategy']} · {item['contract'] or 'Unknown contract'} · {item['order_id']}", expanded=False):
            st.write({
                "Primary strategy": item["strategy"],
                "Strategy source": item["strategy_source"],
                "Attribution confidence": item["attribution_confidence"],
                "Signal ID": item["signal_id"],
                "Bundle ID": item["bundle_id"],
                "Candidate ID": item["candidate_id"],
                "Entry role": item["entry_role"],
                "Entry mode": item["entry_mode"],
                "Queue source": item["queue_source"],
                "Opened by": item["opened_by"],
                "Supporting intelligence": item["supporting_intelligence_text"],
                "Candidate rank": item["candidate_rank"],
                "Candidate score": item["candidate_score"],
                "Selection score": item["selection_score"],
                "Execution probability %": item["execution_probability_pct"],
                "Expected value %": item["expected_value_pct"],
                "Exit policy owner": item["exit_policy_owner"],
                "Exit policy": item["exit_policy"],
                "Exit mode": item["exit_mode"],
                "Checkpoint": item["checkpoint_detail"],
                "Option/OI telemetry": item["telemetry_detail"],
                "Telemetry authority": item["telemetry_authority"],
            })


@_fragment("5s")
def render_performance_ledger(database) -> None:
    orders = [dict(row) for row in (database.read_paper_execution_orders("PAPER-STD") or [])]
    result = build_strategy_performance_ledger(orders)
    render_strategy_performance_ledger(result)


@_fragment("10s")
def render_candidates_and_queue(database, trading_date: str) -> None:
    active_queue = [row for row in _safe_queue(database) if str(row.get("status") or "").upper() in ACTIVE_QUEUE_STATUSES]
    ranking = _active_ranking_from_queue(_safe_ranking(database, trading_date), active_queue)
    st.markdown("### Candidates & Execution Queue")
    rank_tab, queue_tab = st.tabs(["Active Top 5", "Execution Queue"])
    with rank_tab:
        if ranking:
            st.dataframe(_compact_rank_rows(ranking[:5]), width="stretch", hide_index=True)
        else:
            st.caption("No candidates are attached to an active execution queue item. Historical rankings remain under Advanced Details & Diagnostics.")
    with queue_tab:
        if active_queue:
            st.dataframe(_compact_queue_rows(active_queue[:50]), width="stretch", hide_index=True)
        else:
            st.caption("No active execution queue items.")


@_fragment("5s")
def render_recent_exits(database) -> None:
    rows = [dict(row) for row in (database.read_paper_execution_orders("PAPER-STD") or [])]
    closed_rows = [row for row in rows if str(row.get("status") or "").upper() == "CLOSED"]
    closed_rows.sort(key=lambda row: str(row.get("exit_timestamp") or ""), reverse=True)
    st.markdown("### Recent Exits")
    if closed_rows:
        st.dataframe(_compact_exit_rows(_attributed_orders(database, closed_rows[:20])), width="stretch", hide_index=True)
    else:
        st.caption("No closed paper trades yet.")


def build_paper_page_wrapper(original):
    """Show compact attributed operations and retain legacy detail on demand."""

    @wraps(original)
    def wrapper(settings, layout, database, token, underlying_name, instrument_key, interval):
        proxy = ActiveTradeViewDatabaseProxy(database)
        trading_date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        render_trading_overview(proxy, instrument_key, trading_date)
        render_current_trades(proxy)
        render_strategy_attribution(proxy)
        render_performance_ledger(proxy)
        render_candidates_and_queue(proxy, trading_date)
        render_recent_exits(proxy)
        with st.expander("Advanced Details & Diagnostics", expanded=False):
            st.caption(
                "Full legacy detail: market health, Red Bar eligibility, candidate lifecycle, session, Opportunity Health, Performance Selection, Committee evidence, exit diagnostics and history."
            )
            return original(settings, layout, proxy, token, underlying_name, instrument_key, interval)

    return wrapper


__all__ = [
    "ActiveTradeViewDatabaseProxy",
    "build_paper_page_wrapper",
    "render_trading_overview",
    "render_current_trades",
    "render_strategy_attribution",
    "render_performance_ledger",
    "render_candidates_and_queue",
    "render_recent_exits",
]
