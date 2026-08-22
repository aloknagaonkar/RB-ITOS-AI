from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CircuitDecision:
    entry_suspended: bool
    state: str
    consecutive_failures: int
    delay_seconds: int
    reason: str


class PaperMonitorCircuitBreaker:
    """Fail closed for new entries while preserving position-management cycles.

    State is persisted when a path is configured so a process restart does not
    immediately forget an active market-data failure. Corrupt state is ignored
    safely and replaced on the next transition.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        base_delay_seconds: int = 2,
        maximum_delay_seconds: int = 60,
        state_path: str | Path | None = None,
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.base_delay_seconds = max(1, int(base_delay_seconds))
        self.maximum_delay_seconds = max(
            self.base_delay_seconds,
            int(maximum_delay_seconds),
        )
        configured = state_path or os.getenv("RED_BAR_PAPER_MONITOR_CIRCUIT_STATE")
        self.state_path = Path(configured) if configured else None
        self.consecutive_failures = 0
        self._open = False
        self._reason = ""
        self._load_state()

    @property
    def entry_suspended(self) -> bool:
        return self._open

    def begin_cycle(self) -> CircuitDecision:
        return self._decision(
            reason=self._reason if self._open else "ENTRY_FEED_HEALTHY"
        )

    def record_failure(self, reason: object) -> CircuitDecision:
        self.consecutive_failures += 1
        self._reason = str(reason or "PAPER_MONITOR_CYCLE_FAILED")[:500]
        if self.consecutive_failures >= self.failure_threshold:
            self._open = True
        decision = self._decision(reason=self._reason)
        self._persist_state(decision)
        return decision

    def record_success(self) -> tuple[CircuitDecision, bool]:
        recovered = self._open
        self.consecutive_failures = 0
        self._open = False
        self._reason = "ENTRY_FEED_RECOVERED" if recovered else "ENTRY_FEED_HEALTHY"
        decision = self._decision(reason=self._reason)
        self._persist_state(decision)
        return decision, recovered

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

    def _load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        self.consecutive_failures = max(
            0,
            int(payload.get("consecutive_failures") or 0),
        )
        self._open = bool(payload.get("entry_suspended"))
        self._reason = str(payload.get("reason") or "")[:500]

    def _persist_state(self, decision: CircuitDecision) -> None:
        if self.state_path is None:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(asdict(decision), sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(self.state_path)
        except OSError:
            # Persistence must never prevent position-management work.
            return


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
