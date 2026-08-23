from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Protocol

from .paper_canary_models import (
    PaperCanaryCircuitState,
    PaperCanaryCycleOutcome,
    PaperCanaryCycleResult,
    PaperCanaryPolicy,
    PaperCanaryPrerequisites,
    PaperCanaryRuntimeState,
    PaperCanaryWorkerStatus,
    initial_runtime_state,
)
from .paper_canary_repository import (
    CanonicalPaperCandidateRepository,
    PaperCanaryCandidateCorruptionError,
    PaperCanaryCandidateStorageError,
)
from .paper_canary_state_store import (
    PaperCanaryStateCorruptionError,
    PaperCanaryStateStorageError,
    PaperCanaryStateStore,
)
from .paper_execution_models import PaperExecutionOutcome, PaperExecutionResult
from .paper_execution_repository import (
    PaperExecutionCorruptionError,
    PaperExecutionStorageError,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().astimezone()


_FAILURE_OUTCOMES = {
    PaperExecutionOutcome.BUNDLE_CORRUPT,
    PaperExecutionOutcome.RESERVATION_CORRUPT,
    PaperExecutionOutcome.STORAGE_UNAVAILABLE,
    PaperExecutionOutcome.RECOVERY_REQUIRED,
    PaperExecutionOutcome.SUBMISSION_UNCERTAIN,
}


class PaperCanaryRuntime:
    def __init__(
        self,
        *,
        state_store: PaperCanaryStateStore,
        candidate_repository: CanonicalPaperCandidateRepository,
        recovery_service,
        execution_service,
        execution_repository,
        clock: Clock,
        prerequisites: PaperCanaryPrerequisites,
        policy: PaperCanaryPolicy,
    ) -> None:
        self.state_store = state_store
        self.candidate_repository = candidate_repository
        self.recovery_service = recovery_service
        self.execution_service = execution_service
        self.execution_repository = execution_repository
        self.clock = clock
        self.prerequisites = prerequisites
        self.policy = policy
        self._cycle_running = False
        self._persistence_failed = False

    @staticmethod
    def _result(
        outcome: PaperCanaryCycleOutcome,
        reason: str,
        state: PaperCanaryRuntimeState,
        executions: tuple[PaperExecutionResult, ...] = (),
    ) -> PaperCanaryCycleResult:
        return PaperCanaryCycleResult(outcome, reason, state, executions)

    def _safe_save(self, state: PaperCanaryRuntimeState) -> PaperCanaryRuntimeState:
        try:
            persisted = replace(state, persistence_status="STATE_PERSISTED")
            self.state_store.save(persisted)
            self._persistence_failed = False
            return persisted
        except (PaperCanaryStateStorageError, OSError):
            self._persistence_failed = True
            raise

    def _failure_state(
        self,
        state: PaperCanaryRuntimeState,
        *,
        now: datetime,
        reason: str,
        status: PaperCanaryWorkerStatus = PaperCanaryWorkerStatus.ENTRY_SUSPENDED,
    ) -> PaperCanaryRuntimeState:
        failures = state.consecutive_failures + 1
        circuit = (
            PaperCanaryCircuitState.OPEN
            if failures >= self.policy.failure_threshold
            else state.circuit_state
        )
        return replace(
            state,
            worker_status=(
                PaperCanaryWorkerStatus.CIRCUIT_OPEN
                if circuit is PaperCanaryCircuitState.OPEN
                else status
            ),
            circuit_state=circuit,
            entry_suspended=True,
            consecutive_failures=failures,
            healthy_probe_cycles=0,
            last_cycle_completed_at=now,
            next_eligible_cycle_at=now + timedelta(seconds=self.policy.poll_seconds),
            latest_reason_code=reason,
            persistence_status="STATE_PENDING",
        )

    def _load_state(self, now: datetime) -> PaperCanaryRuntimeState | PaperCanaryCycleResult:
        if self._persistence_failed:
            state = replace(
                initial_runtime_state(),
                worker_status=PaperCanaryWorkerStatus.STORAGE_UNAVAILABLE,
                circuit_state=PaperCanaryCircuitState.OPEN,
                entry_suspended=True,
                last_cycle_started_at=now,
                last_cycle_completed_at=now,
                latest_reason_code="RUNTIME_STATE_PERSISTENCE_UNPROVEN",
                persistence_status="STATE_UNAVAILABLE",
            )
            return self._result(
                PaperCanaryCycleOutcome.STORAGE_UNAVAILABLE,
                state.latest_reason_code,
                state,
            )
        try:
            state = self.state_store.load() or initial_runtime_state()
            return replace(state, last_cycle_started_at=now)
        except PaperCanaryStateCorruptionError:
            state = replace(
                initial_runtime_state(),
                worker_status=PaperCanaryWorkerStatus.ENTRY_SUSPENDED,
                circuit_state=PaperCanaryCircuitState.OPEN,
                entry_suspended=True,
                last_cycle_started_at=now,
                last_cycle_completed_at=now,
                latest_reason_code="RUNTIME_STATE_CORRUPT",
                persistence_status="STATE_CORRUPT",
            )
            return self._result(
                PaperCanaryCycleOutcome.ENTRY_SUSPENDED,
                "RUNTIME_STATE_CORRUPT",
                state,
            )
        except PaperCanaryStateStorageError:
            state = replace(
                initial_runtime_state(),
                worker_status=PaperCanaryWorkerStatus.STORAGE_UNAVAILABLE,
                circuit_state=PaperCanaryCircuitState.OPEN,
                entry_suspended=True,
                last_cycle_started_at=now,
                last_cycle_completed_at=now,
                latest_reason_code="RUNTIME_STATE_UNAVAILABLE",
                persistence_status="STATE_UNAVAILABLE",
            )
            return self._result(
                PaperCanaryCycleOutcome.STORAGE_UNAVAILABLE,
                "RUNTIME_STATE_UNAVAILABLE",
                state,
            )

    def run_cycle(self) -> PaperCanaryCycleResult:
        if self._cycle_running:
            state = initial_runtime_state()
            return self._result(
                PaperCanaryCycleOutcome.ENTRY_SUSPENDED,
                "CYCLE_ALREADY_RUNNING",
                replace(
                    state,
                    worker_status=PaperCanaryWorkerStatus.ENTRY_SUSPENDED,
                    entry_suspended=True,
                ),
            )
        self._cycle_running = True
        try:
            now = self.clock.now()
            if now.tzinfo is None or now.utcoffset() is None:
                state = replace(
                    initial_runtime_state(),
                    worker_status=PaperCanaryWorkerStatus.CONFIGURATION_INVALID,
                    entry_suspended=True,
                    latest_reason_code="NAIVE_RUNTIME_CLOCK",
                )
                return self._result(
                    PaperCanaryCycleOutcome.CONFIGURATION_INVALID,
                    "NAIVE_RUNTIME_CLOCK",
                    state,
                )
            if not self.prerequisites.worker_enabled:
                state = replace(
                    initial_runtime_state(),
                    worker_status=PaperCanaryWorkerStatus.DISABLED,
                    entry_suspended=True,
                    latest_reason_code="WORKER_DISABLED",
                )
                return self._result(PaperCanaryCycleOutcome.DISABLED, "WORKER_DISABLED", state)
            if self.prerequisites.paper_execution_mode == "OBSERVE_ONLY":
                state = replace(
                    initial_runtime_state(),
                    worker_status=PaperCanaryWorkerStatus.OBSERVE_ONLY,
                    entry_suspended=True,
                    latest_reason_code="OBSERVE_ONLY",
                )
                return self._result(PaperCanaryCycleOutcome.OBSERVE_ONLY, "OBSERVE_ONLY", state)
            if not self.prerequisites.activation_valid:
                state = replace(
                    initial_runtime_state(),
                    worker_status=PaperCanaryWorkerStatus.CONFIGURATION_INVALID,
                    entry_suspended=True,
                    latest_reason_code="ACTIVATION_PREREQUISITES_NOT_MET",
                )
                return self._result(
                    PaperCanaryCycleOutcome.CONFIGURATION_INVALID,
                    "ACTIVATION_PREREQUISITES_NOT_MET",
                    state,
                )

            loaded = self._load_state(now)
            if type(loaded) is PaperCanaryCycleResult:
                return loaded
            state = loaded

            try:
                recovery_results = tuple(
                    self.recovery_service.recover(observed_at=now, limit=100)
                )
            except Exception:
                failed = self._failure_state(
                    state,
                    now=now,
                    reason="RECOVERY_INFRASTRUCTURE_FAILURE",
                    status=PaperCanaryWorkerStatus.RECOVERY_ONLY,
                )
                try:
                    failed = self._safe_save(failed)
                except PaperCanaryStateStorageError:
                    pass
                return self._result(
                    PaperCanaryCycleOutcome.RECOVERY_REQUIRED,
                    "RECOVERY_INFRASTRUCTURE_FAILURE",
                    failed,
                )

            recovery_unhealthy = any(
                item.outcome in {
                    PaperExecutionOutcome.RECOVERY_REQUIRED,
                    PaperExecutionOutcome.SUBMISSION_UNCERTAIN,
                    PaperExecutionOutcome.STORAGE_UNAVAILABLE,
                    PaperExecutionOutcome.RESERVATION_CORRUPT,
                }
                for item in recovery_results
            )
            state = replace(state, recovery_count=len(recovery_results))

            if state.circuit_state is PaperCanaryCircuitState.OPEN:
                probes = state.healthy_probe_cycles + (0 if recovery_unhealthy else 1)
                if not recovery_unhealthy and probes >= self.policy.required_probe_cycles:
                    probe = replace(
                        state,
                        worker_status=PaperCanaryWorkerStatus.RECOVERY_PROBE,
                        circuit_state=PaperCanaryCircuitState.CLOSED,
                        entry_suspended=True,
                        consecutive_failures=0,
                        healthy_probe_cycles=probes,
                        last_cycle_completed_at=now,
                        last_successful_cycle_at=now,
                        next_eligible_cycle_at=now + timedelta(seconds=self.policy.poll_seconds),
                        latest_reason_code="RECOVERY_PROBE_COMPLETED",
                    )
                else:
                    probe = replace(
                        state,
                        worker_status=PaperCanaryWorkerStatus.CIRCUIT_OPEN,
                        entry_suspended=True,
                        healthy_probe_cycles=probes,
                        last_cycle_completed_at=now,
                        next_eligible_cycle_at=now + timedelta(seconds=self.policy.poll_seconds),
                        latest_reason_code=(
                            "RECOVERY_PROBE_UNHEALTHY"
                            if recovery_unhealthy
                            else "RECOVERY_PROBE_HEALTHY"
                        ),
                    )
                try:
                    probe = self._safe_save(probe)
                except PaperCanaryStateStorageError:
                    return self._result(
                        PaperCanaryCycleOutcome.STORAGE_UNAVAILABLE,
                        "RUNTIME_STATE_SAVE_FAILED",
                        replace(probe, persistence_status="STATE_UNAVAILABLE"),
                        recovery_results,
                    )
                return self._result(
                    PaperCanaryCycleOutcome.RECOVERY_REQUIRED,
                    probe.latest_reason_code,
                    probe,
                    recovery_results,
                )

            if recovery_unhealthy:
                failed = self._failure_state(
                    state,
                    now=now,
                    reason="RECOVERY_UNRESOLVED",
                    status=PaperCanaryWorkerStatus.RECOVERY_ONLY,
                )
                try:
                    failed = self._safe_save(failed)
                except PaperCanaryStateStorageError:
                    return self._result(
                        PaperCanaryCycleOutcome.STORAGE_UNAVAILABLE,
                        "RUNTIME_STATE_SAVE_FAILED",
                        replace(failed, persistence_status="STATE_UNAVAILABLE"),
                        recovery_results,
                    )
                return self._result(
                    PaperCanaryCycleOutcome.RECOVERY_REQUIRED,
                    "RECOVERY_UNRESOLVED",
                    failed,
                    recovery_results,
                )

            try:
                daily_count = self.execution_repository.count_trading_date_executions(
                    trading_date=now.date()
                )
            except (PaperExecutionStorageError, PaperExecutionCorruptionError):
                failed = self._failure_state(
                    state,
                    now=now,
                    reason="DAILY_COUNT_UNAVAILABLE",
                    status=PaperCanaryWorkerStatus.STORAGE_UNAVAILABLE,
                )
                try:
                    failed = self._safe_save(failed)
                except PaperCanaryStateStorageError:
                    pass
                return self._result(
                    PaperCanaryCycleOutcome.STORAGE_UNAVAILABLE,
                    "DAILY_COUNT_UNAVAILABLE",
                    failed,
                    recovery_results,
                )

            state = replace(state, daily_action_count=daily_count)
            if daily_count >= self.policy.max_actions_per_day:
                suspended = replace(
                    state,
                    worker_status=PaperCanaryWorkerStatus.ENTRY_SUSPENDED,
                    entry_suspended=True,
                    consecutive_failures=0,
                    last_cycle_completed_at=now,
                    last_successful_cycle_at=now,
                    next_eligible_cycle_at=now + timedelta(seconds=self.policy.poll_seconds),
                    latest_reason_code="DAILY_ACTION_LIMIT_REACHED",
                )
                try:
                    suspended = self._safe_save(suspended)
                except PaperCanaryStateStorageError:
                    return self._result(
                        PaperCanaryCycleOutcome.STORAGE_UNAVAILABLE,
                        "RUNTIME_STATE_SAVE_FAILED",
                        replace(suspended, persistence_status="STATE_UNAVAILABLE"),
                        recovery_results,
                    )
                return self._result(
                    PaperCanaryCycleOutcome.ENTRY_SUSPENDED,
                    "DAILY_ACTION_LIMIT_REACHED",
                    suspended,
                    recovery_results,
                )

            try:
                candidates = self.candidate_repository.list_candidates(
                    evaluated_at=now,
                    maximum_age_seconds=self.policy.max_bundle_age_seconds,
                    limit=self.policy.max_actions_per_cycle,
                )
            except PaperCanaryCandidateCorruptionError:
                failed = self._failure_state(
                    state,
                    now=now,
                    reason="CANONICAL_CANDIDATE_CORRUPT",
                )
                try:
                    failed = self._safe_save(failed)
                except PaperCanaryStateStorageError:
                    pass
                return self._result(
                    PaperCanaryCycleOutcome.ENTRY_SUSPENDED,
                    "CANONICAL_CANDIDATE_CORRUPT",
                    failed,
                    recovery_results,
                )
            except PaperCanaryCandidateStorageError:
                failed = self._failure_state(
                    state,
                    now=now,
                    reason="CANDIDATE_STORAGE_UNAVAILABLE",
                    status=PaperCanaryWorkerStatus.STORAGE_UNAVAILABLE,
                )
                try:
                    failed = self._safe_save(failed)
                except PaperCanaryStateStorageError:
                    pass
                return self._result(
                    PaperCanaryCycleOutcome.STORAGE_UNAVAILABLE,
                    "CANDIDATE_STORAGE_UNAVAILABLE",
                    failed,
                    recovery_results,
                )

            if not candidates:
                idle = replace(
                    state,
                    worker_status=PaperCanaryWorkerStatus.HEALTHY_IDLE,
                    entry_suspended=False,
                    consecutive_failures=0,
                    healthy_probe_cycles=0,
                    last_cycle_completed_at=now,
                    last_successful_cycle_at=now,
                    next_eligible_cycle_at=now + timedelta(seconds=self.policy.poll_seconds),
                    latest_reason_code="NO_ELIGIBLE_CANDIDATE",
                    candidate_count=0,
                    attempted_count=0,
                    accepted_count=0,
                    rejected_count=0,
                    uncertain_count=0,
                )
                try:
                    idle = self._safe_save(idle)
                except PaperCanaryStateStorageError:
                    return self._result(
                        PaperCanaryCycleOutcome.STORAGE_UNAVAILABLE,
                        "RUNTIME_STATE_SAVE_FAILED",
                        replace(idle, persistence_status="STATE_UNAVAILABLE"),
                        recovery_results,
                    )
                return self._result(
                    PaperCanaryCycleOutcome.HEALTHY_IDLE,
                    "NO_ELIGIBLE_CANDIDATE",
                    idle,
                    recovery_results,
                )

            execution_results: list[PaperExecutionResult] = []
            accepted = rejected = uncertain = 0
            latest_execution_id = None
            failure_seen = False
            for candidate in candidates[: self.policy.max_actions_per_cycle]:
                result = self.execution_service.execute(
                    bundle_id=candidate.bundle_id,
                    spot_price=candidate.spot_price,
                    requested_at=now,
                    quantity_lots=1,
                )
                execution_results.append(result)
                if result.command is not None:
                    latest_execution_id = result.command.execution_id
                if result.outcome is PaperExecutionOutcome.SUBMISSION_ACCEPTED:
                    accepted += 1
                elif result.outcome is PaperExecutionOutcome.SUBMISSION_REJECTED:
                    rejected += 1
                elif result.outcome is PaperExecutionOutcome.SUBMISSION_UNCERTAIN:
                    uncertain += 1
                    failure_seen = True
                elif result.outcome in _FAILURE_OUTCOMES:
                    failure_seen = True
                if failure_seen:
                    break

            if failure_seen:
                final = self._failure_state(
                    state,
                    now=now,
                    reason="PAPER_ACTION_REQUIRES_RECOVERY",
                )
                cycle_outcome = (
                    PaperCanaryCycleOutcome.ACTION_UNCERTAIN
                    if uncertain
                    else PaperCanaryCycleOutcome.RECOVERY_REQUIRED
                )
            else:
                final = replace(
                    state,
                    worker_status=PaperCanaryWorkerStatus.PAPER_ACTION_COMPLETED,
                    entry_suspended=False,
                    consecutive_failures=0,
                    healthy_probe_cycles=0,
                    last_cycle_completed_at=now,
                    last_successful_cycle_at=now,
                    next_eligible_cycle_at=now + timedelta(seconds=self.policy.poll_seconds),
                    latest_reason_code="PAPER_ACTION_COMPLETED",
                )
                cycle_outcome = (
                    PaperCanaryCycleOutcome.ACTION_COMPLETED
                    if accepted
                    else PaperCanaryCycleOutcome.ACTION_REJECTED
                )
            final = replace(
                final,
                candidate_count=len(candidates),
                attempted_count=len(execution_results),
                accepted_count=accepted,
                rejected_count=rejected,
                uncertain_count=uncertain,
                daily_action_count=daily_count + len(execution_results),
                latest_execution_id=latest_execution_id,
            )
            try:
                final = self._safe_save(final)
            except PaperCanaryStateStorageError:
                return self._result(
                    PaperCanaryCycleOutcome.STORAGE_UNAVAILABLE,
                    "RUNTIME_STATE_SAVE_FAILED",
                    replace(
                        final,
                        worker_status=PaperCanaryWorkerStatus.STORAGE_UNAVAILABLE,
                        entry_suspended=True,
                        persistence_status="STATE_UNAVAILABLE",
                    ),
                    tuple(execution_results),
                )
            return self._result(
                cycle_outcome,
                final.latest_reason_code,
                final,
                tuple(execution_results),
            )
        finally:
            self._cycle_running = False
