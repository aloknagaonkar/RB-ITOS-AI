"""Observation-only continuous-health confirmation for Midpoint exits.

The overlay never mutates the canonical lifecycle.  It consumes completed
one-minute health labels and existing candidate exit signals, and maintains
two counterfactual paths beside the unchanged current policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class HealthExitRecord:
    policy: str
    event: str
    timestamp: datetime
    reason: str
    directional_points: float
    health: str
    unhealthy_streak: int
    armed_reason: str | None


@dataclass
class _HealthPath:
    policy: str
    confirmations_required: int
    armed_reason: str | None = None
    armed_at: datetime | None = None
    unhealthy_streak: int = 0
    closed: bool = False
    exit_record: HealthExitRecord | None = None


@dataclass
class ContinuousHealthExitV1:
    """Two non-authoritative exit-confirmation paths for one trade."""

    immediate: _HealthPath = field(
        default_factory=lambda: _HealthPath("HEALTH_IMMEDIATE_CONFIRMATION", 1)
    )
    two_close: _HealthPath = field(
        default_factory=lambda: _HealthPath("HEALTH_TWO_CLOSE_CONFIRMATION", 2)
    )
    last_timestamp: datetime | None = None
    last_health: str = "UNAVAILABLE"
    last_points: float = 0.0

    @property
    def paths(self) -> tuple[_HealthPath, _HealthPath]:
        return self.immediate, self.two_close

    def observe_close(
        self,
        *,
        timestamp: datetime,
        directional_points: float,
        health: str,
    ) -> list[HealthExitRecord]:
        if self.last_timestamp is not None and timestamp <= self.last_timestamp:
            raise ValueError("continuous health requires strictly increasing minutes")
        if health not in {"HEALTHY", "UNHEALTHY", "UNAVAILABLE"}:
            raise ValueError(f"unsupported health label: {health}")
        self.last_timestamp = timestamp
        self.last_health = health
        self.last_points = directional_points
        records: list[HealthExitRecord] = []
        for path in self.paths:
            if path.closed or path.armed_reason is None:
                continue
            if health == "UNHEALTHY":
                path.unhealthy_streak += 1
            elif health == "HEALTHY":
                path.unhealthy_streak = 0
            # UNAVAILABLE does not manufacture or erase confirmation.
            if path.unhealthy_streak >= path.confirmations_required:
                records.append(self._close(path, timestamp, directional_points,
                                           health, path.policy))
        return records

    def arm_soft_exit(
        self,
        *,
        timestamp: datetime,
        reason: str,
        directional_points: float,
    ) -> list[HealthExitRecord]:
        """Arm each open path and apply the current completed-close health."""
        if self.last_timestamp != timestamp:
            raise ValueError("soft exit must use the already-observed current close")
        records: list[HealthExitRecord] = []
        for path in self.paths:
            if path.closed:
                continue
            if path.armed_reason is None:
                path.armed_reason = reason
                path.armed_at = timestamp
                # The current close counts once; observe_close ran before arming.
                path.unhealthy_streak = 1 if self.last_health == "UNHEALTHY" else 0
            if path.unhealthy_streak >= path.confirmations_required:
                records.append(self._close(
                    path, timestamp, directional_points, self.last_health, path.policy
                ))
        return records

    def structural_fallback(
        self,
        *,
        timestamp: datetime,
        directional_points: float,
        reason: str = "MIDPOINT_INVALIDATION",
    ) -> list[HealthExitRecord]:
        """Close still-open comparison paths at the canonical hard backstop."""
        records: list[HealthExitRecord] = []
        for path in self.paths:
            if not path.closed:
                records.append(self._close(
                    path, timestamp, directional_points, self.last_health,
                    f"STRUCTURAL_FALLBACK:{reason}",
                ))
        return records

    @staticmethod
    def _close(
        path: _HealthPath,
        timestamp: datetime,
        points: float,
        health: str,
        reason: str,
    ) -> HealthExitRecord:
        path.closed = True
        record = HealthExitRecord(
            policy=path.policy,
            event="EXIT_CANDIDATE",
            timestamp=timestamp,
            reason=reason,
            directional_points=points,
            health=health,
            unhealthy_streak=path.unhealthy_streak,
            armed_reason=path.armed_reason,
        )
        path.exit_record = record
        return record
