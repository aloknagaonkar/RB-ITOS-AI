from __future__ import annotations

from datetime import datetime
import sqlite3
from zoneinfo import ZoneInfo

from red_bar_lab.execution.execution_policy import (
    DIRECTIONAL_REGIME_STRATEGY_SOURCE,
    RED_BAR_V2_STRATEGY_SOURCE,
    RSI_STRATEGY_SOURCE,
    execution_strategy_source,
)
from red_bar_lab.execution.paper_strategy_authority import (
    PaperStrategyAuthority,
)
from red_bar_lab.operations.red_bar_v2_ui_snapshot import (
    RedBarV2UISnapshot,
    persist_red_bar_v2_ui_snapshot,
)
from red_bar_lab.services.red_bar_v2_paper_signal_bridge import (
    publish_v2_snapshot_to_paper_signals,
    validate_snapshot_for_paper,
)

IST = ZoneInfo("Asia/Kolkata")


def _authority() -> PaperStrategyAuthority:
    return PaperStrategyAuthority(
        primary_red_bar_version="v2",
        red_bar_v2_enabled=True,
        red_bar_v2_mode="paper",
        legacy_red_bar_v1_enabled=False,
        dri_strategy_enabled=False,
        rsi_extreme_reversal_enabled=False,
        broker_execution_enabled=False,
    )


def test_v2_is_only_enabled_paper_source() -> None:
    authority = _authority()
    assert authority.source_enabled("RED_BAR_V2") is True
    assert authority.source_enabled("REFERENCE_LEVEL") is False
    assert authority.source_enabled("DIRECTIONAL_REGIME_INTELLIGENCE") is False
    assert authority.source_enabled("RSI_EXTREME_REVERSAL_V1") is False
    assert authority.validate() == (True, "READY")


def test_broker_execution_fails_closed() -> None:
    authority = PaperStrategyAuthority(broker_execution_enabled=True)
    assert authority.validate() == (
        False,
        "BROKER_EXECUTION_MUST_REMAIN_DISABLED",
    )
    assert authority.source_enabled("RED_BAR_V2") is False


def test_execution_policy_recognizes_strategy_prefixes() -> None:
    assert execution_strategy_source({"signal_id": "RBV2-ABC"}) == RED_BAR_V2_STRATEGY_SOURCE
    assert execution_strategy_source({"signal_id": "DRI-ABC"}) == DIRECTIONAL_REGIME_STRATEGY_SOURCE
    assert execution_strategy_source({"signal_id": "RSI7-ABC"}) == RSI_STRATEGY_SOURCE
    assert execution_strategy_source({"signal_id": "RB-ABC"}) == "REFERENCE_LEVEL"


def test_stale_historical_snapshot_is_blocked() -> None:
    snapshot = RedBarV2UISnapshot(
        alignment_status="READY",
        admission_allowed=True,
        admission_code="INITIAL_BULLISH_ALIGNMENT",
        direction="BULLISH",
        admission_timestamp="2026-08-18T10:00:00+05:30",
        last_evaluation_timestamp="2026-08-18T10:00:00+05:30",
    )
    result = validate_snapshot_for_paper(
        snapshot,
        authority=_authority(),
        now=datetime(2026, 8, 19, 9, 20, tzinfo=IST),
    )
    assert result.status == "BLOCKED"
    assert result.reason == "V2_SNAPSHOT_NOT_CURRENT_SESSION"


def test_fresh_admitted_snapshot_publishes_one_signal(tmp_path) -> None:
    now = datetime(2026, 8, 19, 9, 30, tzinfo=IST)
    snapshot = RedBarV2UISnapshot(
        correlation_id="RBV2-RUNTIME-CORRELATED",
        alignment_status="READY",
        admission_allowed=True,
        admission_code="INITIAL_BEARISH_ALIGNMENT",
        admission_reason="Full bearish alignment.",
        direction="BEARISH",
        option_side="PE",
        admission_timestamp="2026-08-19T09:29:00+05:30",
        reference_timestamp="2026-08-19T09:25:00+05:30",
        reference_midpoint=24850.0,
        index_close=24820.0,
        last_evaluation_timestamp="2026-08-19T09:29:00+05:30",
    )
    artifacts = tmp_path / "artifacts"
    persist_red_bar_v2_ui_snapshot(snapshot, artifacts_root=artifacts)
    database = tmp_path / "paper.db"
    with sqlite3.connect(database) as conn:
        conn.execute(
            """
            CREATE TABLE signal_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT UNIQUE,
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
                confirmation_delay_minutes INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )
    first = publish_v2_snapshot_to_paper_signals(
        database_path=database,
        artifacts_root=artifacts,
        instrument_key="NSE_INDEX|Nifty 50",
        authority=_authority(),
        now=now,
    )
    second = publish_v2_snapshot_to_paper_signals(
        database_path=database,
        artifacts_root=artifacts,
        instrument_key="NSE_INDEX|Nifty 50",
        authority=_authority(),
        now=now,
    )
    assert first.status == "PUBLISHED"
    assert second.status == "PUBLISHED"
    assert first.signal_id == second.signal_id
    with sqlite3.connect(database) as conn:
        rows = conn.execute(
            "SELECT signal_id,run_id,level_type,direction,state FROM signal_attempts"
        ).fetchall()
    assert rows == [(
        first.signal_id,
        "RBV2-RUNTIME-CORRELATED",
        "RED_BAR_V2",
        "BEARISH",
        "ACTIVE",
    )]


def test_old_admission_is_not_refreshed_by_new_observation_timestamp() -> None:
    snapshot = RedBarV2UISnapshot(
        alignment_status="READY",
        admission_allowed=True,
        admission_code="INITIAL_BEARISH_ALIGNMENT",
        direction="BEARISH",
        option_side="PE",
        admission_timestamp="2026-08-19T09:20:00+05:30",
        last_evaluation_timestamp="2026-08-19T11:00:00+05:30",
    )

    result = validate_snapshot_for_paper(
        snapshot,
        authority=_authority(),
        now=datetime(2026, 8, 19, 11, 0, tzinfo=IST),
    )

    assert result.status == "BLOCKED"
    assert result.reason == "V2_SNAPSHOT_STALE"
