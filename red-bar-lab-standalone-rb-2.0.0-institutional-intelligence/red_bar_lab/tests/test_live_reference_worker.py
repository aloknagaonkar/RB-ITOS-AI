from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from red_bar_lab.execution.live_reference_worker import run_cycle


IST = ZoneInfo("Asia/Kolkata")


class _Service:
    def __init__(self, result=None, error: Exception | None = None):
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
        source_rows=141,
        levels_stored=9,
        completed_five_minute_rows=28,
        last_refresh=datetime(2026, 8, 21, 11, 35, tzinfo=IST),
    )


def test_run_cycle_refreshes_and_persists_status(tmp_path):
    service = _Service(result=_result())
    status_path = tmp_path / "status.json"

    result = run_cycle(
        service,
        instrument_key="NSE_INDEX|Nifty 50",
        underlying_name="NIFTY 50",
        status_path=status_path,
        now=datetime(2026, 8, 21, 11, 36, tzinfo=IST),
    )

    assert result is service.result
    assert service.calls == ["NSE_INDEX|Nifty 50"]
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "RUNNING"
    assert status["source_rows"] == 141
    assert status["levels_stored"] == 9
    assert status["last_error"] is None


def test_run_cycle_waits_outside_market_hours(tmp_path):
    service = _Service(result=_result())
    status_path = tmp_path / "status.json"

    result = run_cycle(
        service,
        instrument_key="NSE_INDEX|Nifty 50",
        underlying_name="NIFTY 50",
        status_path=status_path,
        now=datetime(2026, 8, 21, 8, 0, tzinfo=IST),
    )

    assert result is None
    assert service.calls == []
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "WAITING"


def test_run_cycle_records_refresh_error(tmp_path):
    service = _Service(error=RuntimeError("provider unavailable"))
    status_path = tmp_path / "status.json"

    result = run_cycle(
        service,
        instrument_key="NSE_INDEX|Nifty 50",
        underlying_name="NIFTY 50",
        status_path=status_path,
        now=datetime(2026, 8, 21, 11, 36, tzinfo=IST),
    )

    assert result is None
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "ERROR"
    assert status["last_error"] == "provider unavailable"
