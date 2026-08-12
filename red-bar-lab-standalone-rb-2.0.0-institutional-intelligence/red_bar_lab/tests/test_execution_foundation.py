from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import sqlite3

import pandas as pd
import pytest

from red_bar_lab.config import RedBarSettings
from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.execution.providers import (
    ExecutionIntent,
    ZerodhaLiveExecutionProvider,
)
from red_bar_lab.storage.database import RedBarDatabase


class AutoFakeZerodha:
    def __init__(self):
        self.price = 100.0

    def ltp(self, instruments):
        return {key: 25020.0 for key in instruments}

    def nfo_options(self, underlying_name, as_of=None):
        return pd.DataFrame([
            {
                "instrument_token": 1001,
                "tradingsymbol": "NIFTY26AUG25000CE",
                "name": "NIFTY",
                "expiry": date(2026, 8, 13),
                "strike": 25000.0,
                "lot_size": 75,
                "instrument_type": "CE",
                "exchange": "NFO",
            },
            {
                "instrument_token": 1002,
                "tradingsymbol": "NIFTY26AUG25100CE",
                "name": "NIFTY",
                "expiry": date(2026, 8, 13),
                "strike": 25100.0,
                "lot_size": 75,
                "instrument_type": "CE",
                "exchange": "NFO",
            },
            {
                "instrument_token": 1003,
                "tradingsymbol": "NIFTY26AUG25000PE",
                "name": "NIFTY",
                "expiry": date(2026, 8, 13),
                "strike": 25000.0,
                "lot_size": 75,
                "instrument_type": "PE",
                "exchange": "NFO",
            },
        ])

    def quote(self, instruments):
        return {
            key: {
                "last_price": self.price,
                "volume": 100000,
                "oi": 100000,
                "buy_quantity": 1000,
                "sell_quantity": 1000,
                "depth": {
                    "buy": [{"price": self.price - 0.5}],
                    "sell": [{"price": self.price + 0.5}],
                },
            }
            for key in instruments
        }

    def historical_candles(
        self,
        instrument_token,
        interval,
        date_from,
        date_to,
        include_oi=True,
    ):
        ts = pd.date_range(
            "2026-08-10 09:15",
            periods=30,
            freq="1min",
            tz="Asia/Kolkata",
        )
        close = list(range(100, 130))
        return pd.DataFrame({
            "timestamp": ts,
            "open": close,
            "high": [x + 1 for x in close],
            "low": [x - 1 for x in close],
            "close": close,
            "volume": [10000] * 30,
            "oi": [100000] * 30,
        })


def _setup(tmp_path):
    settings = RedBarSettings(
        artifacts_root=tmp_path / "artifacts"
    )
    db = RedBarDatabase(settings.database_path)
    db.initialize()
    return settings, db


def _insert_confirmed_signal(db):
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            """
            INSERT INTO signal_attempts(
                signal_id,run_id,instrument_key,trading_date,
                level_type,level_value,direction,state,
                confirmation_timestamp,underlying_entry,created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "SIG-AUTO-1",
                "RUN-1",
                "NSE_INDEX|Nifty 50",
                "2026-08-10",
                "TEST",
                25000.0,
                "BULLISH",
                "ACTIVE",
                "2026-08-10T09:30:00+05:30",
                25020.0,
                "2026-08-10T09:30:00+05:30",
            ),
        )
        conn.commit()


def test_live_provider_is_hard_disabled():
    provider = ZerodhaLiveExecutionProvider(
        kill_switch_active=True
    )
    assert provider.LIVE_EXECUTION_ENABLED is False
    state = provider.safety_state(
        market_hours_ok=True,
        instrument_verified=True,
        quantity_verified=True,
        duplicate_free=True,
    )
    assert state.live_allowed is False

    with pytest.raises(RuntimeError, match="LIVE EXECUTION IS DISABLED"):
        provider.submit(
            ExecutionIntent(
                intent_id="I-1",
                signal_id="S-1",
                instrument_token=1,
                tradingsymbol="TEST",
                exchange="NFO",
                side="BUY",
                quantity=75,
                mode="LIVE",
            )
        )


def test_rule_based_candidate_score_uses_real_available_fields(tmp_path):
    settings, db = _setup(tmp_path)
    service = RedBarPaperAutomationService(
        zerodha=AutoFakeZerodha(),
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        minimum_candidate_score=65.0,
        allow_outside_market_hours=True,
        allow_stale_signals=True,
    )
    scores = service.score_candidates(
        direction="BULLISH",
        spot_price=25020.0,
    )
    assert scores
    assert scores[0].contract.option_type == "CE"
    assert scores[0].total_score >= 65.0
    assert scores[0].spread_score > 0
    assert scores[0].volume_score > 0
    assert scores[0].oi_score > 0
    assert scores[0].vwap_score > 0
    assert scores[0].ema_score > 0


def test_automatic_signal_to_virtual_order_is_idempotent(tmp_path):
    settings, db = _setup(tmp_path)
    _insert_confirmed_signal(db)
    fake = AutoFakeZerodha()
    service = RedBarPaperAutomationService(
        zerodha=fake,
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        minimum_candidate_score=65.0,
        allow_outside_market_hours=True,
        allow_stale_signals=True,
        maximum_portfolio_risk_pct=5.0,
    )

    first = service.run_cycle(
        trading_date="2026-08-10",
        lots=1,
    )
    assert first.paper_orders_opened == 2

    second = service.run_cycle(
        trading_date="2026-08-10",
        lots=1,
    )
    assert second.paper_orders_opened == 0
    assert second.skipped >= 1

    orders = db.read_paper_execution_orders("PAPER-STD")
    assert len(orders) == 2
    assert orders[0]["signal_id"] == "SIG-AUTO-1"
    assert orders[0]["option_type"] == "CE"

    decisions = db.read_paper_candidate_decisions(
        "2026-08-10"
    )
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "PAPER_BUY_MULTI"

    events = db.read_execution_state_events(
        signal_id="SIG-AUTO-1"
    )
    states = {row["state"] for row in events}
    assert "CANDIDATE_SELECTION" in states
    assert "OPEN" in states


def test_automatic_target_exit_closes_virtual_order(tmp_path):
    settings, db = _setup(tmp_path)
    _insert_confirmed_signal(db)
    fake = AutoFakeZerodha()
    service = RedBarPaperAutomationService(
        zerodha=fake,
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        minimum_candidate_score=65.0,
        target_pct=25.0,
        eod_exit_time=time(23, 59),
        allow_outside_market_hours=True,
        allow_stale_signals=True,
        maximum_portfolio_risk_pct=5.0,
    )
    service.run_cycle(
        trading_date="2026-08-10",
        lots=1,
    )

    fake.price = 130.0
    closed, errors = service.monitor_and_exit()
    assert errors == []
    assert closed == 2

    order = db.read_paper_execution_orders("PAPER-STD")[0]
    assert order["status"] == "CLOSED"
    assert order["exit_reason"] == "AUTO_TARGET"
    assert order["realized_pnl"] > 0



def test_rb0749_momentum_falls_back_with_short_candle_history(tmp_path):
    class ShortHistoryZerodha(AutoFakeZerodha):
        def historical_candles(
            self,
            instrument_token,
            interval,
            date_from,
            date_to,
            include_oi=True,
        ):
            ts = pd.date_range(
                "2026-08-10 09:15",
                periods=2,
                freq="1min",
                tz="Asia/Kolkata",
            )
            return pd.DataFrame({
                "timestamp": ts,
                "open": [100.0, 100.2],
                "high": [100.3, 100.8],
                "low": [99.8, 100.1],
                "close": [100.0, 100.5],
                "volume": [10000, 12000],
                "oi": [100000, 101000],
            })

    settings, db = _setup(tmp_path)
    service = RedBarPaperAutomationService(
        zerodha=ShortHistoryZerodha(),
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        minimum_candidate_score=65.0,
        allow_outside_market_hours=True,
        allow_stale_signals=True,
    )
    scores = service.score_candidates(
        direction="BULLISH",
        spot_price=25020.0,
    )
    assert scores
    assert scores[0].candle_count == 2
    assert scores[0].momentum_pct is not None
    assert scores[0].momentum_pct > 0
    assert scores[0].momentum_score > 0



def test_rb07410_fresh_confirmed_closed_signal_is_not_rejected_by_state(
    tmp_path,
):
    settings, db = _setup(tmp_path)
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            """
            INSERT INTO signal_attempts(
                signal_id,run_id,instrument_key,trading_date,
                level_type,level_value,direction,state,
                confirmation_timestamp,underlying_entry,created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "SIG-CLOSED-1",
                "RUN-CLOSED",
                "NSE_INDEX|Nifty 50",
                "2026-08-10",
                "TEST",
                25000.0,
                "BULLISH",
                "CLOSED",
                "2026-08-10T10:45:00+05:30",
                25020.0,
                "2026-08-10T10:45:00+05:30",
            ),
        )
        conn.commit()

    service = RedBarPaperAutomationService(
        zerodha=AutoFakeZerodha(),
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        minimum_candidate_score=65.0,
        allow_outside_market_hours=True,
        allow_stale_signals=True,
        maximum_portfolio_risk_pct=5.0,
    )
    report = service.run_cycle(
        trading_date="2026-08-10",
        lots=1,
    )
    assert report.paper_orders_opened == 2

    order = db.read_paper_execution_orders("PAPER-STD")[0]
    assert order["signal_id"] == "SIG-CLOSED-1"

    diagnostics = db.read_paper_signal_diagnostics(
        signal_id="SIG-CLOSED-1"
    )
    assert diagnostics
    assert diagnostics[0]["final_decision"] == "OPENED"
    assert diagnostics[0]["signal_state"] == "CLOSED"


def test_rb07410_monitor_status_and_signal_diagnostics_storage(tmp_path):
    _, db = _setup(tmp_path)
    db.upsert_paper_monitor_status(
        {
            "monitor_id": "PAPER-MONITOR",
            "status": "RUNNING",
            "heartbeat_at": "2026-08-10T11:00:00+05:30",
            "last_scan_at": "2026-08-10T11:00:00+05:30",
            "started_at": "2026-08-10T10:59:00+05:30",
            "underlying_name": "NIFTY 50",
            "signals_seen": 12,
            "signals_qualified": 2,
            "candidates_scored": 10,
            "orders_opened": 1,
            "orders_closed": 0,
            "signals_skipped": 11,
            "current_state": "WAITING_FOR_SIGNAL",
            "last_signal_id": "SIG-1",
            "last_decision": "SKIP",
            "last_reason": "STALE_SIGNAL",
            "last_error": None,
        }
    )
    status = db.read_paper_monitor_status()
    assert status["status"] == "RUNNING"
    assert status["orders_opened"] == 1
    assert status["last_reason"] == "STALE_SIGNAL"

    db.insert_paper_signal_diagnostic(
        {
            "scan_id": "SCAN-1",
            "signal_id": "SIG-1",
            "signal_state": "CLOSED",
            "direction": "BULLISH",
            "confirmation_timestamp": "2026-08-10T10:45:00+05:30",
            "signal_age_seconds": 900,
            "market_hours_ok": True,
            "freshness_ok": False,
            "duplicate_free": True,
            "candidate_available": False,
            "best_candidate": None,
            "best_score": None,
            "minimum_score": 65,
            "score_ok": False,
            "final_decision": "SKIP",
            "reason": "STALE_SIGNAL age=900s > max=180s",
            "timestamp": "2026-08-10T11:00:00+05:30",
        }
    )
    rows = db.read_paper_signal_diagnostics(signal_id="SIG-1")
    assert len(rows) == 1
    assert rows[0]["freshness_ok"] == 0
    assert rows[0]["reason"].startswith("STALE_SIGNAL")



def _insert_opportunity_signal(
    db,
    *,
    signal_id,
    trading_date,
    confirmation_timestamp,
    confirmation_close=25010.0,
    confirmation_high=25030.0,
    confirmation_low=24990.0,
):
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            """
            INSERT INTO signal_attempts(
                signal_id,run_id,instrument_key,trading_date,
                level_type,level_value,direction,state,
                confirmation_timestamp,underlying_entry,
                confirmation_high,confirmation_low,confirmation_close,
                created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                signal_id,
                "RUN-OPP",
                "NSE_INDEX|Nifty 50",
                trading_date,
                "TEST",
                25000.0,
                "BULLISH",
                "ACTIVE",
                confirmation_timestamp,
                25010.0,
                confirmation_high,
                confirmation_low,
                confirmation_close,
                confirmation_timestamp,
            ),
        )
        conn.commit()


def test_rb090_old_signal_can_open_via_opportunity_extension(tmp_path):
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    trading_date = now.date().isoformat()
    old_ts = (now - timedelta(minutes=6)).isoformat()

    settings, db = _setup(tmp_path)
    _insert_opportunity_signal(
        db,
        signal_id="SIG-OPP-OPEN",
        trading_date=trading_date,
        confirmation_timestamp=old_ts,
        confirmation_close=25010.0,
        confirmation_high=25030.0,
        confirmation_low=24990.0,
    )

    service = RedBarPaperAutomationService(
        zerodha=AutoFakeZerodha(),
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        allow_outside_market_hours=True,
        max_signal_age_seconds=180,
        enable_opportunity_extension=True,
    )

    opened, skipped, scored, errors = service.process_new_signals(
        trading_date=trading_date,
        lots=1,
    )
    assert errors == []
    assert opened >= 1
    assert scored > 0

    order = db.read_paper_execution_orders("PAPER-STD")[0]
    assert order["entry_mode"] == "OPPORTUNITY_EXTENSION"
    assert float(order["signal_age_at_entry"]) > 180
    assert float(order["opportunity_score"]) >= 85
    assert float(order["reward_remaining_pct"]) >= 40
    assert "AUTO_OPPORTUNITY_EXTENSION" in str(order["entry_reason"])

    evaluations = db.read_opportunity_evaluations(
        signal_id="SIG-OPP-OPEN",
        limit=10,
    )
    assert evaluations
    assert evaluations[0]["entry_mode"] == "OPPORTUNITY_EXTENSION"
    assert bool(evaluations[0]["eligible"]) is True

    events = db.read_execution_state_events(
        signal_id="SIG-OPP-OPEN"
    )
    states = {row["state"] for row in events}
    assert "OPPORTUNITY_EVALUATED" in states
    assert "OPPORTUNITY_EXTENSION_APPROVED" in states
    assert "OPEN" in states


def test_rb090_old_signal_rejected_when_reward_is_consumed(tmp_path):
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    trading_date = now.date().isoformat()
    old_ts = (now - timedelta(minutes=6)).isoformat()

    settings, db = _setup(tmp_path)
    # BULLISH signal whose move is already far beyond two confirmation ranges.
    _insert_opportunity_signal(
        db,
        signal_id="SIG-OPP-LATE",
        trading_date=trading_date,
        confirmation_timestamp=old_ts,
        confirmation_close=24800.0,
        confirmation_high=24820.0,
        confirmation_low=24780.0,
    )

    service = RedBarPaperAutomationService(
        zerodha=AutoFakeZerodha(),
        database=db,
        settings=settings,
        underlying_name="NIFTY 50",
        allow_outside_market_hours=True,
        max_signal_age_seconds=180,
        enable_opportunity_extension=True,
    )

    opened, skipped, scored, errors = service.process_new_signals(
        trading_date=trading_date,
        lots=1,
    )
    assert errors == []
    assert opened == 0
    assert skipped >= 1

    evaluations = db.read_opportunity_evaluations(
        signal_id="SIG-OPP-LATE",
        limit=10,
    )
    assert evaluations
    assert bool(evaluations[0]["eligible"]) is False
    assert "REWARD_CONSUMED" in str(evaluations[0]["reason"])

    events = db.read_execution_state_events(
        signal_id="SIG-OPP-LATE"
    )
    states = {row["state"] for row in events}
    assert "SKIPPED_OPPORTUNITY" in states
