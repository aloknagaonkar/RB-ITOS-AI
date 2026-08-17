from __future__ import annotations

from pathlib import Path

import streamlit as st

from red_bar_lab.storage.database import RedBarDatabase
from red_bar_lab.ui.strategy_option_context import build_option_behaviour_snapshot


OBSERVATIONAL_QUERY_TTL_SECONDS = 30


def _open_database(database_path: str) -> RedBarDatabase:
    database = RedBarDatabase(Path(database_path))
    database.initialize()
    return database


@st.cache_data(ttl=OBSERVATIONAL_QUERY_TTL_SECONDS, show_spinner=False)
def read_option_behaviour_snapshot_cached(
    database_path: str,
    instrument_key: str,
    trading_date: str,
):
    """Cache the read-only aggregate option-behaviour snapshot.

    This wrapper is intentionally limited to observational strategy pages. It
    does not cache open orders, active positions, execution state, risk state,
    or operator controls.
    """
    database = _open_database(database_path)
    return build_option_behaviour_snapshot(database, instrument_key, trading_date)


@st.cache_data(ttl=OBSERVATIONAL_QUERY_TTL_SECONDS, show_spinner=False)
def read_reference_levels_cached(
    database_path: str,
    instrument_key: str,
    trading_date: str,
):
    """Cache persisted reference-level reads used by read-only strategy UI."""
    database = _open_database(database_path)
    return database.read_reference_levels(instrument_key, trading_date)


def clear_strategy_observational_query_cache() -> None:
    """Explicit invalidation hook for future write-capable workflows."""
    read_option_behaviour_snapshot_cached.clear()
    read_reference_levels_cached.clear()
