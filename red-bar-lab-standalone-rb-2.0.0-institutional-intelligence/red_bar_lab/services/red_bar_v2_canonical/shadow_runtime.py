from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Lock, Thread
from time import perf_counter_ns
from types import MappingProxyType
from typing import Protocol, TypeAlias

from red_bar_lab.domain.red_bar_v2 import ContextStatus
from red_bar_lab.services.red_bar_v2_market_data_evidence import persist_stage_latency

from .models import LegacyV2MarketMetadata
from .persistence_models import PersistenceOutcome
from .persistence_service import RedBarV2CanonicalPersistenceService
from .shadow_coordinator import (
    RedBarV2CanonicalShadowCoordinator,
    RedBarV2ShadowObservation,
)
from .sqlite_repository import SQLiteRedBarV2CanonicalRepository

_LOGGER = logging.getLogger(__name__)

FrozenValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | datetime
    | tuple["FrozenValue", ...]
    | Mapping[str, "FrozenValue"]
)
TelemetrySink: TypeAlias = Callable[[dict[str, object]], None]
CoordinatorFactory: TypeAlias = Callable[[], RedBarV2CanonicalShadowCoordinator]


class ReplayLike(Protocol):
    instrument_key: str
    trading_date: str
    reference_timestamp: datetime | None
    reference_midpoint: float | None


class HealthLike(Protocol):
    status: str
    reason: str
    price_source_instrument: str
    rsi_source_instrument: str
    vwap_source_instrument: str
    timeframe: str
    index_rows: int
    futures_rows: int
    aligned_rows: int
    alignment_coverage_pct: float
    positive_volume_rows: int
    index_timestamp: datetime | None
    futures_timestamp: datetime | None
    last_aligned_timestamp: datetime | None
    execution_scope: str


class ReplayEventLike(Protocol):
    timestamp: datetime
    event_type: str
    direction: str | None
    option_side: str | None
    admission_code: str | None
    candidate_allowed: bool | None
    trade_id: str | None
    details: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CanonicalReplaySnapshot:
    instrument_key: str
    trading_date: str
    reference_timestamp: datetime | None
    reference_midpoint: float | None


@dataclass(frozen=True, slots=True)
class CanonicalHealthSnapshot:
    status: str
    reason: str
    price_source_instrument: str
    rsi_source_instrument: str
    vwap_source_instrument: str
    timeframe: str
    index_rows: int
    futures_rows: int
    aligned_rows: int
    alignment_coverage_pct: float
    positive_volume_rows: int
    index_timestamp: datetime | None
    futures_timestamp: datetime | None
    last_aligned_timestamp: datetime | None
    execution_scope: str


@dataclass(frozen=True, slots=True)
class CanonicalReplayEventSnapshot:
    timestamp: datetime
    event_type: str
    direction: str | None
    option_side: str | None
    admission_code: str | None
    candidate_allowed: bool | None
    trade_id: str | None
    details: Mapping[str, FrozenValue]


@dataclass(frozen=True, slots=True)
class RedBarV2ShadowTask:
    source_replay_id: str
    event_timestamp: datetime
    replay_snapshot: CanonicalReplaySnapshot
    health_snapshot: CanonicalHealthSnapshot
    replay_event_snapshot: CanonicalReplayEventSnapshot
    market_metadata: LegacyV2MarketMetadata


class _BoundedIdTracker:
    def __init__(self, limit: int) -> None:
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("ID tracker limit must be a positive integer")
        self._limit = limit
        self._items: OrderedDict[str, None] = OrderedDict()

    def __contains__(self, source_replay_id: str) -> bool:
        return source_replay_id in self._items

    def __len__(self) -> int:
        return len(self._items)

    def add(self, source_replay_id: str) -> None:
        self._items.pop(source_replay_id, None)
        self._items[source_replay_id] = None
        while len(self._items) > self._limit:
            self._items.popitem(last=False)

    def discard(self, source_replay_id: str) -> None:
        self._items.pop(source_replay_id, None)

    def ids(self) -> tuple[str, ...]:
        return tuple(self._items)


def _freeze_value(value: object) -> FrozenValue:
    if value is None or isinstance(value, (str, int, float, bool, datetime)):
        return value
    if isinstance(value, Mapping):
        frozen = {str(key): _freeze_value(item) for key, item in value.items()}
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    raise TypeError(f"unsupported shadow snapshot value: {type(value).__name__}")


def build_shadow_task(
    *,
    replay: ReplayLike,
    health: HealthLike,
    replay_event: ReplayEventLike,
    market_metadata: LegacyV2MarketMetadata,
    source_replay_id: str,
) -> RedBarV2ShadowTask:
    details = _freeze_value(replay_event.details)
    if not isinstance(details, Mapping):
        raise TypeError("replay event details must freeze to a mapping")
    replay_snapshot = CanonicalReplaySnapshot(
        instrument_key=str(replay.instrument_key),
        trading_date=str(replay.trading_date),
        reference_timestamp=replay.reference_timestamp,
        reference_midpoint=replay.reference_midpoint,
    )
    health_snapshot = CanonicalHealthSnapshot(
        status=str(health.status),
        reason=str(health.reason),
        price_source_instrument=str(health.price_source_instrument),
        rsi_source_instrument=str(health.rsi_source_instrument),
        vwap_source_instrument=str(health.vwap_source_instrument),
        timeframe=str(health.timeframe),
        index_rows=int(health.index_rows),
        futures_rows=int(health.futures_rows),
        aligned_rows=int(health.aligned_rows),
        alignment_coverage_pct=float(health.alignment_coverage_pct),
        positive_volume_rows=int(health.positive_volume_rows),
        index_timestamp=health.index_timestamp,
        futures_timestamp=health.futures_timestamp,
        last_aligned_timestamp=health.last_aligned_timestamp,
        execution_scope=str(health.execution_scope),
    )
    event_snapshot = CanonicalReplayEventSnapshot(
        timestamp=replay_event.timestamp,
        event_type=str(replay_event.event_type),
        direction=replay_event.direction,
        option_side=replay_event.option_side,
        admission_code=replay_event.admission_code,
        candidate_allowed=replay_event.candidate_allowed,
        trade_id=replay_event.trade_id,
        details=details,
    )
    return RedBarV2ShadowTask(
        source_replay_id=source_replay_id,
        event_timestamp=replay_event.timestamp,
        replay_snapshot=replay_snapshot,
        health_snapshot=health_snapshot,
        replay_event_snapshot=event_snapshot,
        market_metadata=market_metadata,
    )


def _parse_timestamp(value: object, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = fallback
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("authoritative timestamp must be timezone-aware")
    return parsed


def _details(event: ReplayEventLike) -> Mapping[str, object]:
    return event.details


def _event_health(
    details: Mapping[str, object],
    fallback: HealthLike,
) -> Mapping[str, object]:
    value = details.get("vwap_source_health")
    if isinstance(value, Mapping):
        return value
    return {"status": fallback.status, "reason": fallback.reason}


def build_runtime_source_replay_id(
    *,
    instrument_key: str,
    trading_date: str,
    event: ReplayEventLike,
) -> str:
    timestamp = event.timestamp
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("event timestamp must be timezone-aware")
    details = _details(event)
    payload = {
        "instrument_key": instrument_key,
        "trading_date": trading_date,
        "timestamp_utc": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event_type": event.event_type,
        "admission_code": event.admission_code,
        "decision_id": details.get("decision_id"),
        "reversal_event_id": details.get("reversal_event_id"),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"RBV2-RUNTIME-{hashlib.sha256(encoded).hexdigest()[:24]}"


def build_runtime_market_metadata(
    *,
    replay: ReplayLike,
    health: HealthLike,
    event: ReplayEventLike,
    instrument_key: str,
    futures_instrument_key: str,
    futures_expiry: str | None,
) -> LegacyV2MarketMetadata:
    event_timestamp = event.timestamp
    if event_timestamp.tzinfo is None or event_timestamp.utcoffset() is None:
        raise ValueError("event timestamp must be timezone-aware")
    details = _details(event)
    event_health = _event_health(details, health)
    index_timestamp = _parse_timestamp(details.get("index_context_timestamp"), event_timestamp)
    futures_timestamp = _parse_timestamp(details.get("futures_source_timestamp"), event_timestamp)
    reference_timestamp = _parse_timestamp(details.get("reference_timestamp"), event_timestamp)
    expiry = date.fromisoformat(futures_expiry) if futures_expiry else None
    health_status = str(event_health.get("status", "UNAVAILABLE"))
    health_reason = str(event_health.get("reason", health_status))
    status = ContextStatus.FRESH if health_status == "READY" else ContextStatus.UNAVAILABLE
    return LegacyV2MarketMetadata(
        strategy_version="2.0.0",
        trading_date=date.fromisoformat(str(replay.trading_date)),
        evaluated_at=event_timestamp,
        source_name="MONITORED_FUTURES_REPLAY",
        source_version="1",
        context_status=status,
        maximum_age_seconds=120,
        latest_index_1m=index_timestamp,
        latest_index_5m=index_timestamp,
        latest_futures_1m=futures_timestamp,
        latest_futures_5m=futures_timestamp,
        underlying_instrument_key=instrument_key,
        futures_instrument_key=futures_instrument_key,
        futures_expiry=expiry,
        futures_volume_available=float(details.get("futures_volume", 0.0) or 0.0) > 0,
        futures_vwap_available=details.get("futures_vwap") is not None,
        reason_code=health_status,
        reason=health_reason,
        reference_id=str(details.get("reference_id")) if details.get("reference_id") is not None else None,
        reference_timestamp=reference_timestamp,
        reference_high=float(details["reference_high"]) if details.get("reference_high") is not None else None,
        reference_low=float(details["reference_low"]) if details.get("reference_low") is not None else None,
        reference_midpoint=float(details["reference_midpoint"]) if details.get("reference_midpoint") is not None else None,
        reference_source=str(details.get("reference_source")) if details.get("reference_source") is not None else None,
    )


class RedBarV2CanonicalShadowRuntime:
    """Bounded non-blocking live shadow runtime with lazy worker initialization."""

    def __init__(
        self,
        coordinator_factory: CoordinatorFactory,
        *,
        queue_size: int = 128,
        completed_limit: int = 4096,
        terminal_limit: int = 512,
        telemetry_sink: TelemetrySink | None = None,
    ) -> None:
        if not isinstance(queue_size, int) or queue_size <= 0:
            raise ValueError("queue_size must be a positive integer")
        self._coordinator_factory = coordinator_factory
        self._coordinator: RedBarV2CanonicalShadowCoordinator | None = None
        self._queue: Queue[RedBarV2ShadowTask] = Queue(maxsize=queue_size)
        self._submission_lock = Lock()
        self._queued_or_in_flight_ids: set[str] = set()
        self._completed_ids = _BoundedIdTracker(completed_limit)
        self._terminal_failure_ids = _BoundedIdTracker(terminal_limit)
        self._telemetry_sink = telemetry_sink
        self._worker = Thread(
            target=self._run,
            name="rbv2-canonical-shadow",
            daemon=True,
        )
        self._worker.start()

    def _emit(self, reason_code: str, task: RedBarV2ShadowTask, **extra: object) -> None:
        record: dict[str, object] = {
            "reason_code": reason_code,
            "source_replay_id": task.source_replay_id,
            "event_timestamp": task.event_timestamp.isoformat(),
            **extra,
        }
        try:
            if self._telemetry_sink is not None:
                self._telemetry_sink(record)
            else:
                _LOGGER.info("red_bar_v2_shadow", extra={"shadow": record})
        except Exception:
            _LOGGER.exception(
                "red_bar_v2_shadow_telemetry_failed",
                extra={
                    "shadow": {
                        "reason_code": reason_code,
                        "source_replay_id": task.source_replay_id,
                        "event_timestamp": task.event_timestamp.isoformat(),
                    }
                },
            )

    def submit(self, task: RedBarV2ShadowTask) -> bool:
        with self._submission_lock:
            source_id = task.source_replay_id
            if source_id in self._terminal_failure_ids:
                self._emit("SHADOW_TERMINAL_FAILURE", task)
                return False
            if source_id in self._completed_ids:
                self._emit("SHADOW_ALREADY_COMPLETED", task)
                return False
            if source_id in self._queued_or_in_flight_ids:
                self._emit("SHADOW_DUPLICATE_IN_FLIGHT", task)
                return False
            try:
                self._queue.put_nowait(task)
            except Full:
                try:
                    stale = self._queue.get_nowait()
                except Empty:
                    return False
                self._queue.task_done()
                self._queued_or_in_flight_ids.discard(stale.source_replay_id)
                self._emit(
                    "SHADOW_STALE_TASK_REPLACED",
                    stale,
                    replacement_source_replay_id=source_id,
                )
                try:
                    self._queue.put_nowait(task)
                except Full:
                    return False
            self._queued_or_in_flight_ids.add(source_id)
            self._emit("SHADOW_QUEUED", task)
            return True

    def _get_coordinator(self, task: RedBarV2ShadowTask) -> RedBarV2CanonicalShadowCoordinator | None:
        if self._coordinator is not None:
            return self._coordinator
        started = perf_counter_ns()
        try:
            coordinator = self._coordinator_factory()
        except Exception as error:
            self._emit(
                "SHADOW_INITIALIZATION_FAILED",
                task,
                error_category="PERSISTENCE_UNAVAILABLE",
                exception_class=type(error).__name__,
                duration_ms=(perf_counter_ns() - started) / 1_000_000.0,
            )
            return None
        self._coordinator = coordinator
        return coordinator

    def _finish(
        self,
        task: RedBarV2ShadowTask,
        observation: RedBarV2ShadowObservation | None,
    ) -> None:
        source_id = task.source_replay_id
        with self._submission_lock:
            self._queued_or_in_flight_ids.discard(source_id)
            if observation is None:
                self._emit("SHADOW_RETRY_RELEASED", task, error_category="INITIALIZATION_FAILED")
                return
            if observation.outcome in {
                PersistenceOutcome.INSERTED,
                PersistenceOutcome.IDEMPOTENT_REPLAY,
            }:
                self._completed_ids.add(source_id)
                return
            if observation.error_category in {
                "PERSISTENCE_CONFLICT",
                "PERSISTENCE_CORRUPTION",
            }:
                self._terminal_failure_ids.add(source_id)
                self._emit(
                    "SHADOW_TERMINAL_FAILURE",
                    task,
                    error_category=observation.error_category,
                )
                return
            self._emit(
                "SHADOW_RETRY_RELEASED",
                task,
                error_category=observation.error_category or observation.reason_code,
            )

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            observation: RedBarV2ShadowObservation | None = None
            try:
                coordinator = self._get_coordinator(task)
                if coordinator is not None:
                    observation = coordinator.observe(
                        replay=task.replay_snapshot,
                        health=task.health_snapshot,
                        replay_event=task.replay_event_snapshot,
                        market_metadata=task.market_metadata,
                        legacy_result=task.replay_event_snapshot,
                        source_replay_id=task.source_replay_id,
                        event_timestamp=task.event_timestamp,
                    )
            except Exception as error:
                self._emit(
                    "SHADOW_RETRY_RELEASED",
                    task,
                    error_category="UNEXPECTED_SHADOW_FAILURE",
                    exception_class=type(error).__name__,
                )
            finally:
                try:
                    self._finish(task, observation)
                finally:
                    self._queue.task_done()


_RUNTIME_LOCK = Lock()
_RUNTIMES: dict[str, RedBarV2CanonicalShadowRuntime] = {}


def _canonical_stage_latency_rows(record: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    raw_timings = record.get("stage_timings_ms")
    timings = raw_timings if isinstance(raw_timings, Mapping) else {}

    def duration(name: str) -> float | None:
        value = timings.get(name)
        return float(value) if isinstance(value, (int, float)) else None

    total = record.get("duration_ms")
    total_ms = float(total) if isinstance(total, (int, float)) else None
    return (
        {"stage_id": "INPUT_READINESS", "status": "COUPLED", "duration_ms": None, "detail": "Measured within canonical resolution"},
        {"stage_id": "STRATEGY_DECISION", "status": "MEASURED", "duration_ms": duration("resolution"), "detail": "Canonical Sections 1-3 resolution"},
        {"stage_id": "SIGNAL_BUNDLE", "status": "COUPLED", "duration_ms": None, "detail": "Measured within canonical resolution"},
        {"stage_id": "ARCHITECTURE_PARITY", "status": "MEASURED", "duration_ms": duration("parity"), "detail": "Legacy-to-canonical parity comparison"},
        {"stage_id": "PERSISTENCE_INTEGRITY", "status": "MEASURED", "duration_ms": duration("persistence"), "detail": "Canonical durable persistence"},
        {"stage_id": "RECENT_OBSERVATIONS", "status": "UI_ONLY", "duration_ms": None, "detail": "Read-only UI projection"},
        {"stage_id": "PROCESS_EXPLANATION", "status": "UI_ONLY", "duration_ms": None, "detail": "Read-only UI projection"},
        {"stage_id": "OPPORTUNITY_QUEUE", "status": "NOT_EXECUTED_IN_SHADOW", "duration_ms": None, "detail": "Canonical shadow has no queue authority"},
        {"stage_id": "RESERVATION_BOUNDARY", "status": "NOT_EXECUTED_IN_SHADOW", "duration_ms": None, "detail": "Canonical shadow has no reservation authority"},
        {"stage_id": "PAPER_EXECUTION", "status": "NOT_EXECUTED_IN_SHADOW", "duration_ms": None, "detail": "Legacy V2 remains paper authority"},
        {"stage_id": "RUNTIME_HEALTH", "status": "MEASURED", "duration_ms": total_ms, "detail": "Total canonical shadow observation"},
        {"stage_id": "PROVIDER_READINESS", "status": "SHARED_SOURCE", "duration_ms": None, "detail": "Uses the legacy live-event market snapshot"},
    )


def _build_coordinator_factory(
    database_path: Path,
    artifacts_root: Path | None = None,
) -> CoordinatorFactory:
    def emit(record: dict[str, object]) -> None:
        _LOGGER.info("red_bar_v2_shadow", extra={"shadow": record})
        if artifacts_root is None:
            return
        correlation_id = record.get("source_replay_id")
        if not isinstance(correlation_id, str) or not correlation_id:
            return
        try:
            persist_stage_latency(
                artifacts_root,
                architecture="canonical",
                correlation_id=correlation_id,
                stages=list(_canonical_stage_latency_rows(record)),
                recorded_at=datetime.now(timezone.utc),
            )
        except (OSError, TypeError, ValueError):
            _LOGGER.warning(
                "red_bar_v2_canonical_stage_latency_persist_failed",
                extra={"source_replay_id": correlation_id},
                exc_info=True,
            )

    def factory() -> RedBarV2CanonicalShadowCoordinator:
        repository = SQLiteRedBarV2CanonicalRepository(database_path, busy_timeout_ms=250)
        service = RedBarV2CanonicalPersistenceService(repository)
        return RedBarV2CanonicalShadowCoordinator(
            service,
            enabled=True,
            telemetry_sink=emit,
        )

    return factory


def get_red_bar_v2_shadow_runtime(
    *,
    enabled: bool,
    database_path: Path,
    artifacts_root: Path | None = None,
) -> RedBarV2CanonicalShadowRuntime | None:
    if not enabled:
        return None
    path = Path(database_path)
    key = str(path.resolve())
    with _RUNTIME_LOCK:
        existing = _RUNTIMES.get(key)
        if existing is not None:
            return existing
        runtime = RedBarV2CanonicalShadowRuntime(
            coordinator_factory=_build_coordinator_factory(path, artifacts_root),
        )
        _RUNTIMES[key] = runtime
        return runtime
