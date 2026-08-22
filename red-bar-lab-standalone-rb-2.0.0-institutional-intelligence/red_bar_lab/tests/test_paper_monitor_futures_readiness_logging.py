import inspect

from red_bar_lab.execution import paper_monitor


def test_paper_monitor_assesses_and_logs_unified_futures_readiness():
    source = inspect.getsource(paper_monitor.main)

    assert "assess_nifty_futures_readiness(" in source
    assert "contract=futures_result" in source
    assert "market=futures_market_result" in source
    assert "positioning=futures_positioning_result" in source
    assert 'applicable=args.underlying == "NIFTY 50"' in source
    assert "futures_readiness_log_values(" in source

    # The circuit-breaker refactor logs the complete readiness payload as the
    # stable tuple returned by futures_readiness_log_values(), rather than
    # duplicating every tuple field in the monitor's format string.
    assert "futures_readiness_values = futures_readiness_log_values(" in source
    assert "futures_readiness=%s" in source
    assert "futures_readiness_values," in source


def test_unified_futures_readiness_remains_observational():
    source = inspect.getsource(paper_monitor.main)

    readiness_position = source.index("assess_nifty_futures_readiness(")
    execution_position = source.index("report = automation.run_cycle(")

    assert readiness_position < execution_position
    execution_call = source[execution_position:]
    assert "futures_readiness_result" not in execution_call.split(")", 1)[0]
    assert "monitor_positions=False" in source
