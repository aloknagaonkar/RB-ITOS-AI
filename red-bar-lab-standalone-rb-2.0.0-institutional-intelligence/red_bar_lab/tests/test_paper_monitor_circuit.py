from red_bar_lab.execution.paper_monitor_circuit import (
    PaperMonitorCircuitBreaker,
    critical_market_data_failure,
)


def test_circuit_opens_after_consecutive_failures_and_backs_off():
    circuit = PaperMonitorCircuitBreaker(
        failure_threshold=3,
        base_delay_seconds=2,
        maximum_delay_seconds=30,
    )

    first = circuit.record_failure("temporary timeout")
    second = circuit.record_failure("temporary timeout")
    third = circuit.record_failure("temporary timeout")

    assert first.entry_suspended is False
    assert first.delay_seconds == 2
    assert second.entry_suspended is False
    assert second.delay_seconds == 4
    assert third.entry_suspended is True
    assert third.state == "OPEN"
    assert third.delay_seconds == 8


def test_recovery_cycle_keeps_entries_suspended_until_next_cycle():
    circuit = PaperMonitorCircuitBreaker(failure_threshold=1)
    circuit.record_failure("feed unavailable")

    suspended_at_cycle_start = circuit.begin_cycle()
    recovered, recovery_event = circuit.record_success()
    next_cycle = circuit.begin_cycle()

    assert suspended_at_cycle_start.entry_suspended is True
    assert recovery_event is True
    assert recovered.entry_suspended is False
    assert recovered.reason == "ENTRY_FEED_RECOVERED"
    assert next_cycle.entry_suspended is False


def test_backoff_is_bounded():
    circuit = PaperMonitorCircuitBreaker(
        failure_threshold=1,
        base_delay_seconds=5,
        maximum_delay_seconds=20,
    )
    for _ in range(10):
        decision = circuit.record_failure("failure")
    assert decision.delay_seconds == 20


def test_critical_market_data_failure_ignores_expected_closed_states():
    assert (
        critical_market_data_failure(
            underlying_status="MARKET_CLOSED",
            futures_status="MARKET_CLOSED",
            futures_applicable=True,
        )
        is None
    )


def test_critical_market_data_failure_blocks_unusable_feeds():
    assert critical_market_data_failure(
        underlying_status="STALE",
        futures_status="READY",
        futures_applicable=True,
    ) == "UNDERLYING_FEED_STALE"

    assert critical_market_data_failure(
        underlying_status="READY",
        futures_status="ERROR",
        futures_applicable=True,
    ) == "FUTURES_FEED_ERROR"

    assert critical_market_data_failure(
        underlying_status="READY",
        futures_status="ERROR",
        futures_applicable=False,
    ) is None
