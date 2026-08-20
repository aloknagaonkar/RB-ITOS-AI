import sqlite3
from types import SimpleNamespace

from red_bar_lab.execution.option_telemetry_lifecycle import (
    derive_persisted_option_indicators,
    read_option_telemetry_lifecycle,
    record_active_telemetry_snapshot,
)


def _seed(database, prices):
    with sqlite3.connect(database.path) as conn:
        conn.execute(
            """
            CREATE TABLE option_execution_telemetry (
                order_id TEXT,
                observed_timestamp TEXT,
                current_price REAL,
                volume REAL
            )
            """
        )
        for index, price in enumerate(prices):
            conn.execute(
                "INSERT INTO option_execution_telemetry VALUES (?, ?, ?, ?)",
                ("O1", f"2026-08-20T10:{index:02d}:00+05:30", price, 100 + index * 10),
            )
        conn.commit()


def test_persisted_indicator_derivation_and_lifecycle_storage(tmp_path):
    database = SimpleNamespace(path=tmp_path / "indicators.db")
    prices = [100 + index for index in range(16)]
    _seed(database, prices)

    indicators = derive_persisted_option_indicators(database, "O1")
    assert indicators["option_vwap"] is not None
    assert indicators["option_rsi14"] == 100.0
    assert indicators["indicator_source"] == "PERSISTED_OPTION_TELEMETRY"

    assert record_active_telemetry_snapshot(
        database,
        "O1",
        {"observed_timestamp": "2026-08-20T10:16:00+05:30", "pcr_oi": 1.2, "delta": -0.4},
    )
    lifecycle = read_option_telemetry_lifecycle(database, "O1")
    assert lifecycle["entry"]["option_vwap"] is not None
    assert lifecycle["entry"]["option_rsi14"] == 100.0


def test_insufficient_history_leaves_rsi_unavailable(tmp_path):
    database = SimpleNamespace(path=tmp_path / "short.db")
    _seed(database, [100, 101, 102])
    indicators = derive_persisted_option_indicators(database, "O1")
    assert indicators["option_vwap"] is not None
    assert indicators["option_rsi14"] is None
