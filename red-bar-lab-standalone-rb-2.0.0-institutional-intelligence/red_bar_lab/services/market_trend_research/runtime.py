from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event
from time import monotonic
from typing import Generic, TypeVar
from zoneinfo import ZoneInfo

from .collector import CollectionResult, UpstoxResearchChainCollector
from .repository import MarketTrendResearchRepository
from .service import MarketTrendResearchService

IST = ZoneInfo("Asia/Kolkata")
T = TypeVar("T")


class LatestValueSlot(Generic[T]):
    """Capacity-one slot; newer complete work replaces pending obsolete work."""

    def __init__(self) -> None:
        self._value: T | None = None
        self.dropped = 0

    def put(self, value: T) -> None:
        if self._value is not None:
            self.dropped += 1
        self._value = value

    def take(self) -> T | None:
        value = self._value
        self._value = None
        return value


@dataclass(frozen=True, slots=True)
class ResearchRuntimeConfig:
    enabled: bool = False
    refresh_seconds: float = 5.0
    maximum_backoff_seconds: float = 60.0
    maximum_consecutive_failures: int = 100

    def __post_init__(self) -> None:
        if not 2.0 <= self.refresh_seconds <= 60.0:
            raise ValueError("refresh_seconds invalid")
        if self.maximum_backoff_seconds < self.refresh_seconds:
            raise ValueError("maximum_backoff_seconds invalid")
        if self.maximum_consecutive_failures < 1:
            raise ValueError("maximum_consecutive_failures invalid")


class MarketTrendResearchRuntime:
    """Single observational worker with bounded backoff and no order surface."""

    def __init__(
        self,
        *,
        collector: UpstoxResearchChainCollector,
        service: MarketTrendResearchService,
        repository: MarketTrendResearchRepository,
        config: ResearchRuntimeConfig,
    ) -> None:
        self.collector = collector
        self.service = service
        self.repository = repository
        self.config = config
        self.slot: LatestValueSlot[CollectionResult] = LatestValueSlot()
        self.stop_event = Event()
        self.last_success_at: datetime | None = None
        self.last_failure_at: datetime | None = None
        self.last_failure_reason: str | None = None
        self.consecutive_failures = 0

    @staticmethod
    def _safe_reason(exc: Exception) -> str:
        text = str(exc).strip()
        return text if text.isupper() and len(text) <= 64 else type(exc).__name__.upper()[:64]

    def stop(self) -> None:
        self.stop_event.set()

    def _health(self) -> None:
        self.repository.persist_runtime_health(
            runtime_name="MARKET_TREND_RESEARCH",
            heartbeat_at=datetime.now(timezone.utc),
            last_success_at=self.last_success_at,
            last_failure_at=self.last_failure_at,
            last_failure_reason=self.last_failure_reason,
            consecutive_failures=self.consecutive_failures,
            dropped_obsolete_tasks=self.slot.dropped,
        )

    def run_cycle(self) -> None:
        now = datetime.now(timezone.utc)
        self.collector.capture_reference_once(evaluated_at=now)
        local_time = now.astimezone(IST).time().replace(tzinfo=None)
        if local_time < self.collector.policy.oi_baseline_start:
            self.last_success_at = now
            self.last_failure_at = None
            self.last_failure_reason = None
            self.consecutive_failures = 0
            self._health()
            return
        result = self.collector.collect_once(evaluated_at=now)
        self.slot.put(result)
        latest = self.slot.take()
        if latest is None:
            return
        self.service.evaluate(
            underlying=latest.snapshot.underlying,
            evaluated_at=datetime.now(timezone.utc),
            runtime_mode="CONTINUOUS",
            automatic_refresh="CONNECTED",
            dropped_obsolete_tasks=self.slot.dropped,
            consecutive_failures=self.consecutive_failures,
        )
        self.last_success_at = datetime.now(timezone.utc)
        self.last_failure_at = None
        self.last_failure_reason = None
        self.consecutive_failures = 0
        self._health()

    def run_forever(self) -> None:
        if not self.config.enabled:
            raise ValueError("MARKET_TREND_RESEARCH_RUNTIME_DISABLED")
        while not self.stop_event.is_set():
            cycle_started = monotonic()
            delay = self.config.refresh_seconds
            try:
                self.run_cycle()
            except Exception as exc:
                self.consecutive_failures += 1
                self.last_failure_at = datetime.now(timezone.utc)
                self.last_failure_reason = self._safe_reason(exc)
                self._health()
                exponent = min(self.consecutive_failures - 1, 6)
                delay = min(
                    self.config.maximum_backoff_seconds,
                    self.config.refresh_seconds * (2 ** exponent),
                )
            elapsed = monotonic() - cycle_started
            self.stop_event.wait(max(0.0, delay - elapsed))
