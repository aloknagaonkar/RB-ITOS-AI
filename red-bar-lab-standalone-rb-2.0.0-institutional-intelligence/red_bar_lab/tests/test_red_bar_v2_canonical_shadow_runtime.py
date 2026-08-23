from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from threading import Event
from types import MappingProxyType

import pytest

from red_bar_lab.domain.red_bar_v2 import ContextStatus
from red_bar_lab.services.red_bar_v2_canonical.models import LegacyV2MarketMetadata
from red_bar_lab.services.red_bar_v2_canonical.persistence_models import PersistenceOutcome
from red_bar_lab.services.red_bar_v2_canonical.shadow_coordinator import RedBarV2ShadowObservation
from red_bar_lab.services.red_bar_v2_canonical.shadow_runtime import (
    CanonicalHealthSnapshot,
    CanonicalReplayEventSnapshot,
    CanonicalReplaySnapshot,
    RedBarV2CanonicalShadowRuntime,
    RedBarV2ShadowTask,
    _BoundedIdTracker,
)

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 8, 24, 10, 0, tzinfo=IST)


def _metadata() -> LegacyV2MarketMetadata:
    return LegacyV2MarketMetadata(
        strategy_version="2.0.0",
        trading_date=date(2026, 8, 24),
        evaluated_at=NOW,
        source_name="TEST",
        source_version="1",
        context_status=ContextStatus.FRESH,
        maximum_age_seconds=120,
        latest_index_1m=NOW,
        latest_index_5m=NOW,
        latest_futures_1m=NOW,
        latest_futures_5m=NOW,
        underlying_instrument_key="NSE_INDEX|Nifty 50",
        futures_instrument_key="NSE_FO|NIFTY-FUT",
        futures_expiry=date(2026, 8, 27),
        futures_volume_available=True,
        futures_vwap_available=True,
        reason_code="READY",
        reason="READY",
        reference_id="REF-1",
        reference_timestamp=NOW,
        reference_high=101.0,
        reference_low=99.0,
        reference_midpoint=100.0,
        reference_source="TEST",
    )


def _task(source_id: str) -> RedBarV2ShadowTask:
    replay = CanonicalReplaySnapshot(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-24",
        reference_timestamp=NOW,
        reference_midpoint=100.0,
    )
    health = CanonicalHealthSnapshot(
        status="READY",
        reason="READY",
        price_source_instrument="NSE_INDEX|Nifty 50",
        rsi_source_instrument="NSE_INDEX|Nifty 50",
        vwap_source_instrument="NSE_FO|NIFTY-FUT",
        timeframe="1m",
        index_rows=50,
        futures_rows=50,
        aligned_rows=50,
        alignment_coverage_pct=100.0,
        positive_volume_rows=50,
        index_timestamp=NOW,
        futures_timestamp=NOW,
        last_aligned_timestamp=NOW,
        execution_scope="SHADOW_ONLY",
    )
    event = CanonicalReplayEventSnapshot(
        timestamp=NOW,
        event_type="CANDIDATE_ADMISSION",
        direction="BULLISH",
        option_side="CE",
        admission_code="V2_ADMITTED",
        candidate_allowed=True,
        trade_id=None,
        details=MappingProxyType({"trend_strength": "CONFIRMED"}),
    )
    return RedBarV2ShadowTask(
        source_replay_id=source_id,
        event_timestamp=NOW,
        replay_snapshot=replay,
        health_snapshot=health,
        replay_event_snapshot=event,
        market_metadata=_metadata(),
    )


def _observation(
    *,
    outcome: PersistenceOutcome | None = PersistenceOutcome.INSERTED,
    error_category: str | None = None,
) -> RedBarV2ShadowObservation:
    return RedBarV2ShadowObservation(
        attempted=True,
        persisted=outcome is not None,
        outcome=outcome,
        resolution_id="RES-1" if outcome else None,
        bundle_id="BUNDLE-1" if outcome else None,
        parity_matches=True if outcome else None,
        reason_code=error_category or "PERSISTED",
        duration_ms=0.1,
        error_category=error_category,
    )


class _Coordinator:
    def __init__(
        self,
        result: RedBarV2ShadowObservation,
        *,
        entered: Event | None = None,
        release: Event | None = None,
    ) -> None:
        self.result = result
        self.entered = entered
        self.release = release
        self.calls = 0

    def observe(self, **kwargs):
        self.calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            assert self.release.wait(2)
        return self.result


def test_runtime_construction_is_lightweight_and_worker_initializes_factory():
    factory_called = Event()
    release_factory = Event()
    processed = Event()

    class Coordinator(_Coordinator):
        def observe(self, **kwargs):
            result = super().observe(**kwargs)
            processed.set()
            return result

    coordinator = Coordinator(_observation())

    def factory():
        factory_called.set()
        assert release_factory.wait(2)
        return coordinator

    runtime = RedBarV2CanonicalShadowRuntime(factory)
    assert not factory_called.is_set()
    assert runtime.submit(_task("A")) is True
    assert factory_called.wait(2)
    release_factory.set()
    assert processed.wait(2)


def test_duplicate_while_processing_is_rejected_and_success_completes():
    entered = Event()
    release = Event()
    coordinator = _Coordinator(_observation(), entered=entered, release=release)
    runtime = RedBarV2CanonicalShadowRuntime(lambda: coordinator)
    task = _task("A")
    assert runtime.submit(task) is True
    assert entered.wait(2)
    assert runtime.submit(task) is False
    release.set()
    runtime._queue.join()
    assert "A" in runtime._completed_ids
    assert runtime.submit(task) is False


def test_initialization_failure_releases_id_for_later_retry():
    retry_released = Event()
    attempts = 0
    coordinator = _Coordinator(_observation())

    def telemetry(record):
        if record["reason_code"] == "SHADOW_RETRY_RELEASED":
            retry_released.set()

    def factory():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporarily unavailable")
        return coordinator

    runtime = RedBarV2CanonicalShadowRuntime(factory, telemetry_sink=telemetry)
    task = _task("A")
    assert runtime.submit(task) is True
    assert retry_released.wait(2)
    assert runtime.submit(task) is True
    runtime._queue.join()
    assert "A" in runtime._completed_ids
    assert attempts == 2
    assert coordinator.calls == 1


@pytest.mark.parametrize(
    "category",
    ["PERSISTENCE_UNAVAILABLE", "RESOLUTION_FAILED", "INPUT_UNAVAILABLE"],
)
def test_transient_coordinator_failures_release_for_retry(category):
    released = Event()
    coordinator = _Coordinator(_observation(outcome=None, error_category=category))
    runtime = RedBarV2CanonicalShadowRuntime(
        lambda: coordinator,
        telemetry_sink=lambda record: released.set()
        if record["reason_code"] == "SHADOW_RETRY_RELEASED"
        else None,
    )
    task = _task(category)
    assert runtime.submit(task) is True
    assert released.wait(2)
    assert runtime.submit(task) is True


@pytest.mark.parametrize(
    "category",
    ["PERSISTENCE_CONFLICT", "PERSISTENCE_CORRUPTION"],
)
def test_permanent_failures_are_quarantined(category):
    terminal = Event()
    coordinator = _Coordinator(_observation(outcome=None, error_category=category))
    runtime = RedBarV2CanonicalShadowRuntime(
        lambda: coordinator,
        telemetry_sink=lambda record: terminal.set()
        if record["reason_code"] == "SHADOW_TERMINAL_FAILURE"
        else None,
    )
    task = _task(category)
    assert runtime.submit(task) is True
    assert terminal.wait(2)
    assert runtime.submit(task) is False
    assert category in runtime._terminal_failure_ids


def test_queue_replacement_releases_displaced_id():
    entered = Event()
    release = Event()
    coordinator = _Coordinator(_observation(), entered=entered, release=release)
    runtime = RedBarV2CanonicalShadowRuntime(lambda: coordinator, queue_size=1)
    first = _task("FIRST")
    second = _task("SECOND")
    newest = _task("NEWEST")
    assert runtime.submit(first) is True
    assert entered.wait(2)
    assert runtime.submit(second) is True
    assert runtime.submit(newest) is True
    assert "SECOND" not in runtime._queued_or_in_flight_ids
    assert "NEWEST" in runtime._queued_or_in_flight_ids
    release.set()


def test_bounded_trackers_evict_oldest_deterministically():
    tracker = _BoundedIdTracker(2)
    tracker.add("A")
    tracker.add("B")
    tracker.add("C")
    assert tracker.ids() == ("B", "C")
    assert len(tracker) == 2


def test_compact_task_is_immutable_and_contains_no_full_replay_graph():
    task = _task("A")
    assert not hasattr(task, "replay")
    assert not hasattr(task, "health")
    assert not hasattr(task, "events")
    with pytest.raises(TypeError):
        task.replay_event_snapshot.details["new"] = "value"
