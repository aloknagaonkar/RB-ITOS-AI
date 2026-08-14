from __future__ import annotations

from datetime import datetime
from functools import wraps
import sqlite3
from zoneinfo import ZoneInfo

import streamlit as st


ARCHIVED_STATUSES = {"ARCHIVED", "DUPLICATE", "DUPLICATE_TRADE"}
ACTIVE_QUEUE_STATUSES = {
    "QUALIFIED",
    "APPROVED",
    "PENDING",
    "EXECUTING",
    "ACTIVE",
}


def _is_duplicate(row: dict[str, object]) -> bool:
    status = str(row.get("status") or row.get("state") or "").upper()
    reason = str(row.get("reason") or "").upper()
    return (
        bool(row.get("duplicate"))
        or status in ARCHIVED_STATUSES
        or "DUPLICATE" in reason
    )


def _fragment(run_every: str):
    fragment = getattr(st, "fragment", None)
    if fragment is None:
        return lambda function: function
    return fragment(run_every=run_every)


def _latest_signal(database, instrument_key: str, trading_date: str):
    try:
        rows = list(
            database.read_signal_attempts(instrument_key, trading_date) or []
        )
    except Exception:
        return None
    confirmed = [
        row
        for row in rows
        if row.get("confirmation_timestamp")
        and str(row.get("direction") or "").upper()
        in {"BULLISH", "BEARISH"}
    ]
    if not confirmed:
        return None
    return max(
        confirmed,
        key=lambda row: str(row.get("confirmation_timestamp") or ""),
    )


def _safe_queue(database) -> list[dict[str, object]]:
    try:
        rows = list(database.read_execution_queue(limit=500) or [])
    except TypeError:
        rows = list(database.read_execution_queue() or [])
    except Exception:
        rows = []
    return [row for row in rows if not _is_duplicate(row)]


def _safe_ranking(
    database,
    trading_date: str,
) -> list[dict[str, object]]:
    try:
        rows = list(
            database.read_trade_selection_evaluations(
                trading_date=trading_date,
                limit=500,
            )
            or []
        )
    except TypeError:
        rows = list(
            database.read_trade_selection_evaluations(limit=500) or []
        )
    except Exception:
        rows = []
    rows = [row for row in rows if not _is_duplicate(row)]
    rows.sort(
        key=lambda row: (
            float(row.get("selection_score") or 0.0),
            float(row.get("candidate_score") or 0.0),
        ),
        reverse=True,
    )
    return rows


def _compact_trade_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "Order": row.get("order_id"),
            "Contract": row.get("tradingsymbol"),
            "Side": row.get("option_type"),
            "Qty": row.get("quantity"),
            "Entry": row.get("entry_price"),
            "Current": row.get("current_price"),
            "P&L": row.get("unrealized_pnl"),
            "Entry Time": row.get("entry_timestamp"),
            "Reason": row.get("entry_reason"),
        }
        for row in rows
    ]


def _compact_exit_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "Order": row.get("order_id"),
            "Contract": row.get("tradingsymbol"),
            "Entry": row.get("entry_price"),
            "Exit": row.get("exit_price"),
            "P&L": row.get("realized_pnl"),
            "Exit Time": row.get("exit_timestamp"),
            "Exit Reason": row.get("exit_reason"),
        }
        for row in rows
    ]


def _compact_rank_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "Rank": row.get("candidate_rank"),
            "Candidate": row.get("candidate_symbol"),
            "Candidate Score": row.get("candidate_score"),
            "Opportunity": row.get("opportunity_score"),
            "TSS": row.get("selection_score"),
            "Execute": "YES" if row.get("eligible") else "NO",
            "Reason": row.get("reason"),
        }
        for row in rows
    ]


def _compact_queue_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "Rank": row.get("candidate_rank"),
            "Candidate": row.get("candidate_symbol"),
            "Direction": row.get("direction"),
            "Status": row.get("status"),
            "Reason": row.get("reason"),
            "Order": row.get("order_id"),
            "Updated": row.get("updated_at"),
        }
        for row in rows
    ]


class ActiveTradeViewDatabaseProxy:
    """Archive duplicate candidates and hide them from all active UI reads."""

    def __init__(self, database) -> None:
        self._database = database
        self._archive_duplicate_rows()

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
                    conn.execute(
                        """
                        UPDATE candidate_lifecycle
                        SET state='ARCHIVED',
                            reason='DUPLICATE_TRADE',
                            action='ARCHIVE'
                        WHERE duplicate=1
                          AND UPPER(COALESCE(state,''))!='ARCHIVED'
                        """
                    )
                except sqlite3.OperationalError:
                    pass

                try:
                    conn.execute(
                        """
                        UPDATE execution_queue
                        SET status='ARCHIVED',
                            reason='DUPLICATE_TRADE',
                            updated_at=?
                        WHERE UPPER(COALESCE(status,''))!='ARCHIVED'
                          AND (
                            UPPER(COALESCE(status,'')) IN
                                ('DUPLICATE','DUPLICATE_TRADE')
                            OR UPPER(COALESCE(reason,'')) LIKE '%DUPLICATE%'
                          )
                        """,
                        (now,),
                    )
                except sqlite3.OperationalError:
                    pass
                conn.commit()
        except Exception:
            return

    def read_candidate_lifecycle(self, *args, **kwargs):
        self._archive_duplicate_rows()
        rows = self._database.read_candidate_lifecycle(*args, **kwargs)
        return [row for row in rows if not _is_duplicate(row)]

    def read_trade_selection_evaluations(self, *args, **kwargs):
        rows = self._database.read_trade_selection_evaluations(*args, **kwargs)
        return [row for row in rows if not _is_duplicate(row)]

    def read_execution_queue(self, *args, **kwargs):
        self._archive_duplicate_rows()
        rows = self._database.read_execution_queue(*args, **kwargs)
        return [row for row in rows if not _is_duplicate(row)]


@_fragment("5s")
def render_trading_overview(
    database,
    instrument_key: str,
    trading_date: str,
) -> None:
    """Compact above-the-fold status sourced only from persisted records."""
    orders = list(database.read_paper_execution_orders("PAPER-STD") or [])
    open_rows = [
        row
        for row in orders
        if str(row.get("status") or "").upper() == "OPEN"
    ]
    closed_rows = [
        row
        for row in orders
        if str(row.get("status") or "").upper() == "CLOSED"
    ]
    queue = _safe_queue(database)
    active_queue = [
        row
        for row in queue
        if str(row.get("status") or "").upper() in ACTIVE_QUEUE_STATUSES
    ]
    signal = _latest_signal(database, instrument_key, trading_date)
    direction = str(signal.get("direction") or "WAIT") if signal else "WAIT"
    action = (
        "LOOK FOR CE"
        if direction == "BULLISH"
        else "LOOK FOR PE"
        if direction == "BEARISH"
        else "WAIT"
    )
    open_pnl = sum(float(row.get("unrealized_pnl") or 0.0) for row in open_rows)
    closed_pnl = sum(float(row.get("realized_pnl") or 0.0) for row in closed_rows)

    st.subheader("Paper Trading")
    st.caption(
        "Operational view · duplicates archived · live data panels refresh "
        "without rerunning Committee or execution logic."
    )
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Direction", direction)
    c2.metric("Action", action)
    c3.metric("Open Trades", len(open_rows))
    c4.metric("Active Queue", len(active_queue))
    c5.metric("Open P&L", f"₹{open_pnl:+,.2f}")
    c6.metric("Closed P&L", f"₹{closed_pnl:+,.2f}")

    if signal:
        st.caption(
            f"Latest signal: {signal.get('signal_id')} · "
            f"confirmed {signal.get('confirmation_timestamp')}"
        )
    else:
        st.caption("No confirmed bullish or bearish signal is stored for today.")


@_fragment("5s")
def render_current_trades(database) -> None:
    rows = list(database.read_paper_execution_orders("PAPER-STD") or [])
    open_rows = [
        row
        for row in rows
        if str(row.get("status") or "").upper() == "OPEN"
    ]
    st.markdown("### Current Trades")
    if open_rows:
        st.dataframe(
            _compact_trade_rows(open_rows),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No open paper trades.")


@_fragment("10s")
def render_candidates_and_queue(database, trading_date: str) -> None:
    ranking = _safe_ranking(database, trading_date)
    queue = _safe_queue(database)
    active_queue = [
        row
        for row in queue
        if str(row.get("status") or "").upper() in ACTIVE_QUEUE_STATUSES
    ]

    st.markdown("### Candidates & Execution Queue")
    rank_tab, queue_tab = st.tabs(["Active Top 5", "Execution Queue"])
    with rank_tab:
        if ranking:
            st.dataframe(
                _compact_rank_rows(ranking[:5]),
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No active ranked candidates.")
    with queue_tab:
        if active_queue:
            st.dataframe(
                _compact_queue_rows(active_queue[:50]),
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No active execution queue items.")


@_fragment("5s")
def render_recent_exits(database) -> None:
    rows = list(database.read_paper_execution_orders("PAPER-STD") or [])
    closed_rows = [
        row
        for row in rows
        if str(row.get("status") or "").upper() == "CLOSED"
    ]
    closed_rows.sort(
        key=lambda row: str(row.get("exit_timestamp") or ""),
        reverse=True,
    )
    st.markdown("### Recent Exits")
    if closed_rows:
        st.dataframe(
            _compact_exit_rows(closed_rows[:20]),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No closed paper trades yet.")


def build_paper_page_wrapper(original):
    """Show a compact operational page and retain legacy detail on demand."""

    @wraps(original)
    def wrapper(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    ):
        proxy = ActiveTradeViewDatabaseProxy(database)
        trading_date = (
            datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        )

        render_trading_overview(proxy, instrument_key, trading_date)
        render_current_trades(proxy)
        render_candidates_and_queue(proxy, trading_date)
        render_recent_exits(proxy)

        with st.expander(
            "Advanced Details & Diagnostics",
            expanded=False,
        ):
            st.caption(
                "Full legacy detail: market health, Red Bar eligibility, "
                "candidate lifecycle, session, Opportunity Health, Performance "
                "Selection, Committee evidence, exit diagnostics and history."
            )
            return original(
                settings,
                layout,
                proxy,
                token,
                underlying_name,
                instrument_key,
                interval,
            )

    return wrapper
