from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import logging
from pathlib import Path
from queue import Full, Queue
from threading import Lock, Thread
from typing import Mapping

from red_bar_lab.domain.red_bar_v2 import ContextStatus

from .models import LegacyV2MarketMetadata
from .persistence_service import RedBarV2CanonicalPersistenceService
from .shadow_coordinator import RedBarV2CanonicalShadowCoordinator
from .sqlite_repository import SQLiteRedBarV2CanonicalRepository

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RedBarV2ShadowTask:
    replay: object
    health: object
    replay_event: object
    market_metadata: LegacyV2MarketMetadata
    source_replay_id: str
    event_timestamp: datetime


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


def _details(event: object) -> Mapping[str, object]:
    value = getattr(event, "details", None)
    return value if isinstance(value, Mapping) else {}


def build_runtime_source_replay_id(
    *,
    instrument_key: str,
    trading_date: str,
    event: object,
) -> str:
    timestamp = getattr(event, "timestamp", None)
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
        raise ValueError("event timestamp must be timezone-aware")
    details = _details(event)
    payload = {
        "instrument_key": instrument_key,
        "trading_date": trading_date,
        "timestamp_utc": timestamp.astimezone().isoformat(),
        "event_type": getattr(event, "event_type", None),
        "admission_code": getattr(event, "admission_code", None),
        "decision_id": details.get("decision_id"),
        "reversal_event_id": details.get("reversal_event_id"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return f"RBV2-RUNTIME-{hashlib.sha256(encoded).hexdigest()[:24]}"


def build_runtime_market_metadata(
    *,
    replay: object,
    health: object,
    event: object,
    instrument_key: str,
    futures_instrument_key: str,
    futures_expiry: str | None,
) -> LegacyV2MarketMetadata:
    event_timestamp = getattr(event, "timestamp", None)
    if not isinstance(event_timestamp, datetime):
        raise ValueError("event timestamp is required")
    details = _details(event)
    index_timestamp = _parse_timestamp(details.get("index_context_timestamp"), event_timestamp)
    futures_timestamp = _parse_timestamp(details.get("futures_source_timestamp"), event_timestamp)
    reference_timestamp = _parse_timestamp(details.get("reference_timestamp"), event_timestamp)
    expiry = date.fromisoformat(futures_expiry) if futures_expiry else None
    health_status = str(getattr(health, "status", "UNAVAILABLE"))
    status = ContextStatus.FRESH if health_status == "READY" else ContextStatus.UNAVAILABLE
    trading_date_text = str(getattr(replay, "trading_date"))
    return LegacyV2MarketMetadata(
        strategy_version="2.0.0",
        trading_date=date.fromisoformat(trading_date_text),
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
        reason=str(getattr(health, "reason", health_status)),
        reference_id=str(details.get("reference_id")) if details.get("reference_id") is not None else None,
        reference_timestamp=reference_timestamp,
        reference_high=float(details["reference_high"]) if details.get("reference_high") is not None else None,
        reference_low=float(details["reference_low"]) if details.get("reference_low") is not None else None,
        reference_midpoint=float(details["reference_midpoint"]) if details.get("reference_midpoint") is not None else None,
        reference_source=str(details.get("reference_source")) if details.get("reference_source") is not None else None,
    )


class RedBarV2CanonicalShadowRuntime:
    """One bounded non-blocking worker per background process."""

    def __init__(self, coordinator: RedBarV2CanonicalShadowCoordinator, *, queue_size: int = 128) -> None:
        self._coordinator = coordinator
        self._queue: Queue[RedBarV2ShadowTask] = Queue(maxsize=queue_size)
        self._worker = Thread(target=self._run, name="rbv2-canonical-shadow", daemon=True)
        self._worker.start()

    def submit(self, task: RedBarV2ShadowTask) -> bool:
        try:
            self._queue.put_nowait(task)
            return True
        except Full:
            _LOGGER.warning("red_bar_v2_shadow", extra={"reason_code": "SHADOW_QUEUE_FULL"})
            return False

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            try:
                self._coordinator.observe(
                    replay=task.replay,
                    health=task.health,
                    replay_event=task.replay_event,
                    market_metadata=task.market_metadata,
                    legacy_result=task.replay_event,
                    source_replay_id=task.source_replay_id,
                    event_timestamp=task.event_timestamp,
                )
            except Exception:
                _LOGGER.exception("red_bar_v2_shadow_worker_failure")
            finally:
                self._queue.task_done()


_RUNTIME_LOCK = Lock()
_RUNTIMES: dict[str, RedBarV2CanonicalShadowRuntime] = {}


def get_red_bar_v2_shadow_runtime(
    *,
    enabled: bool,
    database_path: Path,
) -> RedBarV2CanonicalShadowRuntime | None:
    if not enabled:
        return None
    key = str(Path(database_path).resolve())
    with _RUNTIME_LOCK:
        existing = _RUNTIMES.get(key)
        if existing is not None:
            return existing
        repository = SQLiteRedBarV2CanonicalRepository(Path(database_path), busy_timeout_ms=250)
        service = RedBarV2CanonicalPersistenceService(repository)
        coordinator = RedBarV2CanonicalShadowCoordinator(
            service,
            enabled=True,
            telemetry_sink=lambda record: _LOGGER.info("red_bar_v2_shadow", extra={"shadow": record}),
        )
        runtime = RedBarV2CanonicalShadowRuntime(coordinator)
        _RUNTIMES[key] = runtime
        return runtime
