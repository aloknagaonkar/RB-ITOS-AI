import sqlite3
from types import SimpleNamespace

from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot
from red_bar_lab.ui.red_bar_v2_live_runtime import resolve_red_bar_v2_live_state


def _database(path, *, include_reference: bool = True):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE paper_signal_diagnostics (
                id INTEGER PRIMARY KEY,
                signal_id TEXT,
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
            "INSERT INTO paper_signal_diagnostics VALUES (1,?,?,?,?,?,?,?,?,?)",
            (
                "RBV2-CURRENT",
                "BEARISH",
                "2026-08-21T10:29:00+05:30",
                60.0,
                "NIFTY-PE",
                80.0,
                "WAIT",
                "OBSERVATION_ONLY",
                "2026-08-21T10:30:00+05:30",
            ),
        )
        conn.execute(
            "INSERT INTO signal_pipeline_status VALUES (?,?,?,?,?,?,?,?)",
            (
                "RBV2-CURRENT",
                "2026-08-21",
                1,
                1,
                1,
                1,
                1,
                "2026-08-21T10:30:00+05:30",
            ),
        )
        if include_reference:
            conn.execute(
                "INSERT INTO reference_levels VALUES (1,?,?,?,?,?,?,?,?)",
                (
                    "NSE_INDEX|Nifty 50",
                    "2026-08-21",
                    "NEXT_RED_CANDLE",
                    "2026-08-21T09:22:00+05:30",
                    24300.0,
                    24240.0,
                    24270.0,
                    "VALID",
                ),
            )
        conn.commit()
    return SimpleNamespace(path=path)


def _stale_snapshot():
    return RedBarV2UISnapshot(
        direction="BULLISH",
        option_side="CE",
        trend_strength="CONFIRMED",
        reversal_status="REVERSAL_ADMITTED",
        provisional_confirmed_state="CONFIRMED",
        midpoint_confirmation="BULLISH_CONFIRMED",
        midpoint_aligned=True,
        trade_status="ACTIVE",
        trade_id="RBV2-STALE-0002",
    )


def test_missing_reference_suppresses_stale_strategy_and_trade_fields(tmp_path):
    resolved, diagnostics = resolve_red_bar_v2_live_state(
        _database(tmp_path / "lab.db", include_reference=False),
        _stale_snapshot(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
    )

    assert resolved.reference_status == "REFERENCE_NOT_READY"
    assert resolved.directional_state == "REFERENCE_NOT_READY"
    assert resolved.direction == "BEARISH"
    assert resolved.option_side == "PE"
    assert resolved.trend_strength is None
    assert resolved.reversal_status == "NOT_EVALUATED"
    assert resolved.provisional_confirmed_state == "NOT_EVALUATED"
    assert resolved.midpoint_confirmation == "NOT_EVALUATED"
    assert resolved.midpoint_aligned is None
    assert resolved.trade_status == "NO_MATCHING_ACTIVE_TRADE"
    assert resolved.trade_id is None
    assert diagnostics.state_coherent is False
    assert "REFERENCE_REQUIRED_FOR_STRATEGY_STATE" in diagnostics.state_conflicts
    assert "midpoint_confirmation" in diagnostics.stale_fields_suppressed


def test_opposite_midpoint_confirmation_is_suppressed(tmp_path):
    resolved, diagnostics = resolve_red_bar_v2_live_state(
        _database(tmp_path / "lab.db", include_reference=True),
        _stale_snapshot(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
    )

    assert resolved.reference_status == "REFERENCE_READY"
    assert resolved.direction == "BEARISH"
    assert resolved.option_side == "PE"
    assert resolved.midpoint_confirmation == "NOT_EVALUATED"
    assert resolved.reversal_status == "NOT_EVALUATED"
    assert resolved.trade_status == "NO_MATCHING_ACTIVE_TRADE"
    assert diagnostics.state_coherent is False
    assert diagnostics.state_conflicts == ("DIRECTION_MIDPOINT_CONFLICT",)


def test_coherent_snapshot_retains_current_strategy_fields(tmp_path):
    current = RedBarV2UISnapshot(
        direction="BEARISH",
        option_side="PE",
        trend_strength="CONFIRMED",
        reversal_status="REVERSAL_ADMITTED",
        provisional_confirmed_state="CONFIRMED",
        midpoint_confirmation="BEARISH_CONFIRMED",
        midpoint_aligned=True,
        trade_status="FLAT",
    )
    resolved, diagnostics = resolve_red_bar_v2_live_state(
        _database(tmp_path / "lab.db", include_reference=True),
        current,
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-21",
    )

    assert diagnostics.state_coherent is True
    assert diagnostics.state_conflicts == ()
    assert diagnostics.stale_fields_suppressed == ()
    assert resolved.trend_strength == "CONFIRMED"
    assert resolved.midpoint_confirmation == "BEARISH_CONFIRMED"
    assert resolved.reversal_status == "REVERSAL_ADMITTED"
    assert resolved.trade_status == "FLAT"
