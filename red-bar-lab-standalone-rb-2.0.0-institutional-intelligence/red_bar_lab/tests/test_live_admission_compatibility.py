from __future__ import annotations

import inspect
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.execution.live_admission_automation import (
    LiveAdmissionRedBarPaperAutomationService,
    _AdmissionDatabaseProxy,
)


IST = ZoneInfo("Asia/Kolkata")


class _Database:
    def __init__(self, *, signals=None, queue=None):
        self.signals = list(signals or [])
        self.queue = list(queue or [])
        self.expired = []
        self.diagnostics = []
        self.events = []

    def read_signal_attempts(self, instrument_key, trading_date):
        return list(self.signals)

    def read_execution_queue(self, **kwargs):
        return list(self.queue)

    def expire_execution_queue_for_signal(self, *, signal_id, reason):
        self.expired.append((signal_id, reason))

    def insert_paper_signal_diagnostic(self, row):
        self.diagnostics.append(dict(row))

    def insert_execution_state_event(self, row):
        self.events.append(dict(row))


def _service(database):
    service = object.__new__(LiveAdmissionRedBarPaperAutomationService)
    service.database = database
    service.engine = SimpleNamespace(database=database)
    service.underlying_name = "NIFTY 50"
    service.max_signal_age_seconds = 180
    service.allow_outside_market_hours = True
    service.allow_stale_signals = True
    service.enable_opportunity_extension = True
    return service


def test_guard_is_additive_subclass_and_base_engine_has_no_admission_dependency():
    assert issubclass(
        LiveAdmissionRedBarPaperAutomationService,
        RedBarPaperAutomationService,
    )
    base_source = inspect.getsource(RedBarPaperAutomationService)
    assert "evaluate_live_signal_admission" not in base_source
    assert "LiveSignalAdmissionDecision" not in base_source


def test_allowed_processing_delegates_to_base_and_restores_database(monkeypatch):
    database = _Database()
    service = _service(database)
    seen = {}

    def fake_process(self, *, trading_date, lots=1, queue_only=False):
        seen["database"] = self.database
        seen["engine_database"] = self.engine.database
        seen["arguments"] = (trading_date, lots, queue_only)
        return (0, 0, 0, [])

    monkeypatch.setattr(
        RedBarPaperAutomationService,
        "process_new_signals",
        fake_process,
    )

    result = service.process_new_signals(
        trading_date="2026-08-21",
        lots=2,
        queue_only=True,
    )

    assert result == (0, 0, 0, [])
    assert isinstance(seen["database"], _AdmissionDatabaseProxy)
    assert seen["engine_database"] is seen["database"]
    assert seen["arguments"] == ("2026-08-21", 2, True)
    assert service.database is database
    assert service.engine.database is database


def test_processing_restores_database_when_base_engine_raises(monkeypatch):
    database = _Database()
    service = _service(database)

    def fail_process(self, *, trading_date, lots=1, queue_only=False):
        assert isinstance(self.database, _AdmissionDatabaseProxy)
        raise RuntimeError("compatibility failure")

    monkeypatch.setattr(
        RedBarPaperAutomationService,
        "process_new_signals",
        fail_process,
    )

    with pytest.raises(RuntimeError, match="compatibility failure"):
        service.process_new_signals(trading_date="2026-08-21")

    assert service.database is database
    assert service.engine.database is database


def test_unresolved_legacy_queue_rows_remain_approved_and_delegate(monkeypatch):
    database = _Database(
        queue=[
            {
                "queue_id": "Q-LEGACY",
                "signal_id": "LEGACY-UNKNOWN",
                "status": "APPROVED",
            }
        ]
    )
    service = _service(database)
    service._current_time = lambda: datetime(
        2026, 8, 21, 10, 0, tzinfo=IST
    )
    delegated = {}

    def fake_execute(self, *, trading_date, lots=1):
        delegated["arguments"] = (trading_date, lots)
        return (1, [])

    monkeypatch.setattr(
        RedBarPaperAutomationService,
        "execute_approved_queue",
        fake_execute,
    )

    result = service.execute_approved_queue(
        trading_date="2026-08-21",
        lots=1,
    )

    assert result == (1, [])
    assert delegated["arguments"] == ("2026-08-21", 1)
    assert database.expired == []
    assert database.diagnostics == []
    assert database.events == []


def test_queue_guard_is_noop_when_queue_api_is_unavailable(monkeypatch):
    database = SimpleNamespace(
        read_signal_attempts=lambda instrument_key, trading_date: []
    )
    service = _service(database)
    service._current_time = lambda: datetime(
        2026, 8, 21, 10, 0, tzinfo=IST
    )

    monkeypatch.setattr(
        RedBarPaperAutomationService,
        "execute_approved_queue",
        lambda self, *, trading_date, lots=1: (0, []),
    )

    assert service.execute_approved_queue(
        trading_date="2026-08-21"
    ) == (0, [])
