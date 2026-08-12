from datetime import datetime
from pathlib import Path

import pandas as pd

from red_bar_lab.collector.service import (
    RedBarDualMarketCollector,
    market_clock_mode,
    market_session_phase,
)
from red_bar_lab.config import RedBarSettings
from red_bar_lab.storage.database import RedBarDatabase


def _chain():
    return pd.DataFrame([
        {
            "expiry": "2026-08-13",
            "spot": 25000.0,
            "strike": 24950.0,
            "call_oi": 800.0,
            "put_oi": 1200.0,
            "call_oi_change": 50.0,
            "put_oi_change": 100.0,
            "call_iv": 13.0,
            "put_iv": 14.0,
            "call_delta": 0.65,
            "put_delta": -0.35,
            "call_gamma": 0.01,
            "put_gamma": 0.01,
            "call_theta": -2.0,
            "put_theta": -2.1,
            "call_vega": 4.0,
            "put_vega": 4.1,
        },
        {
            "expiry": "2026-08-13",
            "spot": 25000.0,
            "strike": 25000.0,
            "call_oi": 1500.0,
            "put_oi": 1600.0,
            "call_oi_change": 120.0,
            "put_oi_change": 140.0,
            "call_iv": 14.0,
            "put_iv": 15.0,
            "call_delta": 0.50,
            "put_delta": -0.50,
            "call_gamma": 0.02,
            "put_gamma": 0.02,
            "call_theta": -2.2,
            "put_theta": -2.3,
            "call_vega": 4.3,
            "put_vega": 4.4,
        },
        {
            "expiry": "2026-08-13",
            "spot": 25000.0,
            "strike": 25050.0,
            "call_oi": 2000.0,
            "put_oi": 600.0,
            "call_oi_change": 160.0,
            "put_oi_change": 40.0,
            "call_iv": 13.5,
            "put_iv": 15.5,
            "call_delta": 0.35,
            "put_delta": -0.65,
            "call_gamma": 0.01,
            "put_gamma": 0.01,
            "call_theta": -2.0,
            "put_theta": -2.2,
            "call_vega": 4.1,
            "put_vega": 4.2,
        },
    ])


class FakeProvider:
    def option_expiries(self, instrument_key):
        return ["2026-08-13"]

    def option_chain(self, instrument_key, expiry):
        return [{"fake": True}]

    def option_chain_dataframe(self, records):
        return _chain()


def _settings(tmp_path):
    return RedBarSettings(artifacts_root=tmp_path / "artifacts")


def test_market_clock_mode():
    assert market_clock_mode(
        datetime.fromisoformat("2026-08-07T10:00:00+05:30")
    ) == "ONLINE"
    assert market_clock_mode(
        datetime.fromisoformat("2026-08-07T16:00:00+05:30")
    ) == "OFFLINE"
    assert market_clock_mode(
        datetime.fromisoformat("2026-08-08T10:00:00+05:30")
    ) == "OFFLINE"


def test_online_collector_stores_history(tmp_path):
    settings = _settings(tmp_path)
    db = RedBarDatabase(settings.database_path)
    db.initialize()
    collector = RedBarDualMarketCollector(
        FakeProvider(), db, settings
    )

    report = collector.online_tick(
        instrument_key="NSE_INDEX|Nifty 50",
        now=datetime.fromisoformat(
            "2026-08-07T10:00:00+05:30"
        ),
    )

    assert report.status == "OK"
    assert report.snapshot_id is not None
    rows = db.read_option_chain_history(
        "NSE_INDEX|Nifty 50",
        "2026-08-07",
        "2026-08-07",
    )
    assert len(rows) == 1
    assert rows[0]["collector_mode"] == "ONLINE"
    assert rows[0]["pcr_oi"] is not None


def test_offline_collector_stores_eod_snapshot(tmp_path):
    settings = _settings(tmp_path)
    db = RedBarDatabase(settings.database_path)
    db.initialize()
    collector = RedBarDualMarketCollector(
        FakeProvider(), db, settings
    )

    report = collector.offline_eod_tick(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-07",
        now=datetime.fromisoformat(
            "2026-08-07T16:00:00+05:30"
        ),
    )

    assert report.status == "OK"
    rows = db.read_option_chain_history(
        "NSE_INDEX|Nifty 50",
        "2026-08-07",
        "2026-08-07",
    )
    assert len(rows) == 1
    assert rows[0]["collector_mode"] == "EOD"


def test_online_collector_dedupes_same_minute(tmp_path):
    settings = _settings(tmp_path)
    db = RedBarDatabase(settings.database_path)
    db.initialize()
    collector = RedBarDualMarketCollector(
        FakeProvider(), db, settings
    )

    first = collector.online_tick(
        instrument_key="NSE_INDEX|Nifty 50",
        now=datetime.fromisoformat(
            "2026-08-07T10:00:05+05:30"
        ),
    )
    second = collector.online_tick(
        instrument_key="NSE_INDEX|Nifty 50",
        now=datetime.fromisoformat(
            "2026-08-07T10:00:45+05:30"
        ),
    )

    assert first.snapshot_id == second.snapshot_id
    rows = db.read_option_chain_history(
        "NSE_INDEX|Nifty 50",
        "2026-08-07",
        "2026-08-07",
    )
    assert len(rows) == 1



def test_nearest_pre_entry_snapshot_can_be_found(tmp_path):
    settings = _settings(tmp_path)
    db = RedBarDatabase(settings.database_path)
    db.initialize()
    collector = RedBarDualMarketCollector(
        FakeProvider(), db, settings
    )

    collector.online_tick(
        instrument_key="NSE_INDEX|Nifty 50",
        now=datetime.fromisoformat(
            "2026-08-07T10:27:00+05:30"
        ),
    )

    snapshot = db.find_nearest_pre_entry_option_snapshot(
        instrument_key="NSE_INDEX|Nifty 50",
        entry_timestamp="2026-08-07T10:27:15+05:30",
        max_age_seconds=120,
    )
    assert snapshot is not None
    assert snapshot["snapshot_timestamp"] == (
        "2026-08-07T10:27:00+05:30"
    )



def test_market_session_phase_wait_states():
    assert market_session_phase(
        datetime.fromisoformat("2026-08-07T08:30:00+05:30")
    ) == "PREOPEN"
    assert market_session_phase(
        datetime.fromisoformat("2026-08-07T16:00:00+05:30")
    ) == "POSTCLOSE"
    assert market_session_phase(
        datetime.fromisoformat("2026-08-08T10:00:00+05:30")
    ) == "WEEKEND"
