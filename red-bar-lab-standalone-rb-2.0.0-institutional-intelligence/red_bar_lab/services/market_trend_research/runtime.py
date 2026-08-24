from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from threading import Event
from time import monotonic
from typing import Callable, Generic, TypeVar
from zoneinfo import ZoneInfo

from .collector import CollectionResult, UpstoxResearchChainCollector
from .repository import MarketTrendResearchRepository
from .service import MarketTrendResearchService

IST = ZoneInfo("Asia/Kolkata")
T = TypeVar("T")
_SAFE_REASON_PREFIXES = (
    "BASELINE_", "CALENDAR_", "CURRENT_", "EXPIRY_", "MARKET_",
    "OI_", "PARTIAL_", "PCR_", "PROVIDER_", "REFERENCE_",
    "SESSION_", "SOURCE_", "UPSTOX_",
)


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
    maximum_consecutive_failures: int = 5
    failure_cooldown_seconds: float = 60.0
    session_start: time = time(9, 8)
    session_end: time = time(15, 30)
    unattended: bool = False

    def __post_init__(self) -> None:
        if not 2.0 <= self.refresh_seconds <= 60.0:
            raise ValueError("refresh_seconds invalid")
        if self.maximum_backoff_seconds < self.refresh_seconds:
            raise ValueError("maximum_backoff_seconds invalid")
        if self.maximum_consecutive_failures < 1:
            raise ValueError("maximum_consecutive_failures invalid")
        if self.failure_cooldown_seconds < self.refresh_seconds:
            raise ValueError("failure_cooldown_seconds invalid")
        if self.session_end <= self.session_start:
            raise ValueError("session window invalid")


class MarketTrendResearchRuntime:
    """Single observational worker with session guard and provider-cycle circuit."""

    def __init__(
        self,
        *,
        collector: UpstoxResearchChainCollector,
        service: MarketTrendResearchService,
        repository: MarketTrendResearchRepository,
        config: ResearchRuntimeConfig,
        now: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        self.collector = collector
        self.service = service
        self.repository = repository
        self.config = config
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.monotonic_clock = monotonic_clock
        self.slot: LatestValueSlot[CollectionResult] = LatestValueSlot()
        self.stop_event = Event()
        self.last_success_at: datetime | None = None
        self.last_failure_at: datetime | None = None
        self.last_failure_reason: str | None = None
        self.consecutive_failures = 0
        self.suspended_until_monotonic: float | None = None
        self.half_open = False

    @staticmethod
    def _safe_reason(exc: Exception) -> str:
        text = str(exc).strip().upper()
        if (
            text
            and len(text) <= 64
            and all(character.isalnum() or character in "_-" for character in text)
            and text.startswith(_SAFE_REASON_PREFIXES)
        ):
            return text
        return type(exc).__name__.upper()[:64]

    def stop(self) -> None:
        self.stop_event.set()

    def _health(self, lifecycle: str | None = None) -> None:
        self.repository.persist_runtime_health(
            runtime_name="MARKET_TREND_RESEARCH",
            heartbeat_at=self.now(),
            last_success_at=self.last_success_at,
            last_failure_at=self.last_failure_at,
            last_failure_reason=lifecycle or self.last_failure_reason,
            consecutive_failures=self.consecutive_failures,
            dropped_obsolete_tasks=self.slot.dropped,
        )

    def _session_lifecycle(self, now: datetime) -> str:
        calendar = self.collector.calendar
        if self.config.unattended and not getattr(calendar, "verified", False):
            return "CALENDAR_UNVERIFIED"
        local = now.astimezone(IST)
        if local.weekday() >= 5:
            return "HOLIDAY"
        if getattr(calendar, "verified", False):
            sessions = calendar.sessions_between(local.date(), local.date())
            if not sessions:
                return "HOLIDAY"
        local_time = local.time().replace(tzinfo=None)
        if local_time < self.config.session_start:
            return "WAITING_FOR_SESSION"
        if local_time > self.config.session_end:
            return "SESSION_CLOSED"
        return "COLLECTING"

    def _outside_session(self, now: datetime) -> bool:
        lifecycle = self._session_lifecycle(now)
        if lifecycle == "CALENDAR_UNVERIFIED":
            self.last_failure_at = now
            self.last_failure_reason = lifecycle
            self._health(lifecycle)
            return True
        if lifecycle != "COLLECTING":
            self._health(lifecycle)
            return True
        return False

    def run_cycle(self) -> None:
        now = self.now()
        if self._outside_session(now):
            return
        if self.suspended_until_monotonic is not None:
            if self.monotonic_clock() < self.suspended_until_monotonic:
                self._health("PROVIDER_CIRCUIT_OPEN")
                return
            self.half_open = True
            self.suspended_until_monotonic = None

        self.collector.capture_reference_once(evaluated_at=now)
        local_time = now.astimezone(IST).time().replace(tzinfo=None)
        if local_time < self.collector.policy.oi_baseline_start:
            self.last_success_at = now
            self.last_failure_at = None
            self.last_failure_reason = None
            self.consecutive_failures = 0
            self.half_open = False
            self._health("COLLECTING")
            return
        result = self.collector.collect_once(evaluated_at=now)
        self.slot.put(result)
        latest = self.slot.take()
        if latest is None:
            return
        self.service.evaluate(
            underlying=latest.snapshot.underlying,
            evaluated_at=self.now(),
            runtime_mode="CONTINUOUS",
            automatic_refresh="CONNECTED",
            dropped_obsolete_tasks=self.slot.dropped,
            consecutive_failures=self.consecutive_failures,
        )
        self.last_success_at = self.now()
        self.last_failure_at = None
        self.last_failure_reason = None
        self.consecutive_failures = 0
        self.half_open = False
        self._health("COLLECTING")

    def _record_failure(self, exc: Exception) -> float:
        self.consecutive_failures += 1
        self.last_failure_at = self.now()
        self.last_failure_reason = self._safe_reason(exc)
        exponent = min(self.consecutive_failures - 1, 6)
        delay = min(
            self.config.maximum_backoff_seconds,
            self.config.refresh_seconds * (2 ** exponent),
        )
        if self.consecutive_failures >= self.config.maximum_consecutive_failures:
            self.suspended_until_monotonic = (
                self.monotonic_clock() + self.config.failure_cooldown_seconds
            )
            self._health("PROVIDER_CIRCUIT_OPEN")
            return self.config.failure_cooldown_seconds
        self._health()
        return delay

    def _wait_with_heartbeat(self, seconds: float, *, lifecycle: str | None = None) -> None:
        deadline = self.monotonic_clock() + max(0.0, seconds)
        while not self.stop_event.is_set():
            remaining = deadline - self.monotonic_clock()
            if remaining <= 0:
                return
            self.stop_event.wait(min(self.config.refresh_seconds, remaining))
            if not self.stop_event.is_set():
                self._health(lifecycle)

    def run_forever(self) -> None:
        if not self.config.enabled:
            raise ValueError("MARKET_TREND_RESEARCH_RUNTIME_DISABLED")
        try:
            while not self.stop_event.is_set():
                cycle_started = self.monotonic_clock()
                delay = self.config.refresh_seconds
                lifecycle: str | None = None
                try:
                    self.run_cycle()
                    lifecycle = self._session_lifecycle(self.now())
                    if self.suspended_until_monotonic is not None:
                        lifecycle = "PROVIDER_CIRCUIT_OPEN"
                except Exception as exc:
                    delay = self._record_failure(exc)
                    lifecycle = (
                        "PROVIDER_CIRCUIT_OPEN"
                        if self.suspended_until_monotonic is not None
                        else self.last_failure_reason
                    )
                elapsed = self.monotonic_clock() - cycle_started
                self._wait_with_heartbeat(
                    max(0.0, delay - elapsed),
                    lifecycle=lifecycle,
                )
        finally:
            self._health("STOPPED")
