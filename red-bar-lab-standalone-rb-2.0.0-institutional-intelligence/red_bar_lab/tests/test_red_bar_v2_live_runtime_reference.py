import sqlite3

from red_bar_lab.ui.red_bar_v2_live_runtime import (
    REFERENCE_LEVEL_TYPE,
    resolve_red_bar_v2_live_state,
)


class _Database:
    def __init__(self, path):
        self.path = path


def _create_runtime_db(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE paper_signal_diagnostics (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                trading_date TEXT,
                signal_id TEXT NOT NULL,
                direction TEXT,
                confirmation_timestamp TEXT,
                signal_age_seconds REAL,
                final_decision TEXT,
                reason TEXT,
                best_candidate TEXT,
                best_score REAL
            );
            CREATE TABLE signal_pipeline_status (
                signal_id TEXT NOT NULL,
                trading_date TEXT NOT NULL,
                updated_at TEXT,
                market_context_ready INTEGER,
                volume_structure_ready INTEGER,
                options_context_ready INTEGER,
                core_eligible INTEGER,
                hybrid_eligible INTEGER
            );
            CREATE TABLE reference_levels (
                id INTEGER PRIMARY KEY,
                instrument_key TEXT NOT NULL,
                trading_date TEXT NOT NULL,
                level_type TEXT NOT NULL,
                source_timestamp TEXT,
                source_high REAL,
                source_low REAL,
                midpoint REAL,
                level_value REAL,
                data_quality TEXT
            );
            CREATE TABLE paper_monitor_status (
                updated_at TEXT,
                heartbeat_at TEXT,
                current_state TEXT,
                last_decision TEXT,
                last_reason TEXT
            );
            CREATE TABLE execution_state_events (
                signal_id TEXT,
                state TEXT,
                timestamp TEXT,
                detail TEXT
            );
            """
        )
        connection.execute(
            """INSERT INTO paper_signal_diagnostics
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "2026-08-21T10:30:00+05:30",
                "2026-08-21",
                "RBV2-TEST",
                "BULLISH",
                "2026-08-21T10:29:00+05:30",
                60.0,
                "WAIT",
                "OBSERVATION_ONLY",
                "NIFTY-CE",
                80.0,
            ),
        )
        connection.execute(
            """INSERT INTO signal_pipeline_status
               VALUES (?, ?, ?, 1, 1, 1, 1, 1)""",
            (
                "RBV2-TEST",
                "2026-08-21",
                "2026-08-21T10:30:00+05:30",
            ),
        )
        connection.execute(
            """INSERT INTO reference_levels
               VALUES (1, ?, ?, 'FIRST_CANDLE', ?, 24200, 24150, 24175, 24175, 'VALID')""",
            (
                "NSE_INDEX|Nifty 50",
                "2026-08-21",
                "2026-08-21T09:15:00+05:30",
            ),
        )
        connection.execute(
            """INSERT INTO reference_levels
               VALUES (2, ?, ?, ?, ?, 24300, 24240, 24270, 24270, 'VALID')""",
            (
                "NSE_INDEX|Nifty 50",
                "2026-08-21",
                REFERENCE_LEVEL_TYPE,
                "2026-08-21T09:22:00+05:30",
            ),
        )
        connection.commit()


def test_live_runtime_uses_next_red_candle_reference(tmp_path):
    path = tmp_path / "lab.db"
    _create_runtime_db(path)

    snapshot, diagnostics = resolve_red_bar_v2_live_state(
        _Database(path),
        None,
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
    )

    assert snapshot is not None
    assert snapshot.reference_status == "REFERENCE_READY"
    assert snapshot.reference_high == 24300
    assert snapshot.reference_low == 24240
    assert snapshot.reference_midpoint == 24270
    assert snapshot.alignment_status == "ALIGNED"
    assert diagnostics.reference_level_type == "NEXT_RED_CANDLE"
    assert diagnostics.reference_found is True
    assert diagnostics.reference_data_quality == "VALID"
    assert diagnostics.alignment_blocking_reasons == ()


def test_live_runtime_explains_missing_reference(tmp_path):
    path = tmp_path / "lab.db"
    _create_runtime_db(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "DELETE FROM reference_levels WHERE level_type='NEXT_RED_CANDLE'"
        )
        connection.commit()

    snapshot, diagnostics = resolve_red_bar_v2_live_state(
        _Database(path),
        None,
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
    )

    assert snapshot is not None
    assert snapshot.reference_status == "REFERENCE_NOT_READY"
    assert snapshot.alignment_status == "BLOCKED"
    assert diagnostics.reference_found is False
    assert diagnostics.alignment_blocking_reasons == (
        "NEXT_RED_CANDLE_REFERENCE_NOT_FOUND",
    )
