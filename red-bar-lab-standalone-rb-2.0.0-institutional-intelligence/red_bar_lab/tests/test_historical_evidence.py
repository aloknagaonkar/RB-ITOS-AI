from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import sqlite3

from red_bar_lab.intelligence.historical_evidence import HistoricalEvidenceService
from red_bar_lab.storage.database import RedBarDatabase


IST = ZoneInfo("Asia/Kolkata")


def _insert_signal(db, *, signal_id, trading_date="2026-08-13", direction="BULLISH"):
    db.initialize()
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            """
            INSERT INTO signal_attempts(
                signal_id,run_id,instrument_key,trading_date,level_type,
                level_value,direction,state,cross_timestamp,
                confirmation_timestamp,underlying_entry,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                signal_id,
                "RUN-EVIDENCE",
                "NSE_INDEX|Nifty 50",
                trading_date,
                "FIRST_CANDLE",
                24500.0,
                direction,
                "ACTIVE",
                f"{trading_date}T09:20:00+05:30",
                f"{trading_date}T09:21:00+05:30",
                24510.0,
                f"{trading_date}T09:21:00+05:30",
            ),
        )
        conn.commit()


def _open_order(db, *, order_id, signal_id, token=101, entry_minute=30):
    entry = datetime(2026, 8, 13, 9, entry_minute, tzinfo=IST)
    db.insert_paper_execution_order(
        {
            "order_id": order_id,
            "account_id": "PAPER-STD",
            "signal_id": signal_id,
            "market_data_provider": "ZERODHA",
            "execution_provider": "PAPER",
            "execution_mode": "PAPER",
            "underlying_name": "NIFTY 50",
            "underlying_price_entry": 24510.0,
            "instrument_token": token,
            "exchange": "NFO",
            "tradingsymbol": "NIFTY24500CE",
            "option_type": "CE",
            "strike": 24500.0,
            "expiry": "2026-08-13",
            "lot_size": 75,
            "side": "BUY",
            "quantity": 75,
            "entry_timestamp": entry.isoformat(),
            "entry_price": 100.0,
            "current_price": 100.0,
            "stop_price": 85.0,
            "target1_price": None,
            "target2_price": None,
            "status": "OPEN",
            "entry_reason": "TEST_EVIDENCE",
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "mfe_points": 0.0,
            "mae_points": 0.0,
        }
    )
    db.update_paper_entry_intelligence(
        order_id=order_id,
        entry_mode="FRESH_SIGNAL",
        signal_age_at_entry=20.0,
        opportunity_score=91.0,
        reward_remaining_pct=72.0,
        candidate_rank=1,
        candidate_score=93.0,
        selection_score=89.0,
        historical_win_rate_pct=60.0,
        historical_profit_factor=1.8,
        historical_expectancy_pct=4.5,
        historical_sample_size=25,
        execution_probability_pct=93.0,
        expected_value_pct=0.0,
        intelligence_score=50.0,
    )
    return entry


def _database(tmp_path):
    db = RedBarDatabase(tmp_path / "evidence.db")
    db.initialize()
    db.ensure_paper_execution_account(
        account_id="PAPER-STD",
        account_name="Evidence Test",
        initial_capital=100000.0,
    )
    return db


def test_paper_execution_builds_canonical_closed_evidence_without_fabrication(tmp_path):
    db = _database(tmp_path)
    _insert_signal(db, signal_id="SIG-EVIDENCE-1")
    entry = _open_order(db, order_id="ORD-EVIDENCE-1", signal_id="SIG-EVIDENCE-1")
    db.close_paper_execution_order(
        order_id="ORD-EVIDENCE-1",
        exit_timestamp=(entry + timedelta(minutes=30)).isoformat(),
        exit_price=120.0,
        exit_reason="BULLISH_EMA10_EXIT",
        realized_pnl=1500.0,
        mfe_points=25.0,
        mae_points=4.0,
    )

    service = HistoricalEvidenceService(db)
    report = service.build_paper_execution_evidence(account_id="PAPER-STD")
    rows = service.store.read(source_type="PAPER_EXECUTION")

    assert report.records_written == 1
    assert report.resolved_outcomes == 1
    assert len(rows) == 1
    row = rows[0]
    assert row["level_type"] == "FIRST_CANDLE"
    assert row["direction"] == "BULLISH"
    assert row["candidate_score"] == 93.0
    assert row["opportunity_score"] == 91.0
    assert row["selection_score"] == 89.0
    assert row["return_pct"] == 20.0
    assert row["holding_minutes"] == 30.0
    assert row["outcome_result"] == "WIN"
    assert row["exit_reason"] == "BULLISH_EMA10_EXIT"
    assert row["shadow_execution_impact"] == "NONE"
    assert row["entry_ema10"] is None
    assert "entry_ema10" in row["missing_fields"]


def test_paper_evidence_rebuild_is_idempotent_and_tracks_contract_sequence(tmp_path):
    db = _database(tmp_path)
    _insert_signal(db, signal_id="SIG-SEQ-1")
    _insert_signal(db, signal_id="SIG-SEQ-2")

    first = _open_order(db, order_id="ORD-SEQ-1", signal_id="SIG-SEQ-1", token=777, entry_minute=30)
    db.close_paper_execution_order(
        order_id="ORD-SEQ-1",
        exit_timestamp=(first + timedelta(minutes=10)).isoformat(),
        exit_price=105.0,
        exit_reason="BREAKEVEN_STOP",
        realized_pnl=375.0,
        mfe_points=8.0,
        mae_points=2.0,
    )
    second = _open_order(db, order_id="ORD-SEQ-2", signal_id="SIG-SEQ-2", token=777, entry_minute=50)
    db.close_paper_execution_order(
        order_id="ORD-SEQ-2",
        exit_timestamp=(second + timedelta(minutes=15)).isoformat(),
        exit_price=95.0,
        exit_reason="HARD_STOP",
        realized_pnl=-375.0,
        mfe_points=3.0,
        mae_points=6.0,
    )

    service = HistoricalEvidenceService(db)
    service.build_paper_execution_evidence(account_id="PAPER-STD")
    service.build_paper_execution_evidence(account_id="PAPER-STD")
    rows = service.store.read(source_type="PAPER_EXECUTION")

    assert len(rows) == 2
    by_id = {row["source_id"]: row for row in rows}
    assert by_id["ORD-SEQ-1"]["contract_entry_number"] == 1
    assert by_id["ORD-SEQ-2"]["contract_entry_number"] == 2
    assert by_id["ORD-SEQ-1"]["signal_reentry_number"] == 0
    assert by_id["ORD-SEQ-2"]["signal_reentry_number"] == 0


def _replay_row(*, outcome="WIN", option_exit=120.0):
    return SimpleNamespace(
        signal_id="RB-REPLAY-1",
        timestamp="2026-08-13T10:05:00+05:30",
        level_type="PD1_315",
        direction="BEARISH",
        option_side="PE",
        primary_confidence_pct=88.0,
        final_confidence_pct=88.0,
        expectancy_pct=-2.5,
        decision="APPROVED",
        execution="WOULD_TAKE",
        blocker="NONE",
        data_fidelity="PARTIAL_LIVE_PARITY_HIGH",
        candidate_symbol="NIFTY24500PE",
        candidate_rank=1,
        candidate_score=88.0,
        opportunity_health=90.0,
        portfolio_status="APPROVED",
        portfolio_reason="PORTFOLIO_ADMITTED",
        exit_reason="BEARISH_EMA10_EXIT",
        option_entry_price=100.0,
        option_exit_price=option_exit,
        option_return_pct=((option_exit - 100.0) if option_exit is not None else None),
        outcome_result=outcome,
        outcome_basis="EXECUTED_EXIT_ENGINE",
    )


def test_replay_ingest_is_replaceable_and_shadow_remains_zero_authority(tmp_path):
    db = _database(tmp_path)
    service = HistoricalEvidenceService(db)
    result = SimpleNamespace(
        trading_date=date(2026, 8, 13),
        data_fidelity="PARTIAL_LIVE_PARITY_HIGH",
        data_source="LIVE_MARKET_CAPTURE",
        rows=(_replay_row(),),
    )

    first = service.ingest_replay_result(
        instrument_key="NSE_INDEX|Nifty 50",
        result=result,
    )
    assert first.records_written == 1

    updated = SimpleNamespace(
        trading_date=date(2026, 8, 13),
        data_fidelity="PARTIAL_LIVE_PARITY_HIGH",
        data_source="LIVE_MARKET_CAPTURE",
        rows=(_replay_row(outcome="LOSS", option_exit=90.0),),
    )
    service.ingest_replay_result(
        instrument_key="NSE_INDEX|Nifty 50",
        result=updated,
    )
    rows = service.store.read(source_type="HISTORICAL_REPLAY")

    assert len(rows) == 1
    row = rows[0]
    assert row["outcome_result"] == "LOSS"
    assert row["return_pct"] == -10.0
    assert row["committee_expectancy_pct"] == -2.5
    assert row["shadow_execution_impact"] == "NONE"
    assert row["data_source"] == "LIVE_MARKET_CAPTURE"
    assert row["entry_ema10"] is None
    assert "entry_ema10_state" in row["missing_fields"]


def test_evidence_date_filter_does_not_change_global_contract_sequence(tmp_path):
    db = _database(tmp_path)
    _insert_signal(db, signal_id="SIG-FILTER-1")
    _insert_signal(db, signal_id="SIG-FILTER-2")
    first = _open_order(db, order_id="ORD-FILTER-1", signal_id="SIG-FILTER-1", token=999, entry_minute=30)
    db.close_paper_execution_order(
        order_id="ORD-FILTER-1",
        exit_timestamp=(first + timedelta(minutes=5)).isoformat(),
        exit_price=101.0,
        exit_reason="EOD_EXIT",
        realized_pnl=75.0,
        mfe_points=2.0,
        mae_points=1.0,
    )
    second = _open_order(db, order_id="ORD-FILTER-2", signal_id="SIG-FILTER-2", token=999, entry_minute=40)
    db.close_paper_execution_order(
        order_id="ORD-FILTER-2",
        exit_timestamp=(second + timedelta(minutes=5)).isoformat(),
        exit_price=102.0,
        exit_reason="EOD_EXIT",
        realized_pnl=150.0,
        mfe_points=3.0,
        mae_points=1.0,
    )

    service = HistoricalEvidenceService(db)
    report = service.build_paper_execution_evidence(
        account_id="PAPER-STD",
        date_from="2026-08-13",
        date_to="2026-08-13",
    )
    assert report.records_written == 2
    rows = service.store.read(source_type="PAPER_EXECUTION")
    assert [row["contract_entry_number"] for row in rows] == [1, 2]
