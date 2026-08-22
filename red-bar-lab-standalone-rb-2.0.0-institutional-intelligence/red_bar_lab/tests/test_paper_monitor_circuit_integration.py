from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / "execution" / "paper_monitor.py"


def test_monitor_wires_entry_circuit_without_disabling_exits():
    source = MONITOR.read_text(encoding="utf-8")

    assert "PaperMonitorCircuitBreaker(" in source
    assert "critical_market_data_failure(" in source
    assert "execute_confirmed_reversal_exits(" in source
    assert "POSITION_MANAGEMENT_ONLY" in source
    assert "ENTRY_SUSPENDED" in source


def test_open_circuit_skips_new_entry_automation():
    source = MONITOR.read_text(encoding="utf-8")

    assert "elif cycle_gate.entry_suspended:" in source
    assert "ENTRY_RECOVERY_CONFIRMED_RESUME_NEXT_CYCLE" in source
    assert "report = automation.run_cycle(" in source
    assert source.index("elif cycle_gate.entry_suspended:") < source.index(
        "report = automation.run_cycle("
    )


def test_monitor_uses_circuit_backoff_and_recovery_event():
    source = MONITOR.read_text(encoding="utf-8")

    assert "next_delay = circuit_decision.delay_seconds" in source
    assert "PAPER_MONITOR_ENTRY_FEED_RECOVERED" in source
    assert "time.sleep(max(2, next_delay))" in source


def test_non_idempotent_broker_execution_remains_disabled():
    source = MONITOR.read_text(encoding="utf-8")

    assert "This process never sends broker orders." in source
    assert "broker execution disabled" in source
