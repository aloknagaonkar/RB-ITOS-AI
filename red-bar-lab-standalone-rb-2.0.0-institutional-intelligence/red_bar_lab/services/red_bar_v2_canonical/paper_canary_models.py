from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .paper_execution_models import PaperExecutionResult


class PaperCanaryWorkerStatus(str, Enum):
    DISABLED = "DISABLED"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    HEALTHY_IDLE = "HEALTHY_IDLE"
    PAPER_ACTION_COMPLETED = "PAPER_ACTION_COMPLETED"
    ENTRY_SUSPENDED = "ENTRY_SUSPENDED"
    RECOVERY_ONLY = "RECOVERY_ONLY"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    RECOVERY_PROBE = "RECOVERY_PROBE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"


class PaperCanaryCircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    RECOVERY_PROBE = "RECOVERY_PROBE"


class PaperCanaryCycleOutcome(str, Enum):
    DISABLED = "DISABLED"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    HEALTHY_IDLE = "HEALTHY_IDLE"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_REJECTED = "ACTION_REJECTED"
    ACTION_UNCERTAIN = "ACTION_UNCERTAIN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    ENTRY_SUSPENDED = "ENTRY_SUSPENDED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"


def _aware(name: str, value: datetime | None) -> None:
    if value is None:
        return
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _non_negative(name: str, value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _text(name: str, value: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class PaperCanaryRuntimeState:
    worker_status: PaperCanaryWorkerStatus
    circuit_state: PaperCanaryCircuitState
    entry_suspended: bool
    consecutive_failures: int
    healthy_probe_cycles: int
    last_cycle_started_at: datetime | None
    last_cycle_completed_at: datetime | None
    last_successful_cycle_at: datetime | None
    next_eligible_cycle_at: datetime | None
    latest_reason_code: str
    recovery_count: int
    candidate_count: int
    attempted_count: int
    accepted_count: int
    rejected_count: int
    uncertain_count: int
    daily_action_count: int
    latest_execution_id: str | None
    persistence_status: str
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if type(self.worker_status) is not PaperCanaryWorkerStatus:
            raise ValueError("worker_status must be PaperCanaryWorkerStatus")
        if type(self.circuit_state) is not PaperCanaryCircuitState:
            raise ValueError("circuit_state must be PaperCanaryCircuitState")
        if type(self.entry_suspended) is not bool:
            raise ValueError("entry_suspended must be bool")
        for name in (
            "consecutive_failures",
            "healthy_probe_cycles",
            "recovery_count",
            "candidate_count",
            "attempted_count",
            "accepted_count",
            "rejected_count",
            "uncertain_count",
            "daily_action_count",
        ):
            _non_negative(name, getattr(self, name))
        for name in (
            "last_cycle_started_at",
            "last_cycle_completed_at",
            "last_successful_cycle_at",
            "next_eligible_cycle_at",
        ):
            _aware(name, getattr(self, name))
        _text("latest_reason_code", self.latest_reason_code)
        _text("persistence_status", self.persistence_status)
        _text("schema_version", self.schema_version)
        if self.schema_version != "1.0":
            raise ValueError("unsupported runtime state schema")
        if self.latest_execution_id is not None:
            _text("latest_execution_id", self.latest_execution_id)
        if self.circuit_state is PaperCanaryCircuitState.OPEN and not self.entry_suspended:
            raise ValueError("open circuit requires entry_suspended")


@dataclass(frozen=True, slots=True)
class PaperCanaryCycleResult:
    outcome: PaperCanaryCycleOutcome
    reason_code: str
    state: PaperCanaryRuntimeState
    execution_results: tuple[PaperExecutionResult, ...]

    def __post_init__(self) -> None:
        if type(self.outcome) is not PaperCanaryCycleOutcome:
            raise ValueError("outcome must be PaperCanaryCycleOutcome")
        _text("reason_code", self.reason_code)
        if type(self.state) is not PaperCanaryRuntimeState:
            raise ValueError("state must be PaperCanaryRuntimeState")
        if type(self.execution_results) is not tuple or any(
            type(item) is not PaperExecutionResult for item in self.execution_results
        ):
            raise ValueError("execution_results must contain PaperExecutionResult values")


@dataclass(frozen=True, slots=True)
class PaperCanaryPrerequisites:
    shadow_enabled: bool
    reservation_enabled: bool
    paper_execution_enabled: bool
    paper_execution_mode: str
    worker_enabled: bool
    market_session_active: bool = True

    def __post_init__(self) -> None:
        for name in (
            "shadow_enabled",
            "reservation_enabled",
            "paper_execution_enabled",
            "worker_enabled",
            "market_session_active",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be bool")
        _text("paper_execution_mode", self.paper_execution_mode)

    @property
    def activation_valid(self) -> bool:
        return (
            self.shadow_enabled
            and self.reservation_enabled
            and self.paper_execution_enabled
            and self.paper_execution_mode == "PAPER_CANARY"
            and self.worker_enabled
        )


@dataclass(frozen=True, slots=True)
class PaperCanaryPolicy:
    poll_seconds: float
    max_actions_per_cycle: int
    max_actions_per_day: int
    max_bundle_age_seconds: float
    failure_threshold: int
    required_probe_cycles: int

    def __post_init__(self) -> None:
        if type(self.poll_seconds) not in (int, float) or not 2 <= float(self.poll_seconds) <= 60:
            raise ValueError("poll_seconds outside safe range")
        if type(self.max_actions_per_cycle) is not int or not 1 <= self.max_actions_per_cycle <= 2:
            raise ValueError("max_actions_per_cycle outside safe range")
        if type(self.max_actions_per_day) is not int or not 1 <= self.max_actions_per_day <= 50:
            raise ValueError("max_actions_per_day outside safe range")
        if type(self.max_bundle_age_seconds) not in (int, float) or not 15 <= float(self.max_bundle_age_seconds) <= 300:
            raise ValueError("max_bundle_age_seconds outside safe range")
        if type(self.failure_threshold) is not int or not 1 <= self.failure_threshold <= 10:
            raise ValueError("failure_threshold outside safe range")
        if type(self.required_probe_cycles) is not int or not 1 <= self.required_probe_cycles <= 5:
            raise ValueError("required_probe_cycles outside safe range")


def initial_runtime_state() -> PaperCanaryRuntimeState:
    return PaperCanaryRuntimeState(
        worker_status=PaperCanaryWorkerStatus.HEALTHY_IDLE,
        circuit_state=PaperCanaryCircuitState.CLOSED,
        entry_suspended=False,
        consecutive_failures=0,
        healthy_probe_cycles=0,
        last_cycle_started_at=None,
        last_cycle_completed_at=None,
        last_successful_cycle_at=None,
        next_eligible_cycle_at=None,
        latest_reason_code="INITIALIZED",
        recovery_count=0,
        candidate_count=0,
        attempted_count=0,
        accepted_count=0,
        rejected_count=0,
        uncertain_count=0,
        daily_action_count=0,
        latest_execution_id=None,
        persistence_status="STATE_INITIALIZED",
    )
