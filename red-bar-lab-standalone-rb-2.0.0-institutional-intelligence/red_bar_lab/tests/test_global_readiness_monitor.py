import inspect

from red_bar_lab.execution import paper_monitor


def test_global_readiness_runs_after_stable_automation_cycle():
    source = inspect.getsource(paper_monitor.main)
    run_cycle_index = source.index("report = automation.run_cycle(")
    readiness_index = source.index("build_and_persist_global_readiness(")
    assert run_cycle_index < readiness_index


def test_global_readiness_is_not_passed_into_automation_cycle():
    source = inspect.getsource(paper_monitor.main)
    call = source[source.index("report = automation.run_cycle("):source.index("totals[\"signals_seen\"]")]
    assert "global_readiness" not in call
    assert "futures_readiness" not in call


def test_monitor_logs_all_global_reason_categories():
    source = inspect.getsource(paper_monitor.main)
    for field in (
        "global_readiness=%s",
        "global_blocking_reasons=%s",
        "global_advisory_reasons=%s",
        "global_execution_reasons=%s",
        "global_authority=%s",
    ):
        assert field in source
