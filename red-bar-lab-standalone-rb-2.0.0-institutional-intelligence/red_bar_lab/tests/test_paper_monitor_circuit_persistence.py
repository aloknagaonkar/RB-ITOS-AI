from pathlib import Path

from red_bar_lab.execution.paper_monitor_circuit import PaperMonitorCircuitBreaker


def test_open_circuit_survives_restart(tmp_path: Path):
    state_path = tmp_path / "paper-monitor-circuit.json"
    circuit = PaperMonitorCircuitBreaker(
        failure_threshold=2,
        base_delay_seconds=2,
        maximum_delay_seconds=30,
        state_path=state_path,
    )

    circuit.record_failure("UNDERLYING_FEED_STALE")
    opened = circuit.record_failure("UNDERLYING_FEED_STALE")

    assert opened.entry_suspended is True
    restored = PaperMonitorCircuitBreaker(
        failure_threshold=2,
        base_delay_seconds=2,
        maximum_delay_seconds=30,
        state_path=state_path,
    )
    decision = restored.begin_cycle()
    assert decision.entry_suspended is True
    assert decision.consecutive_failures == 2
    assert decision.reason == "UNDERLYING_FEED_STALE"


def test_success_closes_and_persists_recovery(tmp_path: Path):
    state_path = tmp_path / "paper-monitor-circuit.json"
    circuit = PaperMonitorCircuitBreaker(
        failure_threshold=1,
        state_path=state_path,
    )
    circuit.record_failure("FUTURES_FEED_ERROR")

    decision, recovered = circuit.record_success()

    assert recovered is True
    assert decision.entry_suspended is False
    restored = PaperMonitorCircuitBreaker(state_path=state_path)
    assert restored.begin_cycle().entry_suspended is False
    assert restored.begin_cycle().reason == "ENTRY_FEED_HEALTHY"


def test_corrupt_state_is_ignored(tmp_path: Path):
    state_path = tmp_path / "paper-monitor-circuit.json"
    state_path.write_text("not-json", encoding="utf-8")

    circuit = PaperMonitorCircuitBreaker(state_path=state_path)

    assert circuit.begin_cycle().entry_suspended is False
    assert circuit.begin_cycle().consecutive_failures == 0


def test_real_monitor_runtime_uses_default_artifact_state(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("RED_BAR_ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.delenv("RED_BAR_PAPER_MONITOR_CIRCUIT_STATE", raising=False)

    circuit = PaperMonitorCircuitBreaker(failure_threshold=1)
    circuit.record_failure("UNDERLYING_FEED_STALE")

    expected = tmp_path / "paper_monitor_circuit.json"
    assert circuit.state_path == expected
    assert expected.exists()


def test_library_use_without_monitor_token_has_no_file_side_effect(monkeypatch):
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("RED_BAR_PAPER_MONITOR_CIRCUIT_STATE", raising=False)

    circuit = PaperMonitorCircuitBreaker()

    assert circuit.state_path is None
