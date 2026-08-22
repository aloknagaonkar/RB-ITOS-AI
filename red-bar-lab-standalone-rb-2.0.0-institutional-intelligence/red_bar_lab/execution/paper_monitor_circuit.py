from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CircuitDecision:
    entry_suspended: bool
    state: str
    consecutive_failures: int
    delay_seconds: int
    reason: str


class PaperMonitorCircuitBreaker:
    """Fail closed for new entries while preserving position-management cycles.

    The circuit opens after a bounded number of consecutive cycle failures.
    While open, callers continue market-data and position-management work but
    must skip new-entry automation. One completely successful suspended cycle
    records recovery; entries resume only on the following cycle.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        base_delay_seconds: int = 2,
        maximum_delay_seconds: int = 60,
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.base_delay_seconds = max(1, int(base_delay_seconds))
        self.maximum_delay_seconds = max(
            self.base_delay_seconds,
            int(maximum_delay_seconds),
        )
        self.consecutive_failures = 0
        self._open = False
        self._reason = ""

    @property
    def entry_suspended(self) -> bool:
        return self._open

    def begin_cycle(self) -> CircuitDecision:
        return self._decision(
            reason=(
                self._reason
                if self._open
                else "ENTRY_FEED_HEALTHY"
            )
        )

    def record_failure(self, reason: object) -> CircuitDecision:
        self.consecutive_failures += 1
        self._reason = str(reason or "PAPER_MONITOR_CYCLE_FAILED")[:500]
        if self.consecutive_failures >= self.failure_threshold:
            self._open = True
        return self._decision(reason=self._reason)

    def record_success(self) -> tuple[CircuitDecision, bool]:
        recovered = self._open
        self.consecutive_failures = 0
        self._open = False
        self._reason = "ENTRY_FEED_RECOVERED" if recovered else "ENTRY_FEED_HEALTHY"
        return self._decision(reason=self._reason), recovered

    def _delay_seconds(self) -> int:
        if self.consecutive_failures <= 0:
            return self.base_delay_seconds
        delay = self.base_delay_seconds * (2 ** (self.consecutive_failures - 1))
        return min(self.maximum_delay_seconds, delay)

    def _decision(self, *, reason: str) -> CircuitDecision:
        return CircuitDecision(
            entry_suspended=self._open,
            state="OPEN" if self._open else "CLOSED",
            consecutive_failures=self.consecutive_failures,
            delay_seconds=self._delay_seconds(),
            reason=reason,
        )


def critical_market_data_failure(
    *,
    underlying_status: object,
    futures_status: object,
    futures_applicable: bool,
) -> str | None:
    """Return a stable failure reason only for unusable entry-feed states."""

    underlying = str(underlying_status or "UNAVAILABLE").upper()
    if underlying in {
        "MISSING",
        "STALE",
        "INVALID_TIMESTAMP",
        "TIMESTAMP_MISMATCH",
        "ERROR",
        "UNAVAILABLE",
    }:
        return f"UNDERLYING_FEED_{underlying}"

    if futures_applicable:
        futures = str(futures_status or "UNAVAILABLE").upper()
        if futures in {"MISSING", "STALE", "ERROR", "UNAVAILABLE"}:
            return f"FUTURES_FEED_{futures}"
    return None


__all__ = [
    "CircuitDecision",
    "PaperMonitorCircuitBreaker",
    "critical_market_data_failure",
]
