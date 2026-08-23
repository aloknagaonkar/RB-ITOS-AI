from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from red_bar_lab.services.red_bar_v2_canonical.paper_canary_models import (
    PaperCanaryCircuitState,
    PaperCanaryCycleOutcome,
    PaperCanaryPolicy,
    PaperCanaryPrerequisites,
    PaperCanaryWorkerStatus,
    initial_runtime_state,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_runtime import PaperCanaryRuntime
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_models import (
    PaperExecutionOutcome,
    PaperExecutionResult,
)

NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


class Clock:
    def now(self):
        return NOW


class Store:
    def __init__(self, calls, state):
        self.calls = calls
        self.state = state

    def load(self):
        self.calls.append("load_state")
        return self.state

    def save(self, state):
        self.calls.append("save_state")
        self.state = state


class Recovery:
    def __init__(self, calls, results=()):
        self.calls = calls
        self.results = results

    def recover(self, **kwargs):
        self.calls.append("recover")
        return self.results


class NeverCandidates:
    def __init__(self, calls):
        self.calls = calls

    def list_candidates(self, **kwargs):
        self.calls.append("list_candidates")
        raise AssertionError("candidate scan must not occur")


class NeverExecutions:
    def __init__(self, calls):
        self.calls = calls

    def execute(self, **kwargs):
        self.calls.append("execute")
        raise AssertionError("execution must not occur")


class Daily:
    def __init__(self, calls):
        self.calls = calls

    def count_trading_date_executions(self, **kwargs):
        self.calls.append("daily_count")
        return 0


def prereq():
    return PaperCanaryPrerequisites(True, True, True, "PAPER_CANARY", True, True)


def policy():
    return PaperCanaryPolicy(5.0, 1, 10, 120.0, 2, 1)


def test_open_circuit_runs_recovery_only_and_closes_without_entry():
    calls = []
    open_state = replace(
        initial_runtime_state(),
        worker_status=PaperCanaryWorkerStatus.CIRCUIT_OPEN,
        circuit_state=PaperCanaryCircuitState.OPEN,
        entry_suspended=True,
        consecutive_failures=2,
    )
    store = Store(calls, open_state)
    runtime = PaperCanaryRuntime(
        state_store=store,
        candidate_repository=NeverCandidates(calls),
        recovery_service=Recovery(calls),
        execution_service=NeverExecutions(calls),
        execution_repository=Daily(calls),
        clock=Clock(),
        prerequisites=prereq(),
        policy=policy(),
    )
    result = runtime.run_cycle()
    assert result.outcome is PaperCanaryCycleOutcome.RECOVERY_REQUIRED
    assert result.state.circuit_state is PaperCanaryCircuitState.CLOSED
    assert result.state.entry_suspended is True
    assert calls == ["load_state", "recover", "save_state"]


def test_unresolved_recovery_blocks_all_new_entries():
    calls = []
    unresolved = PaperExecutionResult(
        PaperExecutionOutcome.RECOVERY_REQUIRED,
        "NO_PROVEN_PAPER_RESULT",
    )
    runtime = PaperCanaryRuntime(
        state_store=Store(calls, initial_runtime_state()),
        candidate_repository=NeverCandidates(calls),
        recovery_service=Recovery(calls, (unresolved,)),
        execution_service=NeverExecutions(calls),
        execution_repository=Daily(calls),
        clock=Clock(),
        prerequisites=prereq(),
        policy=policy(),
    )
    result = runtime.run_cycle()
    assert result.outcome is PaperCanaryCycleOutcome.RECOVERY_REQUIRED
    assert result.state.entry_suspended is True
    assert calls == ["load_state", "recover", "save_state"]


def test_disabled_worker_creates_no_runtime_mutation():
    calls = []
    runtime = PaperCanaryRuntime(
        state_store=Store(calls, initial_runtime_state()),
        candidate_repository=NeverCandidates(calls),
        recovery_service=Recovery(calls),
        execution_service=NeverExecutions(calls),
        execution_repository=Daily(calls),
        clock=Clock(),
        prerequisites=PaperCanaryPrerequisites(True, True, True, "PAPER_CANARY", False, True),
        policy=policy(),
    )
    result = runtime.run_cycle()
    assert result.outcome is PaperCanaryCycleOutcome.DISABLED
    assert calls == []
