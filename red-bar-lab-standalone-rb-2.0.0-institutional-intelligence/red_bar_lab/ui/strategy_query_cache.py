from __future__ import annotations

from functools import wraps
from pathlib import Path
import sqlite3

import streamlit as st

from red_bar_lab.storage.database import RedBarDatabase


OBSERVATIONAL_QUERY_TTL_SECONDS = 30


def _open_database(database_path: str) -> RedBarDatabase:
    database = RedBarDatabase(Path(database_path))
    database.initialize()
    return database


@st.cache_data(ttl=OBSERVATIONAL_QUERY_TTL_SECONDS, show_spinner=False)
def read_latest_option_chain_snapshot_cached(
    database_path: str,
    instrument_key: str,
    trading_date: str,
    limit: int = 100,
):
    """Return only rows belonging to the latest stored snapshot timestamp.

    This query is intentionally confined to the read-only strategy-page cache
    adapter. It does not alter the core database facade or any collection,
    contract-selection, execution, position, or risk-control workflow.
    """
    database = _open_database(database_path)
    with sqlite3.connect(database.path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM option_chain_snapshot_history
            WHERE instrument_key=?
              AND trading_date=?
              AND snapshot_timestamp=(
                  SELECT MAX(snapshot_timestamp)
                  FROM option_chain_snapshot_history
                  WHERE instrument_key=?
                    AND trading_date=?
              )
            ORDER BY option_expiry, id
            LIMIT ?
            """,
            (
                instrument_key,
                trading_date,
                instrument_key,
                trading_date,
                int(limit),
            ),
        ).fetchall()
    return [dict(row) for row in rows]


@st.cache_data(ttl=OBSERVATIONAL_QUERY_TTL_SECONDS, show_spinner=False)
def read_option_chain_history_cached(
    database_path: str,
    instrument_key: str,
    start_date: str,
    end_date: str,
    limit: int = 500,
):
    """Cache the legacy option-history reader used as a compatibility fallback."""
    database = _open_database(database_path)
    return database.read_option_chain_history(
        instrument_key,
        start_date,
        end_date,
        limit=limit,
    )


@st.cache_data(ttl=OBSERVATIONAL_QUERY_TTL_SECONDS, show_spinner=False)
def read_reference_levels_cached(
    database_path: str,
    instrument_key: str,
    trading_date: str,
):
    """Cache persisted reference-level reads used by read-only strategy UI."""
    database = _open_database(database_path)
    return database.read_reference_levels(instrument_key, trading_date)


class StrategyObservationalDatabaseProxy:
    """Delegate all database behavior except approved observational reads."""

    def __init__(self, database, database_path: str):
        self._database = database
        self._database_path = str(database_path)

    def __getattr__(self, name: str):
        return getattr(self._database, name)

    def read_latest_option_chain_snapshot(
        self,
        instrument_key: str,
        trading_date: str,
        limit: int = 100,
    ):
        return read_latest_option_chain_snapshot_cached(
            self._database_path,
            instrument_key,
            trading_date,
            limit,
        )

    def read_option_chain_history(
        self,
        instrument_key: str,
        start_date: str,
        end_date: str,
        limit: int = 500,
    ):
        return read_option_chain_history_cached(
            self._database_path,
            instrument_key,
            start_date,
            end_date,
            limit,
        )

    def read_reference_levels(self, instrument_key: str, trading_date: str):
        return read_reference_levels_cached(
            self._database_path,
            instrument_key,
            trading_date,
        )


def build_strategy_query_cache_wrapper(render_page):
    """Install observational caching without changing page implementations."""

    @wraps(render_page)
    def wrapped(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    ):
        cached_database = StrategyObservationalDatabaseProxy(
            database,
            str(settings.database_path),
        )
        return render_page(
            settings,
            layout,
            cached_database,
            token,
            underlying_name,
            instrument_key,
            interval,
        )

    return wrapped


def clear_strategy_observational_query_cache() -> None:
    """Explicit invalidation hook for future write-capable workflows."""
    read_latest_option_chain_snapshot_cached.clear()
    read_option_chain_history_cached.clear()
    read_reference_levels_cached.clear()
