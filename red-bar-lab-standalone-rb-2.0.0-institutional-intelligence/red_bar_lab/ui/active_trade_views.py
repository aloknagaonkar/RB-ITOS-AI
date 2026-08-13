from __future__ import annotations

from datetime import datetime
from functools import wraps
import sqlite3
from zoneinfo import ZoneInfo

import streamlit as st


ARCHIVED_STATUSES = {"ARCHIVED", "DUPLICATE", "DUPLICATE_TRADE"}


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
def render_live_trade_exit_activity(database) -> None:
    """Read-only live panels; does not run committee, entry, or exit engines."""
    rows = list(database.read_paper_execution_orders("PAPER-STD") or [])
    open_rows = [
        row for row in rows
        if str(row.get("status") or "").upper() == "OPEN"
    ]
    closed_rows = [
        row for row in rows
        if str(row.get("status") or "").upper() == "CLOSED"
    ]
    closed_rows.sort(
        key=lambda row: str(row.get("exit_timestamp") or ""),
        reverse=True,
    )

    st.markdown("### Live Trade & Exit Activity")
    c1, c2, c3 = st.columns(3)
    c1.metric("Open Trades", len(open_rows))
    c2.metric("Closed Trades", len(closed_rows))
    c3.metric("Refresh", "5 seconds")

    st.markdown("#### Current Trades")
    if open_rows:
        st.dataframe(open_rows, width="stretch", hide_index=True)
    else:
        st.caption("No open paper trades.")

    st.markdown("#### Latest Exits")
    if closed_rows:
        st.dataframe(closed_rows[:25], width="stretch", hide_index=True)
    else:
        st.caption("No closed paper trades yet.")


@_fragment("10s")
def render_live_rank_and_queue(database, trading_date: str) -> None:
    """Refresh rank and queue using persisted database rows only."""
    st.markdown("### Live Rank & Execution Queue")

    try:
        ranking = list(
            database.read_trade_selection_evaluations(
                trading_date=trading_date,
                limit=500,
            )
            or []
        )
    except TypeError:
        ranking = list(
            database.read_trade_selection_evaluations(limit=500) or []
        )

    ranking = [row for row in ranking if not _is_duplicate(row)]
    ranking.sort(
        key=lambda row: (
            float(row.get("selection_score") or 0.0),
            float(row.get("candidate_score") or 0.0),
        ),
        reverse=True,
    )

    try:
        queue = list(database.read_execution_queue(limit=500) or [])
    except TypeError:
        queue = list(database.read_execution_queue() or [])
    queue = [row for row in queue if not _is_duplicate(row)]

    st.markdown("#### Active Top 5")
    if ranking:
        st.dataframe(ranking[:5], width="stretch", hide_index=True)
    else:
        st.caption("No active ranked candidates.")

    st.markdown("#### Active Queue")
    if queue:
        st.dataframe(queue[:50], width="stretch", hide_index=True)
    else:
        st.caption("No active execution queue items.")

    st.caption(
        "Database-only refresh: this panel does not execute candidate, "
        "committee, entry, or exit logic."
    )


def build_paper_page_wrapper(original):
    """Inject duplicate-safe reads and append authoritative live panels."""

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
        result = original(
            settings,
            layout,
            proxy,
            token,
            underlying_name,
            instrument_key,
            interval,
        )
        trading_date = (
            datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        )
        render_live_trade_exit_activity(proxy)
        render_live_rank_and_queue(proxy, trading_date)
        return result

    return wrapper
