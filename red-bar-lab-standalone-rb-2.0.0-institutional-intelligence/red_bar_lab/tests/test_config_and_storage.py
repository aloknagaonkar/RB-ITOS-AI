from red_bar_lab.config import RedBarSettings
from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.storage.database import RedBarDatabase


def test_red_bar_artifacts_are_separate(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    layout = ArtifactLayout(settings)
    layout.ensure()
    assert settings.database_path.parent.exists()
    assert settings.historical_root.exists()
    assert "market_lake" not in str(settings.artifacts_root)


def test_database_initializes(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    database = RedBarDatabase(settings.database_path)
    assert database.health()["ok"] is True


def test_signal_attempts_round_trip(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from red_bar_lab.strategy.models import Direction, SignalAttempt, SignalState

    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    database = RedBarDatabase(settings.database_path)
    stamp = datetime(2026, 8, 5, 9, 25, tzinfo=ZoneInfo("Asia/Kolkata"))
    attempt = SignalAttempt(
        state=SignalState.ACTIVE,
        direction=Direction.BULLISH,
        level_type="PD1_315",
        level_value=100.0,
        cross_timestamp=stamp,
        cross_open=99.0,
        cross_high=103.0,
        cross_low=98.0,
        cross_close=102.0,
        confirmation_timestamp=stamp,
        confirmation_open=102.0,
        confirmation_high=105.0,
        confirmation_low=101.0,
        confirmation_close=104.0,
        underlying_entry=104.0,
    )
    assert database.replace_signal_attempts(
        "RUN1", "NIFTY", "2026-08-05", [attempt]
    ) == 1
    rows = database.read_signal_attempts("NIFTY", "2026-08-05")
    assert rows[0]["state"] == "ACTIVE"
    assert rows[0]["underlying_entry"] == 104.0


def test_signal_replay_is_idempotent_across_run_ids(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from red_bar_lab.strategy.models import Direction, SignalAttempt, SignalState

    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    database = RedBarDatabase(settings.database_path)
    stamp = datetime(2026, 8, 5, 10, 55, tzinfo=ZoneInfo("Asia/Kolkata"))
    attempt = SignalAttempt(
        state=SignalState.ACTIVE,
        direction=Direction.BULLISH,
        level_type="NEXT_RED_CANDLE",
        level_value=24631.6,
        cross_timestamp=stamp,
        confirmation_timestamp=stamp,
        underlying_entry=24647.95,
    )
    database.replace_signal_attempts("RUN1", "NIFTY", "2026-08-05", [attempt])
    first = database.read_signal_attempts("NIFTY", "2026-08-05")
    database.replace_signal_attempts("RUN2", "NIFTY", "2026-08-05", [attempt])
    second = database.read_signal_attempts("NIFTY", "2026-08-05")
    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["signal_id"] == second[0]["signal_id"]


def test_database_supports_rb05_signal_columns(tmp_path):
    import sqlite3
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    database = RedBarDatabase(settings.database_path)
    database.initialize()
    with sqlite3.connect(settings.database_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(signal_attempts)")}
    assert "confirmation_delay_minutes" in columns


def test_paper_trade_replay_is_idempotent(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from red_bar_lab.strategy.trade_models import (
        ExitReason,
        PaperTradeOutcome,
        TradeStatus,
    )

    ist = ZoneInfo("Asia/Kolkata")
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    database = RedBarDatabase(settings.database_path)
    from red_bar_lab.strategy.trade_models import ExitModel
    outcome = PaperTradeOutcome(
        trade_id="TRD-1",
        signal_id="SIG-1",
        instrument_key="NIFTY",
        trading_date="2026-08-05",
        level_type="FIRST_CANDLE",
        direction="BULLISH",
        entry_timestamp=datetime(2026,8,5,9,26,tzinfo=ist),
        entry_price=100,
        stop_price=95,
        risk_points=5,
        exit_model=ExitModel.FIXED_TARGET,
        model_parameter="20pt",
        target_points=20,
        target_price=120,
        exit_timestamp=datetime(2026,8,5,9,30,tzinfo=ist),
        exit_price=120,
        exit_reason=ExitReason.TARGET,
        status=TradeStatus.CLOSED,
        points=20,
        r_multiple=4,
        mfe=22,
        mae=2,
        holding_minutes=4,
        session_mfe_points=25,
        session_mae_points=2,
        session_extreme_price=125,
        session_extreme_timestamp=datetime(2026,8,5,9,35,tzinfo=ist),
        move_after_target_points=5,
        minutes_from_target_to_extreme=5,
        giveback_from_extreme_points=3,
    )
    database.replace_paper_trade_outcomes(
        "NIFTY", "2026-08-05", (outcome,)
    )
    first = database.read_paper_trade_outcomes("NIFTY", "2026-08-05")
    database.replace_paper_trade_outcomes(
        "NIFTY", "2026-08-05", (outcome,)
    )
    second = database.read_paper_trade_outcomes("NIFTY", "2026-08-05")
    assert len(first) == len(second) == 1


def test_rb066_database_backup_is_created_once(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    database = RedBarDatabase(settings.database_path)
    database.initialize()

    # Put a durable value in the original DB before the first patched startup.
    import sqlite3
    with sqlite3.connect(settings.database_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO strategy_runs(
                run_id, mode, started_at, status, parameters_json
            ) VALUES('BEFORE_PATCH','TEST','2026-08-07T09:00:00','COMPLETE','{}')"""
        )
        conn.commit()

    backup = settings.database_path.with_name(
        f"{settings.database_path.stem}.pre_RB_0_6_6"
        f"{settings.database_path.suffix}"
    )
    if backup.exists():
        backup.unlink()

    database.initialize()
    assert backup.exists()

    with sqlite3.connect(backup) as conn:
        row = conn.execute(
            "SELECT run_id FROM strategy_runs WHERE run_id='BEFORE_PATCH'"
        ).fetchone()
    assert row == ("BEFORE_PATCH",)

    first_mtime = backup.stat().st_mtime_ns
    database.initialize()
    assert backup.stat().st_mtime_ns == first_mtime



def test_update_signal_state_api_exists_and_updates_row(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from red_bar_lab.strategy.models import (
        Direction,
        SignalAttempt,
        SignalState,
    )

    ist = ZoneInfo("Asia/Kolkata")
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    database = RedBarDatabase(settings.database_path)

    attempt = SignalAttempt(
        state=SignalState.ACTIVE,
        direction=Direction.BEARISH,
        level_type="NEXT_RED_CANDLE",
        level_value=100.0,
        cross_timestamp=datetime(2026,8,7,10,5,tzinfo=ist),
        confirmation_timestamp=datetime(2026,8,7,10,15,tzinfo=ist),
        underlying_entry=99.0,
        cross_high=101.0,
        cross_low=98.0,
    )

    database.replace_signal_attempts(
        "LIVE_MONITOR",
        "NIFTY",
        "2026-08-07",
        (attempt,),
    )

    rows = database.read_signal_attempts(
        "NIFTY",
        "2026-08-07",
    )
    assert len(rows) == 1

    database.update_signal_state(
        rows[0]["signal_id"],
        "CLOSED",
    )

    updated = database.read_signal_attempts(
        "NIFTY",
        "2026-08-07",
    )
    assert updated[0]["state"] == "CLOSED"



def test_intelligence_range_reader_methods_exist():
    assert hasattr(RedBarDatabase, "read_signal_attempts_range")
    assert hasattr(RedBarDatabase, "read_paper_trade_outcomes_range")



def test_market_context_storage_api_exists():
    assert hasattr(RedBarDatabase, "upsert_market_context_snapshots")
    assert hasattr(RedBarDatabase, "read_market_context_snapshots")



def test_volume_structure_storage_api_exists():
    assert hasattr(RedBarDatabase, "upsert_volume_structure_snapshots")
    assert hasattr(RedBarDatabase, "read_volume_structure_snapshots")



def test_rb074_option_context_storage_api_exists():
    assert hasattr(RedBarDatabase, "upsert_option_context_snapshots")
    assert hasattr(RedBarDatabase, "read_option_context_snapshots")
    assert hasattr(RedBarDatabase, "read_option_context_by_signal")



def test_rb074_option_context_round_trip(tmp_path):
    database = RedBarDatabase(tmp_path / "rb074.db")
    database.initialize()
    row = {
        "signal_id": "RB-OPT-DB",
        "instrument_key": "NSE_INDEX|Nifty 50",
        "trading_date": "2026-08-07",
        "entry_timestamp": "2026-08-07T10:00:00+05:30",
        "option_expiry": "2026-08-13",
        "option_snapshot_timestamp": "2026-08-07T10:01:00+05:30",
        "option_snapshot_delay_seconds": 60.0,
        "entry_aligned": 1,
        "option_spot_price": 25000.0,
        "atm_strike": 25000.0,
        "total_call_oi": 1000.0,
        "total_put_oi": 1200.0,
        "pcr_oi": 1.2,
    }
    assert database.upsert_option_context_snapshots([row]) == 1
    loaded = database.read_option_context_by_signal("RB-OPT-DB")
    assert loaded is not None
    assert loaded["entry_aligned"] == 1
    assert loaded["pcr_oi"] == 1.2
    assert loaded["atm_strike"] == 25000.0



def test_rb0741_dual_collector_storage_apis_exist():
    assert hasattr(RedBarDatabase, "upsert_option_chain_history")
    assert hasattr(RedBarDatabase, "read_option_chain_history")
    assert hasattr(
        RedBarDatabase,
        "find_nearest_pre_entry_option_snapshot",
    )
    assert hasattr(RedBarDatabase, "update_collector_status")
    assert hasattr(RedBarDatabase, "read_collector_status")



def test_rb0742_pipeline_storage_apis_exist():
    assert hasattr(RedBarDatabase, "upsert_signal_pipeline_status")
    assert hasattr(RedBarDatabase, "read_signal_pipeline_status_range")
    assert hasattr(RedBarDatabase, "update_pipeline_run_status")
    assert hasattr(RedBarDatabase, "read_pipeline_run_status")
    assert hasattr(RedBarDatabase, "upsert_eod_pipeline_validation")
    assert hasattr(RedBarDatabase, "read_eod_pipeline_validation")



def test_rb0743_historical_backfill_storage_apis_exist():
    assert hasattr(RedBarDatabase, "upsert_historical_option_backfill")
    assert hasattr(RedBarDatabase, "read_historical_option_backfill_day")
    assert hasattr(RedBarDatabase, "read_historical_option_backfill_range")



def test_rb0745_paper_execution_storage_apis_exist():
    assert hasattr(RedBarDatabase, "ensure_paper_execution_account")
    assert hasattr(RedBarDatabase, "insert_paper_execution_order")
    assert hasattr(RedBarDatabase, "read_paper_execution_order")
    assert hasattr(RedBarDatabase, "read_open_paper_execution_orders")
    assert hasattr(RedBarDatabase, "close_paper_execution_order")
    assert hasattr(RedBarDatabase, "insert_paper_execution_mark")



def test_rb0746_execution_foundation_storage_apis_exist():
    assert hasattr(RedBarDatabase, "paper_execution_exists_for_signal")
    assert hasattr(RedBarDatabase, "insert_execution_state_event")
    assert hasattr(RedBarDatabase, "read_execution_state_events")
    assert hasattr(RedBarDatabase, "upsert_paper_candidate_decision")
    assert hasattr(RedBarDatabase, "read_paper_candidate_decisions")



def test_rb0747_upstox_service_market_intelligence_apis_exist():
    from red_bar_lab.services.upstox_service import RedBarUpstoxService
    assert hasattr(RedBarUpstoxService, "option_contracts")
    assert hasattr(RedBarUpstoxService, "option_greeks")
    assert hasattr(RedBarUpstoxService, "option_chain")
    assert hasattr(RedBarUpstoxService, "intraday_candles")



def test_rb075_signal_provenance_lookup_exists():
    assert hasattr(RedBarDatabase, "read_signal_attempt_by_id")
