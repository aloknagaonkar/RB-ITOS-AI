import sqlite3
from types import SimpleNamespace

from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot
from red_bar_lab.ui.red_bar_v2_live_runtime import resolve_red_bar_v2_live_state


def _database(tmp_path):
    path = tmp_path / "runtime.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE paper_signal_diagnostics (
                id INTEGER PRIMARY KEY,
                signal_id TEXT,
                trading_date TEXT,
                direction TEXT,
                confirmation_timestamp TEXT,
                signal_age_seconds REAL,
                best_candidate TEXT,
                best_score REAL,
                final_decision TEXT,
                reason TEXT,
                timestamp TEXT
            );
            CREATE TABLE signal_pipeline_status (
                signal_id TEXT,
                trading_date TEXT,
                market_context_ready INTEGER,
                volume_structure_ready INTEGER,
                options_context_ready INTEGER,
                core_eligible INTEGER,
                hybrid_eligible INTEGER,
                updated_at TEXT
            );
            CREATE TABLE reference_levels (
                id INTEGER PRIMARY KEY,
                instrument_key TEXT,
                trading_date TEXT,
                level_type TEXT,
                source_timestamp TEXT,
                source_high REAL,
                source_low REAL,
                midpoint REAL,
                data_quality TEXT
            );
            CREATE TABLE paper_monitor_status (
                current_state TEXT,
                last_decision TEXT,
                last_reason TEXT,
                heartbeat_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE execution_state_events (
                signal_id TEXT,
                state TEXT,
                detail TEXT,
                timestamp TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO paper_signal_diagnostics VALUES (1,?,?,?,?,?,?,?,?,?,?)",
            (
                "RBV2-CURRENT",
                "2026-08-20",
                "BEARISH",
                "2026-08-20T09:31:00+05:30",
                86.49,
                "NIFTY 24200 PE 25 AUG 26",
                100.0,
                "WAIT",
                "FOREGROUND_COMMITTEE_APPROVED=0; CANDIDATES=5",
                "2026-08-20T09:32:26+05:30",
            ),
        )
        conn.execute(
            "INSERT INTO signal_pipeline_status VALUES (?,?,?,?,?,?,?,?)",
            ("RBV2-CURRENT", "2026-08-20", 1, 1, 1, 1, 1, "2026-08-20T09:32:16+05:30"),
        )
        conn.execute(
            "INSERT INTO reference_levels VALUES (1,?,?,?,?,?,?,?,?)",
            (
                "NSE_INDEX|Nifty 50",
                "2026-08-20",
                "FIRST_CANDLE",
                "2026-08-20T09:15:00+05:30",
                24225.45,
                24189.30,
                24207.375,
                "VALID",
            ),
        )
        conn.execute(
            "INSERT INTO paper_monitor_status VALUES (?,?,?,?,?)",
            (
                "WAITING_FOR_V2_SIGNAL",
                "WAIT",
                "FOREGROUND_COMMITTEE_APPROVED=0; CANDIDATES=5",
                "2026-08-20T09:32:19+05:30",
                "2026-08-20T09:32:19+05:30",
            ),
        )
        conn.execute(
            "INSERT INTO execution_state_events VALUES (?,?,?,?)",
            (
                "RBV2-CURRENT",
                "EXECUTION_COMMITTEE",
                "decision=WAIT; reason=OPPORTUNITY_TERMINAL[BEARISH_EMA10_LOST]",
                "2026-08-20T09:32:17+05:30",
            ),
        )
        conn.commit()
    return SimpleNamespace(path=path)


def test_current_day_runtime_overlays_stale_file_snapshot(tmp_path):
    stale = RedBarV2UISnapshot(
        reference_status="REFERENCE_NOT_READY",
        alignment_status="BLOCKED",
        directional_state="REFERENCE_NOT_READY",
    )

    resolved, diagnostics = resolve_red_bar_v2_live_state(
        _database(tmp_path),
        stale,
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-20",
    )

    assert resolved.reference_status == "REFERENCE_READY"
    assert resolved.reference_high == 24225.45
    assert resolved.reference_low == 24189.30
    assert resolved.reference_midpoint == 24207.375
    assert resolved.alignment_status == "ALIGNED"
    assert resolved.directional_state == "ACTIVE_SIGNAL"
    assert resolved.direction == "BEARISH"
    assert resolved.option_side == "PE"
    assert resolved.admission_allowed is None
    assert resolved.admission_code == "WAIT"
    assert diagnostics.signal_id == "RBV2-CURRENT"
    assert diagnostics.terminal_condition == "BEARISH_EMA10_LOST"
    assert diagnostics.market_context_ready is True
    assert diagnostics.options_context_ready is True


def test_missing_current_day_signal_preserves_original_snapshot(tmp_path):
    database = _database(tmp_path)
    original = RedBarV2UISnapshot(reference_status="REFERENCE_NOT_READY")

    resolved, diagnostics = resolve_red_bar_v2_live_state(
        database,
        original,
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
    )

    assert resolved is original
    assert diagnostics.source_status == "NO_CURRENT_DAY_SIGNAL"
