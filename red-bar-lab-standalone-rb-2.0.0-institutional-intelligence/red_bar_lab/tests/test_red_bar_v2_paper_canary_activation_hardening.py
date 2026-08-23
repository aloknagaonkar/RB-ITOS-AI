from dataclasses import replace
from datetime import datetime, timezone

import pytest

from red_bar_lab.config import RedBarSettings
from red_bar_lab.execution.run_red_bar_v2_paper_canary import (
    PaperCanaryProcessLock,
    PaperCanaryStartupAction,
    SessionAwarePaperCanaryRuntime,
    evaluate_paper_canary_startup,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_models import (
    PaperCanaryCircuitState,
    PaperCanaryPolicy,
    PaperCanaryPrerequisites,
    PaperCanaryWorkerStatus,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_state_store import (
    AtomicJsonPaperCanaryStateStore,
    PaperCanaryStateStorageError,
)


def _settings(**changes):
    return replace(RedBarSettings(), **changes)


def test_startup_policy_is_pure_and_exact():
    disabled = evaluate_paper_canary_startup(_settings())
    assert disabled.action is PaperCanaryStartupAction.DISABLED
    assert disabled.reason_code == "WORKER_DISABLED"
    assert disabled.runtime_construction_allowed is False

    observe = evaluate_paper_canary_startup(
        _settings(red_bar_v2_paper_canary_worker_enabled=True)
    )
    assert observe.action is PaperCanaryStartupAction.OBSERVE_ONLY
    assert observe.reason_code == "OBSERVE_ONLY"

    invalid = evaluate_paper_canary_startup(
        _settings(
            red_bar_v2_paper_canary_worker_enabled=True,
            red_bar_v2_canonical_paper_execution_mode="INVALID",
        )
    )
    assert invalid.action is PaperCanaryStartupAction.CONFIGURATION_INVALID
    assert invalid.reason_code == "INVALID_PAPER_EXECUTION_MODE"

    base = dict(
        red_bar_v2_paper_canary_worker_enabled=True,
        red_bar_v2_canonical_paper_execution_mode="PAPER_CANARY",
    )
    assert evaluate_paper_canary_startup(
        _settings(**base)
    ).reason_code == "CANONICAL_SHADOW_DISABLED"
    assert evaluate_paper_canary_startup(
        _settings(**base, red_bar_v2_canonical_shadow_enabled=True)
    ).reason_code == "CANONICAL_RESERVATION_DISABLED"
    assert evaluate_paper_canary_startup(
        _settings(
            **base,
            red_bar_v2_canonical_shadow_enabled=True,
            red_bar_v2_canonical_reservation_enabled=True,
        )
    ).reason_code == "CANONICAL_PAPER_EXECUTION_DISABLED"

    allowed = evaluate_paper_canary_startup(
        _settings(
            **base,
            red_bar_v2_canonical_shadow_enabled=True,
            red_bar_v2_canonical_reservation_enabled=True,
            red_bar_v2_canonical_paper_execution_enabled=True,
        )
    )
    assert allowed.action is PaperCanaryStartupAction.PAPER_CANARY
    assert allowed.runtime_construction_allowed is True


def test_os_lock_ignores_stale_metadata_and_excludes_active_owner(tmp_path):
    path = tmp_path / "canary.lock"
    path.write_text("pid=999999\n", encoding="ascii")
    first = PaperCanaryProcessLock(path)
    second = PaperCanaryProcessLock(path)
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    first.release()
    assert second.acquire() is True
    second.release()
    assert path.parent == tmp_path


class _Clock:
    def now(self):
        return datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


class _Unused:
    def __getattr__(self, name):
        raise AssertionError(f"unexpected call: {name}")


def _runtime(tmp_path, *, threshold=2):
    return SessionAwarePaperCanaryRuntime(
        state_store=AtomicJsonPaperCanaryStateStore(tmp_path / "state.json"),
        candidate_repository=_Unused(),
        recovery_service=_Unused(),
        execution_service=_Unused(),
        execution_repository=_Unused(),
        clock=_Clock(),
        prerequisites=PaperCanaryPrerequisites(
            shadow_enabled=True,
            reservation_enabled=True,
            paper_execution_enabled=True,
            paper_execution_mode="PAPER_CANARY",
            worker_enabled=True,
        ),
        policy=PaperCanaryPolicy(
            poll_seconds=5,
            max_actions_per_cycle=1,
            max_actions_per_day=10,
            max_bundle_age_seconds=120,
            failure_threshold=threshold,
            required_probe_cycles=1,
        ),
    )


def test_process_boundary_failure_is_durable_and_opens_circuit(tmp_path):
    runtime = _runtime(tmp_path, threshold=2)
    at = _Clock().now()
    first = runtime.record_process_boundary_failure(
        failed_at=at,
        reason_code="WORKER_CYCLE_FAILED",
    )
    assert first.worker_status is PaperCanaryWorkerStatus.ENTRY_SUSPENDED
    assert first.entry_suspended is True
    assert first.consecutive_failures == 1
    assert first.latest_reason_code == "WORKER_CYCLE_FAILED"

    second = runtime.record_process_boundary_failure(
        failed_at=at,
        reason_code="WORKER_CYCLE_FAILED",
    )
    assert second.worker_status is PaperCanaryWorkerStatus.CIRCUIT_OPEN
    assert second.circuit_state is PaperCanaryCircuitState.OPEN
    assert second.consecutive_failures == 2
    restored = runtime.state_store.load()
    assert restored == second


def test_process_boundary_failure_does_not_hide_state_storage_failure(tmp_path):
    runtime = _runtime(tmp_path)

    class _FailingStore:
        def load(self):
            return None

        def save(self, state):
            raise PaperCanaryStateStorageError("unavailable")

    runtime.state_store = _FailingStore()
    with pytest.raises(PaperCanaryStateStorageError):
        runtime.record_process_boundary_failure(
            failed_at=_Clock().now(),
            reason_code="WORKER_CYCLE_FAILED",
        )
