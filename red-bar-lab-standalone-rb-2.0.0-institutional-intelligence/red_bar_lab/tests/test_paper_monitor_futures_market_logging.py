import inspect

from red_bar_lab.execution import paper_monitor


def test_paper_monitor_collects_and_logs_futures_market_telemetry():
    source = inspect.getsource(paper_monitor.main)

    assert "assess_nifty_futures_market_data(" in source
    assert "contract=futures_result" in source
    assert "now=cycle_started" in source
    assert "futures_market_log_values(" in source

    for field in (
        "futures_market=%s",
        "futures_market_reason=%s",
        "futures_candle=%s",
        "futures_volume=%s",
        "futures_close=%s",
        "futures_volume_value=%s",
        "futures_oi=%s",
        "futures_timestamp=%s",
        "futures_candle_count=%s",
        "futures_market_error=%s",
    ):
        assert field in source


def test_futures_market_diagnostics_remain_separate_from_execution_report():
    source = inspect.getsource(paper_monitor.main)

    diagnostic_position = source.index("assess_nifty_futures_market_data(")
    execution_position = source.index("report = automation.run_cycle(")

    assert diagnostic_position < execution_position
    assert "monitor_positions=False" in source
