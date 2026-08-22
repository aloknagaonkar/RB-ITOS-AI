from __future__ import annotations

from datetime import datetime
import sqlite3

from red_bar_lab.storage import RedBarDatabase
from red_bar_lab.strategy.models import Direction, SignalAttempt, SignalState


def _attempt(level_type: str, minute: int) -> SignalAttempt:
    return SignalAttempt(
        state=SignalState.ACTIVE,
        direction=Direction.BULLISH,
        level_type=level_type,
        level_value=24200.0 + minute,
        cross_timestamp=datetime.fromisoformat(
            f"2026-08-21T09:{minute:02d}:00+05:30"
        ),
        confirmation_timestamp=datetime.fromisoformat(
            f"2026-08-21T09:{minute + 1:02d}:00+05:30"
        ),
        underlying_entry=24210.0,
    )


def test_red_bar_database_preserves_other_run_rows(tmp_path):
    database = RedBarDatabase(tmp_path / "red_bar.db")
    database.initialize()

    database.replace_signal_attempts(
        "RBV2-PAPER-RUNTIME",
        "NSE_INDEX|Nifty 50",
        "2026-08-21",
        [_attempt("RED_BAR_V2", 20)],
    )
    database.replace_signal_attempts(
        "LIVE_MONITOR",
        "NSE_INDEX|Nifty 50",
        "2026-08-21",
        [_attempt("FIRST_CANDLE", 25)],
    )
    database.replace_signal_attempts(
        "LIVE_MONITOR",
        "NSE_INDEX|Nifty 50",
        "2026-08-21",
        [_attempt("NEXT_RED_CANDLE", 30)],
    )

    with sqlite3.connect(database.path) as connection:
        rows = connection.execute(
            """
            SELECT run_id, level_type
            FROM signal_attempts
            ORDER BY run_id, level_type
            """
        ).fetchall()
        index_names = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(signal_attempts)"
            ).fetchall()
        }

    assert rows == [
        ("LIVE_MONITOR", "NEXT_RED_CANDLE"),
        ("RBV2-PAPER-RUNTIME", "RED_BAR_V2"),
    ]
    assert "idx_signal_attempts_run_session" in index_names
