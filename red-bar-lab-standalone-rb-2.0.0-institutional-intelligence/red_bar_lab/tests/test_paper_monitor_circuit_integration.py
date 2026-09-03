from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / "execution" / "paper_monitor.py"
POSITION_MONITOR = ROOT / "execution" / "position_monitor.py"
CHILD_PROCESS = ROOT / "platform" / "child_process.py"


def test_monitor_wires_entry_circuit_without_disabling_exits():
    """The circuit suspends entries only -- and exits live in another process.

    This used to be proved by finding an exit call in this file. Both of the
    exits it ran here are now deleted (the reference-boundary sweep and the RSI
    threshold), so the claim has to be made where it is actually true: exit
    authority is a separately supervised child process, which the entry circuit
    cannot suspend because it does not run there.
    """
    source = MONITOR.read_text(encoding="utf-8")

    assert "PaperMonitorCircuitBreaker(" in source
    assert "critical_market_data_failure(" in source
    assert "POSITION_MANAGEMENT_ONLY" in source
    assert "ENTRY_SUSPENDED" in source

    specs = CHILD_PROCESS.read_text(encoding="utf-8")
    assert 'module="red_bar_lab.execution.position_monitor"' in specs
    assert "automation.monitor_and_exit()" in POSITION_MONITOR.read_text(
        encoding="utf-8"
    )


def test_real_monitor_persists_circuit_state_under_artifacts_root():
    source = MONITOR.read_text(encoding="utf-8")

    assert 'state_path=settings.artifacts_root / "paper_monitor_circuit.json"' in source


def test_open_circuit_skips_signal_publication_and_new_entry_automation():
    source = MONITOR.read_text(encoding="utf-8")

    suspended_branch = source.index("if cycle_gate.entry_suspended:")
    publication = source.index("bridge = publish_v2_snapshot_to_paper_signals(")
    recovery_gate = source.index("elif cycle_gate.entry_suspended:")
    automation = source.index("report = automation.run_cycle(")

    assert "ENTRY_CIRCUIT_OPEN_SIGNAL_PUBLICATION_SKIPPED" in source
    assert suspended_branch < publication
    assert recovery_gate < automation
    assert "ENTRY_RECOVERY_CONFIRMED_RESUME_NEXT_CYCLE" in source


def test_monitor_uses_circuit_backoff_and_recovery_event():
    source = MONITOR.read_text(encoding="utf-8")

    assert "next_delay = circuit_decision.delay_seconds" in source
    assert "PAPER_MONITOR_ENTRY_FEED_RECOVERED" in source
    assert "time.sleep(max(2, next_delay))" in source


def test_non_idempotent_broker_execution_remains_disabled():
    source = MONITOR.read_text(encoding="utf-8")

    assert "This process never sends broker orders." in source
    assert "broker execution disabled" in source
