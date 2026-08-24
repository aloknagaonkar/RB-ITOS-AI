from __future__ import annotations

from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from red_bar_lab.services.market_trend_research.runtime import (
    MarketTrendResearchRuntime,
    ResearchRuntimeConfig,
)

IST = ZoneInfo("Asia/Kolkata")


class CalendarStub:
    def __init__(self, *, verified=True, holiday=False):
        self.verified = verified
        self.holiday = holiday

    def sessions_between(self, start: date, end: date):
        return () if self.holiday else (start,)


class CollectorStub:
    def __init__(self, calendar):
        self.calendar = calendar
        self.policy = SimpleNamespace(oi_baseline_start=time(9, 15))
        self.reference_calls = 0
        self.collect_calls = 0

    def capture_reference_once(self, *, evaluated_at):
        self.reference_calls += 1

    def collect_once(self, *, evaluated_at):
        self.collect_calls += 1
        return SimpleNamespace(snapshot=SimpleNamespace(underlying="NIFTY 50"))


class RepositoryStub:
    def __init__(self):
        self.health = []

    def persist_runtime_health(self, **kwargs):
        self.health.append(kwargs)


class ServiceStub:
    def __init__(self):
        self.calls = 0

    def evaluate(self, **kwargs):
        self.calls += 1


def _runtime(now, *, calendar=None, failures=5, cooldown=60.0, monotonic_clock=lambda: 0.0):
    collector = CollectorStub(calendar or CalendarStub())
    repository = RepositoryStub()
    service = ServiceStub()
    runtime = MarketTrendResearchRuntime(
        collector=collector,
        service=service,
        repository=repository,
        config=ResearchRuntimeConfig(
            enabled=True,
            refresh_seconds=5.0,
            maximum_backoff_seconds=60.0,
            maximum_consecutive_failures=failures,
            failure_cooldown_seconds=cooldown,
            session_start=time(9, 8),
            session_end=time(15, 30),
            unattended=True,
        ),
        now=lambda: now,
        monotonic_clock=monotonic_clock,
    )
    return runtime, collector, repository, service


def _utc(local_hour, local_minute, *, day=24):
    return datetime(2026, 8, day, local_hour, local_minute, tzinfo=IST).astimezone(timezone.utc)


def test_before_session_performs_zero_provider_calls_and_heartbeats():
    runtime, collector, repository, service = _runtime(_utc(9, 0))
    runtime.run_cycle()
    assert collector.reference_calls == 0
    assert collector.collect_calls == 0
    assert service.calls == 0
    assert repository.health[-1]["last_failure_reason"] == "WAITING_FOR_SESSION"


def test_after_session_performs_zero_provider_calls():
    runtime, collector, repository, _ = _runtime(_utc(15, 31))
    runtime.run_cycle()
    assert collector.reference_calls == 0
    assert collector.collect_calls == 0
    assert repository.health[-1]["last_failure_reason"] == "SESSION_CLOSED"


def test_weekend_performs_zero_provider_calls():
    runtime, collector, repository, _ = _runtime(_utc(10, 0, day=23))
    runtime.run_cycle()
    assert collector.collect_calls == 0
    assert repository.health[-1]["last_failure_reason"] == "HOLIDAY"


def test_verified_holiday_performs_zero_provider_calls():
    runtime, collector, repository, _ = _runtime(
        _utc(10, 0), calendar=CalendarStub(verified=True, holiday=True)
    )
    runtime.run_cycle()
    assert collector.collect_calls == 0
    assert repository.health[-1]["last_failure_reason"] == "HOLIDAY"


def test_unverified_calendar_fails_closed_for_unattended_runtime():
    runtime, collector, repository, _ = _runtime(
        _utc(10, 0), calendar=CalendarStub(verified=False)
    )
    runtime.run_cycle()
    assert collector.collect_calls == 0
    assert repository.health[-1]["last_failure_reason"] == "CALENDAR_UNVERIFIED"


def test_in_session_collection_continues_normally():
    runtime, collector, repository, service = _runtime(_utc(10, 0))
    runtime.run_cycle()
    assert collector.reference_calls == 1
    assert collector.collect_calls == 1
    assert service.calls == 1
    assert repository.health[-1]["last_failure_reason"] == "COLLECTING"


def test_failure_threshold_opens_circuit_and_half_open_success_recovers():
    clock = {"value": 0.0}
    runtime, collector, repository, service = _runtime(
        _utc(10, 0), failures=2, cooldown=60.0,
        monotonic_clock=lambda: clock["value"],
    )
    runtime._record_failure(ValueError("PROVIDER_FAILED"))
    runtime._record_failure(ValueError("PROVIDER_FAILED"))
    assert runtime.suspended_until_monotonic == 60.0
    runtime.run_cycle()
    assert collector.collect_calls == 0
    assert repository.health[-1]["last_failure_reason"] == "PROVIDER_CIRCUIT_OPEN"

    clock["value"] = 61.0
    runtime.run_cycle()
    assert collector.collect_calls == 1
    assert service.calls == 1
    assert runtime.consecutive_failures == 0
    assert runtime.suspended_until_monotonic is None


def test_stop_is_idempotent():
    runtime, _, _, _ = _runtime(_utc(10, 0))
    runtime.stop()
    runtime.stop()
    assert runtime.stop_event.is_set()
