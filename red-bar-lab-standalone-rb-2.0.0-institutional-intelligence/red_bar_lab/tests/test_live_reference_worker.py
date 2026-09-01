from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from red_bar_lab.execution.live_reference_worker import run_cycle
from red_bar_lab.execution.live_reference_worker import _format_level_diagnostics
from red_bar_lab.services.live_service import _build_level_diagnostics
from red_bar_lab.strategy.models import (
    Direction,
    ReferenceLevel,
    SignalAttempt,
    SignalState,
)


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


def _result(
    *,
    current_price: float | None = 24100.0,
    attempts: int = 0,
    active: int = 0,
    awaiting: int = 0,
    level_diagnostics: tuple[dict[str, object], ...] = (),
    levels_stored: int = 9,
):
    return SimpleNamespace(
        connected=True,
        message="Current session refreshed.",
        trading_date=datetime(2026, 8, 21, tzinfo=IST).date(),
        source_rows=141,
        levels_stored=levels_stored,
        completed_five_minute_rows=28,
        last_refresh=datetime(2026, 8, 21, 11, 35, tzinfo=IST),
        current_price=current_price,
        attempts=attempts,
        active=active,
        awaiting=awaiting,
        level_diagnostics=level_diagnostics,
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


def _reference_level(
    level_type: str,
    source_high: float,
    source_low: float,
    *,
    source_ts: datetime | None = None,
    interval_minutes: int = 5,
) -> ReferenceLevel:
    return ReferenceLevel(
        level_type=level_type,
        value=(source_high + source_low) / 2.0,
        source_timestamp=source_ts or datetime(2026, 8, 21, 9, 15, tzinfo=IST),
        source_high=source_high,
        source_low=source_low,
        interval_minutes=interval_minutes,
    )


def test_build_level_diagnostics_marks_price_inside_range():
    level = _reference_level("FIRST_CANDLE", 24128.0, 24038.0)
    diagnostics = _build_level_diagnostics(
        levels=[level],
        current_price=24080.0,
        attempts=(),
    )
    assert len(diagnostics) == 1
    entry = diagnostics[0]
    assert entry["level_type"] == "FIRST_CANDLE"
    assert entry["status"] == "PRICE_INSIDE_RANGE"
    assert "no cross can fire" in entry["explanation"]
    assert entry["distance_to_high"] == 24128.0 - 24080.0
    assert entry["distance_to_low"] == 24080.0 - 24038.0


def test_build_level_diagnostics_marks_price_above_level():
    level = _reference_level("PD9_315", 24166.0, 24155.0)
    diagnostics = _build_level_diagnostics(
        levels=[level],
        current_price=24200.0,
        attempts=(),
    )
    entry = diagnostics[0]
    assert entry["status"] == "PRICE_ABOVE_LEVEL"
    assert "bearish break" in entry["explanation"]


def test_build_level_diagnostics_marks_price_below_level():
    level = _reference_level("NEXT_RED_CANDLE", 24085.0, 24057.0)
    diagnostics = _build_level_diagnostics(
        levels=[level],
        current_price=24040.0,
        attempts=(),
    )
    entry = diagnostics[0]
    assert entry["status"] == "PRICE_BELOW_LEVEL"
    assert "bullish break" in entry["explanation"]


def test_build_level_diagnostics_attaches_last_attempt_state():
    level = _reference_level("FIRST_CANDLE", 24128.0, 24038.0)
    attempts = (
        SignalAttempt(
            state=SignalState.TIMEOUT,
            direction=Direction.BULLISH,
            level_type="FIRST_CANDLE",
            level_value=24128.0,
            cross_timestamp=datetime(2026, 8, 21, 9, 30, tzinfo=IST),
        ),
    )
    diagnostics = _build_level_diagnostics(
        levels=[level],
        current_price=24080.0,
        attempts=attempts,
    )
    entry = diagnostics[0]
    assert entry["last_attempt_state"] == "TIMEOUT"
    assert entry["has_active_attempt"] is False


def test_build_level_diagnostics_empty_when_price_missing():
    level = _reference_level("FIRST_CANDLE", 24128.0, 24038.0)
    assert (
        _build_level_diagnostics(levels=[level], current_price=None, attempts=())
        == ()
    )
    assert (
        _build_level_diagnostics(levels=[], current_price=24080.0, attempts=())
        == ()
    )


def test_run_cycle_writes_diagnostics_to_status_when_no_signals(tmp_path):
    level = _reference_level("FIRST_CANDLE", 24128.0, 24038.0)
    diagnostics = _build_level_diagnostics(
        levels=[level],
        current_price=24080.0,
        attempts=(),
    )
    service = _Service(
        result=_result(
            current_price=24080.0,
            level_diagnostics=diagnostics,
        ),
    )
    status_path = tmp_path / "status.json"

    run_cycle(
        service,
        instrument_key="NSE_INDEX|Nifty 50",
        underlying_name="NIFTY 50",
        status_path=status_path,
        now=datetime(2026, 8, 21, 11, 36, tzinfo=IST),
    )

    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["current_price"] == 24080.0
    assert status["attempts"] == 0
    assert status["active_attempts"] == 0
    assert status["awaiting_attempts"] == 0
    assert len(status["level_diagnostics"]) == 1
    assert status["level_diagnostics"][0]["level_type"] == "FIRST_CANDLE"
    assert status["level_diagnostics"][0]["status"] == "PRICE_INSIDE_RANGE"


def test_run_cycle_logs_no_signal_diagnostic(caplog, tmp_path):
    import logging

    level = _reference_level("FIRST_CANDLE", 24128.0, 24038.0)
    diagnostics = _build_level_diagnostics(
        levels=[level],
        current_price=24080.0,
        attempts=(),
    )
    service = _Service(
        result=_result(
            current_price=24080.0,
            level_diagnostics=diagnostics,
        ),
    )
    status_path = tmp_path / "status.json"

    with caplog.at_level(logging.INFO):
        run_cycle(
            service,
            instrument_key="NSE_INDEX|Nifty 50",
            underlying_name="NIFTY 50",
            status_path=status_path,
            now=datetime(2026, 8, 21, 11, 36, tzinfo=IST),
        )

    no_signal_records = [
        record
        for record in caplog.records
        if "no signal candidates" in record.getMessage()
    ]
    assert no_signal_records, "expected a 'no signal candidates' log line"
    message = no_signal_records[0].getMessage()
    assert "current_price=24080.0" in message
    assert "FIRST_CANDLE=PRICE_INSIDE_RANGE" in message


def test_format_level_diagnostics_handles_empty():
    assert _format_level_diagnostics(()) == "no-levels-built-yet"
    assert _format_level_diagnostics([]) == "no-levels-built-yet"
