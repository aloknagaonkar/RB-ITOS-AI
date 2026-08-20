from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from red_bar_lab.services.nifty_futures_phase2_pipeline import (
    run_nifty_futures_phase2_pipeline,
)
from red_bar_lab.services.nifty_futures_snapshot_store import read_nifty_futures_snapshots


class Provider:
    def intraday_candles(self, instrument_key, interval_minutes=1):
        return [
            ["2026-08-20T10:00:00+05:30", 100, 101, 99, 100, 1000, 10000],
            ["2026-08-20T10:01:00+05:30", 100, 102, 99, 101, 1300, 10100],
            ["2026-08-20T10:02:00+05:30", 101, 103, 100, 102, 1500, 10200],
        ]


def test_pipeline_assesses_and_persists_without_execution_authority(tmp_path):
    now = datetime(2026, 8, 20, 10, 3, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    result = run_nifty_futures_phase2_pipeline(
        Provider(),
        database_path=tmp_path / "red_bar.db",
        contract=SimpleNamespace(
            status="READY",
            instrument_key="NSE_FO|1",
            trading_symbol="NIFTY FUT",
            expiry="2026-08-25",
            error=None,
        ),
        now=now,
    )

    assert result.persisted is True
    assert result.persistence_error is None
    assert result.market.status == "READY"
    assert result.positioning.state == "LONG_BUILDUP"
    assert result.readiness.status == "READY"
    rows = read_nifty_futures_snapshots(tmp_path / "red_bar.db")
    assert rows[0]["authority"] == "OBSERVATIONAL_ONLY"


def test_pipeline_persistence_failure_is_non_fatal(tmp_path):
    bad_path = tmp_path / "directory"
    bad_path.mkdir()
    now = datetime(2026, 8, 20, 10, 3, 30, tzinfo=ZoneInfo("Asia/Kolkata"))

    result = run_nifty_futures_phase2_pipeline(
        Provider(),
        database_path=bad_path,
        contract=SimpleNamespace(
            status="READY",
            instrument_key="NSE_FO|1",
            trading_symbol="NIFTY FUT",
            expiry="2026-08-25",
            error=None,
        ),
        now=now,
    )

    assert result.market.status == "READY"
    assert result.persisted is False
    assert result.persistence_error
