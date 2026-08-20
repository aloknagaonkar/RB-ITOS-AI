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

    for field in (
        "futures_readiness=%s",
        "futures_readiness_reason=%s",
        "futures_contract_status=%s",
        "futures_market_status=%s",
        "futures_candle_status=%s",
        "futures_volume_status=%s",
        "futures_oi_status=%s",
        "futures_positioning_status=%s",
        "futures_positioning_state=%s",
        "futures_blocking_reasons=%s",
        "futures_advisory_reasons=%s",
    ):
        assert field in source


def test_unified_futures_readiness_remains_observational():
    source = inspect.getsource(paper_monitor.main)

    readiness_position = source.index("assess_nifty_futures_readiness(")
    execution_position = source.index("report = automation.run_cycle(")

    assert readiness_position < execution_position
    execution_call = source[execution_position:]
    assert "futures_readiness_result" not in execution_call.split(")", 1)[0]
    assert "monitor_positions=False" in source
