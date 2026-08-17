from __future__ import annotations

import sqlite3

from red_bar_lab.storage.database import RedBarDatabase
from red_bar_lab.ui import strategy_option_context, strategy_query_cache


def _insert_snapshot(
    database_path,
    *,
    snapshot_key,
    instrument_key,
    trading_date,
    expiry,
    timestamp,
    call_oi,
):
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            INSERT INTO option_chain_snapshot_history(
                snapshot_key,instrument_key,trading_date,option_expiry,
                snapshot_timestamp,collector_mode,total_call_oi,
                created_at,updated_at
            ) VALUES(?,?,?,?,?,'ONLINE',?,?,?)
            """,
            (
                snapshot_key,
                instrument_key,
                trading_date,
                expiry,
                timestamp,
                call_oi,
                timestamp,
                timestamp,
            ),
        )
        conn.commit()


def test_latest_snapshot_query_preserves_latest_timestamp_rows_only(tmp_path):
    database_path = tmp_path / "red_bar.db"
    RedBarDatabase(database_path).initialize()

    _insert_snapshot(
        database_path,
        snapshot_key="old-near",
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-17",
        expiry="2026-08-20",
        timestamp="2026-08-17T10:00:00+05:30",
        call_oi=100,
    )
    _insert_snapshot(
        database_path,
        snapshot_key="new-near",
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-17",
        expiry="2026-08-20",
        timestamp="2026-08-17T10:05:00+05:30",
        call_oi=200,
    )
    _insert_snapshot(
        database_path,
        snapshot_key="new-far",
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-17",
        expiry="2026-08-27",
        timestamp="2026-08-17T10:05:00+05:30",
        call_oi=300,
    )
    _insert_snapshot(
        database_path,
        snapshot_key="other-instrument",
        instrument_key="NSE_INDEX|Nifty Bank",
        trading_date="2026-08-17",
        expiry="2026-08-20",
        timestamp="2026-08-17T10:10:00+05:30",
        call_oi=999,
    )
    _insert_snapshot(
        database_path,
        snapshot_key="other-date",
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-18",
        expiry="2026-08-20",
        timestamp="2026-08-18T10:10:00+05:30",
        call_oi=888,
    )

    strategy_query_cache.read_latest_option_chain_snapshot_cached.clear()
    rows = strategy_query_cache.read_latest_option_chain_snapshot_cached(
        str(database_path),
        "NSE_INDEX|Nifty 50",
        "2026-08-17",
        100,
    )

    assert [row["snapshot_key"] for row in rows] == ["new-near", "new-far"]
    assert {row["snapshot_timestamp"] for row in rows} == {
        "2026-08-17T10:05:00+05:30"
    }
    assert {row["total_call_oi"] for row in rows} == {200.0, 300.0}


def test_latest_snapshot_query_returns_empty_for_missing_scope(tmp_path):
    database_path = tmp_path / "red_bar.db"
    RedBarDatabase(database_path).initialize()

    strategy_query_cache.read_latest_option_chain_snapshot_cached.clear()
    assert strategy_query_cache.read_latest_option_chain_snapshot_cached(
        str(database_path),
        "NSE_INDEX|Nifty 50",
        "2026-08-17",
        100,
    ) == []


def test_option_context_prefers_latest_reader():
    class Database:
        def __init__(self):
            self.latest_calls = []
            self.history_calls = []

        def read_latest_option_chain_snapshot(self, instrument_key, trading_date, limit=100):
            self.latest_calls.append((instrument_key, trading_date, limit))
            return [{
                "snapshot_timestamp": "2026-08-17T10:05:00+05:30",
                "option_expiry": "2026-08-20",
                "total_call_oi": 100,
                "total_put_oi": 150,
                "total_call_oi_change": -10,
                "total_put_oi_change": 20,
            }]

        def read_option_chain_history(self, *args, **kwargs):
            self.history_calls.append((args, kwargs))
            return []

    database = Database()
    result = strategy_option_context.build_option_behaviour_snapshot(
        database,
        "NSE_INDEX|Nifty 50",
        "2026-08-17",
    )

    assert database.latest_calls == [
        ("NSE_INDEX|Nifty 50", "2026-08-17", 100)
    ]
    assert database.history_calls == []
    assert result["directional_bias"] == "BULLISH POSITIONING"


def test_option_context_falls_back_to_legacy_history_reader():
    class Database:
        def __init__(self):
            self.calls = []

        def read_option_chain_history(
            self, instrument_key, date_from, date_to, limit=500
        ):
            self.calls.append((instrument_key, date_from, date_to, limit))
            return [{
                "snapshot_timestamp": "2026-08-17T10:05:00+05:30",
                "option_expiry": "2026-08-20",
                "total_call_oi": 150,
                "total_put_oi": 100,
                "total_call_oi_change": 20,
                "total_put_oi_change": -10,
            }]

    database = Database()
    result = strategy_option_context.build_option_behaviour_snapshot(
        database,
        "NSE_INDEX|Nifty 50",
        "2026-08-17",
    )

    assert database.calls == [
        (
            "NSE_INDEX|Nifty 50",
            "2026-08-17",
            "2026-08-17",
            500,
        )
    ]
    assert result["directional_bias"] == "BEARISH POSITIONING"
