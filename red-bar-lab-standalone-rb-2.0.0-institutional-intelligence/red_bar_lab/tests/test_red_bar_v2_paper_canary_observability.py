from __future__ import annotations

from dataclasses import replace

from red_bar_lab.services.red_bar_v2_canonical.paper_canary_models import (
    PaperCanaryCircuitState,
    PaperCanaryWorkerStatus,
    initial_runtime_state,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_observability import (
    PaperCanaryRuntimeObservabilityService,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_state_store import (
    AtomicJsonPaperCanaryStateStore,
)


def test_disabled_and_observe_only_are_explicit(tmp_path):
    service = PaperCanaryRuntimeObservabilityService(tmp_path / "state.json")
    assert service.load(worker_enabled=False, mode="PAPER_CANARY").status == "WORKER_DISABLED"
    assert service.load(worker_enabled=True, mode="OBSERVE_ONLY").status == "OBSERVE_ONLY"


def test_missing_and_corrupt_state_are_distinct(tmp_path):
    path = tmp_path / "state.json"
    service = PaperCanaryRuntimeObservabilityService(path)
    assert service.load(worker_enabled=True, mode="PAPER_CANARY").status == "RUNTIME_STATE_UNAVAILABLE"
    path.write_text("not-json", encoding="utf-8")
    assert service.load(worker_enabled=True, mode="PAPER_CANARY").status == "RUNTIME_STATE_CORRUPT"


def test_verified_open_circuit_renders_circuit_open(tmp_path):
    path = tmp_path / "state.json"
    state = replace(
        initial_runtime_state(),
        worker_status=PaperCanaryWorkerStatus.CIRCUIT_OPEN,
        circuit_state=PaperCanaryCircuitState.OPEN,
        entry_suspended=True,
        latest_reason_code="TEST_OPEN",
    )
    AtomicJsonPaperCanaryStateStore(path).save(state)
    observed = PaperCanaryRuntimeObservabilityService(path).load(
        worker_enabled=True,
        mode="PAPER_CANARY",
    )
    assert observed.status == "CIRCUIT_OPEN"
    assert observed.state == state


def test_runner_import_has_no_runtime_side_effect():
    from red_bar_lab.execution import run_red_bar_v2_paper_canary as runner

    assert callable(runner.build_runtime)
    assert callable(runner.main)
