from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from red_bar_lab.collector.runner import _refresh_live_reference

IST = ZoneInfo("Asia/Kolkata")


class _Service:
    def __init__(self, *, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def refresh(self, instrument_key: str):
        self.calls.append(instrument_key)
        if self.error is not None:
            raise self.error
        return self.result


def _result():
    return SimpleNamespace(
        connected=True,
        message="Current session refreshed.",
        trading_date=datetime(2026, 8, 21, tzinfo=IST).date(),
        source_rows=180,
        levels_stored=9,
        completed_five_minute_rows=36,
        last_refresh=datetime(2026, 8, 21, 12, 15, tzinfo=IST),
    )


def _settings(tmp_path: Path):
    return SimpleNamespace(database_path=tmp_path / "red_bar_strategy.db")


def test_collector_refreshes_live_reference_and_writes_heartbeat(tmp_path):
    service = _Service(result=_result())

    result = _refresh_live_reference(
        service,
        settings=_settings(tmp_path),
        instrument_key="NSE_INDEX|Nifty 50",
        underlying_name="NIFTY 50",
        now=datetime(2026, 8, 21, 12, 15, tzinfo=IST),
    )

    assert result is service.result
    assert service.calls == ["NSE_INDEX|Nifty 50"]
    status_path = tmp_path / "live_reference_worker_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "RUNNING"
    assert status["source_rows"] == 180
    assert status["levels_stored"] == 9


def test_collector_live_reference_failure_is_fault_isolated(tmp_path):
    service = _Service(error=RuntimeError("temporary candle failure"))

    result = _refresh_live_reference(
        service,
        settings=_settings(tmp_path),
        instrument_key="NSE_INDEX|Nifty 50",
        underlying_name="NIFTY 50",
        now=datetime(2026, 8, 21, 12, 15, tzinfo=IST),
    )

    assert result is None
    status_path = tmp_path / "live_reference_worker_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "ERROR"
    assert status["last_error"] == "temporary candle failure"
