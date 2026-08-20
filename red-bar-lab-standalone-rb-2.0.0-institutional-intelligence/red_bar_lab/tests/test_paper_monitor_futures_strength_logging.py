import inspect

from red_bar_lab.execution import paper_monitor


def test_paper_monitor_logs_futures_strength_fields():
    source = inspect.getsource(paper_monitor.main)

    assert "assess_nifty_futures_positioning_strength(" in source
    assert "futures_positioning_strength_log_values(" in source
    assert "futures_strength_status=%s" in source
    assert "futures_strength_reason=%s" in source
    assert "futures_strength=%s" in source
    assert "futures_strength_state=%s" in source
    assert "futures_strength_price_pct=%s" in source
    assert "futures_strength_oi_pct=%s" in source
    assert "futures_strength_rvol=%s" in source


def test_futures_strength_is_collected_before_execution_cycle():
    source = inspect.getsource(paper_monitor.main)

    strength_position = source.index("assess_nifty_futures_positioning_strength(")
    execution_position = source.index("report = automation.run_cycle(")

    assert strength_position < execution_position
    assert "monitor_positions=False" in source
