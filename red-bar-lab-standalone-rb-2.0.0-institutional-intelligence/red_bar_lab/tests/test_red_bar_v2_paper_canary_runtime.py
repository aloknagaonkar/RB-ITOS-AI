from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_models import (
    PaperCanaryCircuitState,
    PaperCanaryCycleOutcome,
    PaperCanaryPolicy,
    PaperCanaryPrerequisites,
    PaperCanaryWorkerStatus,
    initial_runtime_state,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_repository import (
    CanonicalPaperCandidate,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_runtime import (
    PaperCanaryRuntime,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_state_store import (
    AtomicJsonPaperCanaryStateStore,
    PaperCanaryStateCorruptionError,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_models import (
    PaperExecutionOutcome,
    PaperExecutionResult,
)

NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


class FixedClock:
    def now(self):
        return NOW


class RecordingStateStore:
    def __init__(self, calls, state=None):
        self.calls = calls
        self.state = state

    def load(self):
        self.calls.append("load_state")
        return self.state

    def save(self, state):
        self.calls.append("save_state")
        self.state = state


class RecordingRecovery:
    def __init__(self, calls, results=()):
        self.calls = calls
        self.results = results

    def recover(self, **kwargs):
        self.calls.append("recover")
        return self.results


class RecordingExecutionRepository:
    def __init__(self, calls, count=0):
        self.calls = calls
        self.count = count

    def count_trading_date_executions(self, **kwargs):
        self.calls.append("daily_count")
        return self.count


class RecordingCandidates:
    def __init__(self, calls, candidates=()):
        self.calls = calls
        self.candidates = candidates

    def list_candidates(self, **kwargs):
        self.calls.append("list_candidates")
        return self.candidates


class RecordingExecution:
    def __init__(self, calls, result=None):
        self.calls = calls
        self.result = result or PaperExecutionResult(
            PaperExecutionOutcome.SUBMISSION_REJECTED,
            "NORMAL_REJECTION",
        )

    def execute(self, **kwargs):
        self.calls.append("execute")
        return self.result


def prerequisites(worker=True):
    return PaperCanaryPrerequisites(
        shadow_enabled=True,
        reservation_enabled=True,
        paper_execution_enabled=True,
        paper_execution_mode="PAPER_CANARY",
        worker_enabled=worker,
        market_session_active=True,
    )


def policy():
    return PaperCanaryPolicy(5.0, 1, 10, 120.0, 3, 1)


def candidate():
    return CanonicalPaperCandidate(
        bundle_id="B1",
        idempotency_key="I1",
        event_timestamp=NOW,
        created_at=NOW,
        trading_date=date(2026, 8, 23),
        spot_price=25000.0,
    )


def test_configuration_defaults_are_disabled(monkeypatch):
    monkeypatch.delenv("RED_BAR_V2_PAPER_CANARY_WORKER_ENABLED", raising=False)
    settings = RedBarSettings.from_env()
    assert settings.red_bar_v2_paper_canary_worker_enabled is False
    assert settings.red_bar_v2_canonical_paper_execution_mode == "OBSERVE_ONLY"


def test_atomic_state_round_trip_and_digest_validation(tmp_path):
    path = tmp_path / "state.json"
    store = AtomicJsonPaperCanaryStateStore(path)
    state = replace(
        initial_runtime_state(),
        circuit_state=PaperCanaryCircuitState.OPEN,
        worker_status=PaperCanaryWorkerStatus.CIRCUIT_OPEN,
        entry_suspended=True,
        latest_reason_code="TEST_OPEN",
    )
    store.save(state)
    assert store.load() == state
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("TEST_OPEN", "TAMPERED"), encoding="utf-8")
    with pytest.raises(PaperCanaryStateCorruptionError):
        store.load()


def test_cycle_order_is_recovery_first_and_bounded():
    calls = []
    runtime = PaperCanaryRuntime(
        state_store=RecordingStateStore(calls),
        candidate_repository=RecordingCandidates(calls, (candidate(),)),
        recovery_service=RecordingRecovery(calls),
        execution_service=RecordingExecution(calls),
        execution_repository=RecordingExecutionRepository(calls),
        clock=FixedClock(),
        prerequisites=prerequisites(),
        policy=policy(),
    )
    result = runtime.run_cycle()
    assert result.outcome is PaperCanaryCycleOutcome.ACTION_REJECTED
    assert calls == [
        "load_state",
        "recover",
        "daily_count",
        "list_candidates",
        "execute",
        "save_state",
    ]


def test_daily_limit_prevents_candidate_scan_and_execution():
    calls = []
    runtime = PaperCanaryRuntime(
        state_store=RecordingStateStore(calls),
        candidate_repository=RecordingCandidates(calls, (candidate(),)),
        recovery_service=RecordingRecovery(calls),
        execution_service=RecordingExecution(calls),
        execution_repository=RecordingExecutionRepository(calls, count=10),
        clock=FixedClock(),
        prerequisites=prerequisites(),
        policy=policy(),
    )
    result = runtime.run_cycle()
    assert result.outcome is PaperCanaryCycleOutcome.ENTRY_SUSPENDED
    assert calls == ["load_state", "recover", "daily_count", "save_state"]
