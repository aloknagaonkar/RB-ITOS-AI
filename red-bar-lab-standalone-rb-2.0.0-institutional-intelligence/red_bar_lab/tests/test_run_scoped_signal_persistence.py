from __future__ import annotations

import sqlite3

from red_bar_lab.services.run_scoped_signal_persistence import (
    replace_run_scoped_signal_rows,
)


_SCHEMA = """
CREATE TABLE signal_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    level_type TEXT NOT NULL,
    level_value REAL NOT NULL,
    direction TEXT,
    state TEXT NOT NULL,
    cross_timestamp TEXT,
    confirmation_timestamp TEXT,
    underlying_entry REAL,
    cross_open REAL,
    cross_high REAL,
    cross_low REAL,
    cross_close REAL,
    confirmation_open REAL,
    confirmation_high REAL,
    confirmation_low REAL,
    confirmation_close REAL,
    confirmation_delay_minutes INTEGER,
    created_at TEXT NOT NULL
);
"""


def _row(signal_id: str, level: float) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "level_type": "RED_BAR_V2",
        "level_value": level,
        "direction": "BULLISH",
        "state": "ACTIVE",
        "cross_timestamp": "2026-08-21T09:25:00+05:30",
        "confirmation_timestamp": "2026-08-21T09:30:00+05:30",
    }


def test_replacement_is_scoped_to_run_owner(tmp_path):
    database_path = tmp_path / "signals.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(_SCHEMA)

    replace_run_scoped_signal_rows(
        database_path,
        run_id="RBV2-PAPER-RUNTIME",
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
        rows=[_row("RBV2-1", 24200.0), _row("RBV2-2", 24225.0)],
    )
    replace_run_scoped_signal_rows(
        database_path,
        run_id="LIVE_MONITOR",
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
        rows=[_row("RB-1", 24150.0)],
    )

    result = replace_run_scoped_signal_rows(
        database_path,
        run_id="LIVE_MONITOR",
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
        rows=[_row("RB-2", 24175.0)],
    )

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT run_id, signal_id FROM signal_attempts ORDER BY run_id, signal_id"
        ).fetchall()

    assert result.deleted_count == 1
    assert result.inserted_count == 1
    assert rows == [
        ("LIVE_MONITOR", "RB-2"),
        ("RBV2-PAPER-RUNTIME", "RBV2-1"),
        ("RBV2-PAPER-RUNTIME", "RBV2-2"),
    ]


def test_rejects_missing_owner_or_signal_identity(tmp_path):
    database_path = tmp_path / "signals.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(_SCHEMA)

    try:
        replace_run_scoped_signal_rows(
            database_path,
            run_id="",
            instrument_key="NSE_INDEX|Nifty 50",
            trading_date="2026-08-21",
            rows=[],
        )
    except ValueError as exc:
        assert str(exc) == "run_id is required"
    else:
        raise AssertionError("missing run_id must fail closed")

    try:
        replace_run_scoped_signal_rows(
            database_path,
            run_id="LIVE_MONITOR",
            instrument_key="NSE_INDEX|Nifty 50",
            trading_date="2026-08-21",
            rows=[{"level_type": "RED_BAR_V2"}],
        )
    except ValueError as exc:
        assert str(exc) == "signal_id is required for every signal row"
    else:
        raise AssertionError("missing signal_id must fail closed")
