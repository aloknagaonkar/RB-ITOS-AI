from __future__ import annotations

from functools import wraps
from pathlib import Path

import streamlit as st

from red_bar_lab.storage.database import RedBarDatabase


OBSERVATIONAL_QUERY_TTL_SECONDS = 30


def _open_database(database_path: str) -> RedBarDatabase:
    database = RedBarDatabase(Path(database_path))
    database.initialize()
    return database


@st.cache_data(ttl=OBSERVATIONAL_QUERY_TTL_SECONDS, show_spinner=False)
def read_option_chain_history_cached(
    database_path: str,
    instrument_key: str,
    start_date: str,
    end_date: str,
    limit: int = 500,
):
    """Cache stored option-chain history used as supporting evidence."""
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
    read_option_chain_history_cached.clear()
    read_reference_levels_cached.clear()
