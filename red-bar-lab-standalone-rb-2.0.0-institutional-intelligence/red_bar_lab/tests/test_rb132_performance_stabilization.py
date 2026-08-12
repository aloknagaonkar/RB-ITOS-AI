from __future__ import annotations

from datetime import date
import gc
import sqlite3
import threading
import time

import pandas as pd

from red_bar_lab.brokers.upstox_client import UpstoxClient
from red_bar_lab.config import RedBarSettings
from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.execution.paper_engine import PaperContract
from red_bar_lab.storage.database import RedBarDatabase


def _db(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "artifacts")
    database = RedBarDatabase(settings.database_path)
    database.initialize()
    return settings, database


def _unlink_with_windows_retry(path, attempts: int = 20, delay_seconds: float = 0.025):
    """Delete a SQLite test file after transient Windows handle release."""
    last_error = None
    for _ in range(attempts):
        try:
            path.unlink()
            return
        except PermissionError as exc:
            last_error = exc
            gc.collect()
            time.sleep(delay_seconds)
    if last_error is not None:
        raise last_error


def test_rb132_initialize_skips_schema_but_self_heals_deleted_file(tmp_path):
    _, database = _db(tmp_path)
    assert database._initialized is True
    original = database.path
    database.initialize()  # hot path: no migration rerun
    assert original.exists()

    _unlink_with_windows_retry(original)
    database.initialize()  # self-heal path must recreate the DB
    assert original.exists()
    with sqlite3.connect(original) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_attempts'"
        ).fetchone() is not None


def test_rb132_batch_signal_and_event_reads_match_single_reads(tmp_path):
    _, database = _db(tmp_path)
    with sqlite3.connect(database.path) as conn:
        for idx in range(3):
            signal_id = f"SIG-{idx}"
            conn.execute(
                """
                INSERT INTO signal_attempts(
                    signal_id,run_id,instrument_key,trading_date,level_type,
                    level_value,direction,state,confirmation_timestamp,
                    underlying_entry,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    signal_id, "RUN", "NSE_INDEX|Nifty 50", "2026-08-10",
                    "TEST", 25000.0 + idx, "BULLISH", "ACTIVE",
                    f"2026-08-10T09:3{idx}:00+05:30", 25000.0,
                    f"2026-08-10T09:3{idx}:00+05:30",
                ),
            )
            for event_idx in range(3):
                conn.execute(
                    """
                    INSERT INTO execution_state_events(
                        event_id,signal_id,order_id,state,detail,candidate_score,timestamp
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        f"EV-{idx}-{event_idx}", signal_id, None,
                        f"STATE-{event_idx}", f"detail-{event_idx}", 70 + event_idx,
                        f"2026-08-10T09:3{idx}:0{event_idx}+05:30",
                    ),
                )
        conn.commit()

    signal_ids = ["SIG-0", "SIG-1", "SIG-2"]
    batch_meta = database.read_signal_attempts_by_ids(signal_ids)
    for signal_id in signal_ids:
        assert batch_meta[signal_id] == database.read_signal_attempt_by_id(signal_id)

    batch_events = database.read_execution_state_events_for_signals(
        signal_ids, per_signal_limit=2
    )
    for signal_id in signal_ids:
        assert batch_events[signal_id] == database.read_execution_state_events(
            signal_id=signal_id, limit=2
        )


def test_rb132_candidate_candles_are_fetched_concurrently(tmp_path):
    settings, database = _db(tmp_path)

    class DummyZerodha:
        pass

    service = RedBarPaperAutomationService(
        zerodha=DummyZerodha(), database=database, settings=settings,
        underlying_name="NIFTY 50", allow_outside_market_hours=True,
        allow_stale_signals=True,
    )
    contracts = [
        PaperContract(
            instrument_token=1000 + idx,
            tradingsymbol=f"NIFTY26AUG{24500 + idx * 50}CE",
            exchange="NFO", option_type="CE", strike=24500 + idx * 50,
            expiry=date(2026, 8, 13), lot_size=75,
        )
        for idx in range(5)
    ]
    service.engine.candidate_contracts = lambda **kwargs: contracts
    service.engine.contract_quotes = lambda **kwargs: [
        {
            "symbol": contract.tradingsymbol,
            "ltp": 100.0,
            "best_bid": 99.5,
            "best_ask": 100.5,
            "volume": 100000,
            "oi": 100000,
            "buy_quantity": 1000,
            "sell_quantity": 1000,
        }
        for contract in contracts
    ]

    lock = threading.Lock()
    active = 0
    max_active = 0

    def candles(**kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        ts = pd.date_range("2026-08-10 09:15", periods=3, freq="1min", tz="Asia/Kolkata")
        return pd.DataFrame({
            "timestamp": ts,
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000, 1000, 1000],
            "oi": [10000, 10000, 10000],
            "vwap": [100.0, 100.5, 101.0],
            "ema9": [100.0, 100.5, 101.5],
            "ema21": [99.0, 99.5, 100.5],
        })

    service.engine.option_candles = candles
    scores = service.score_candidates(direction="BULLISH", spot_price=24600.0)
    assert len(scores) == 5
    assert max_active >= 2


def test_rb132_upstox_reuses_injected_http_session():
    class Response:
        ok = True
        status_code = 200
        text = ""
        def __init__(self, payload):
            self._payload = payload
        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.calls = []
        def get(self, url, **kwargs):
            self.calls.append(("GET", url))
            if url.endswith("/option/contract"):
                return Response({"data": [{"expiry": "2026-08-13"}]})
            return Response({"data": {}})
        def post(self, url, **kwargs):
            self.calls.append(("POST", url))
            return Response({"access_token": "x"})

    session = FakeSession()
    client = UpstoxClient("token", session=session)
    assert client.get_option_expiries("NSE_INDEX|Nifty 50") == ["2026-08-13"]
    client.exchange_code("c", "id", "secret", "http://localhost")
    assert [call[0] for call in session.calls] == ["GET", "POST"]
