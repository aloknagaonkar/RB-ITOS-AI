import inspect
from pathlib import Path
from types import SimpleNamespace

from red_bar_lab.execution import paper_monitor
from red_bar_lab.services.red_bar_v2_cycle_evaluation_store import (
    persist_red_bar_v2_cycle_evaluation,
    read_red_bar_v2_cycle_evaluations,
)


def _stubs():
    live_v2 = SimpleNamespace(
        status="BLOCKED",
        reason="FUTURES_TIMESTAMP_MISMATCH",
        admitted_candidates=0,
        closed_trades=0,
        completed_1m_close=24199.0,
        completed_1m_rsi=52.3,
        completed_1m_timestamp="2026-08-31T13:00:00+05:30",
        market_data_evidence=(),
        session_health={
            "status": "BLOCKED",
            "reason": "FUTURES_TIMESTAMP_MISMATCH",
            "aligned_rows": 384,
            "alignment_coverage_pct": 99.7,
            "index_rows": 385,
            "futures_rows": 384,
            "index_timestamp": "2026-08-31T13:01:00+05:30",
            "futures_timestamp": "2026-08-31T13:00:00+05:30",
            "last_aligned_timestamp": "2026-08-31T13:00:00+05:30",
        },
        candidate_events_scanned=2,
        latest_admission=None,
    )
    snapshot = SimpleNamespace(
        index_close=24199.0,
        index_rsi=52.3,
        futures_close=24245.0,
        futures_vwap=24234.49,
        reference_midpoint=24210.0,
    )
    bridge = SimpleNamespace(status="BLOCKED", reason="V2_SOURCE_ALIGNMENT_NOT_READY")
    readiness = SimpleNamespace(
        status="UNAVAILABLE",
        reason="Global readiness cannot be established from the available observations.",
        blocking_reasons=("OPTION_QUOTE_UNAVAILABLE", "PCR_UNAVAILABLE"),
        advisory_reasons=("MARKET_HOURS_MARKET_CLOSED",),
        execution_reasons=(),
    )
    report = SimpleNamespace(
        signals_seen=0,
        candidates_scored=0,
        paper_orders_opened=0,
        skipped=0,
        errors=[],
    )
    return live_v2, snapshot, bridge, readiness, report


def test_cycle_evaluation_round_trip_and_idempotency(tmp_path: Path):
    path = tmp_path / "lab.sqlite3"
    live_v2, snapshot, bridge, readiness, report = _stubs()

    for _ in range(2):
        persist_red_bar_v2_cycle_evaluation(
            path,
            run_id="run-1",
            observed_at="2026-08-31T13:01:05+05:30",
            trading_date="2026-08-31",
            underlying_name="NIFTY 50",
            instrument_key="NSE_INDEX|Nifty 50",
            live_v2=live_v2,
            snapshot=snapshot,
            bridge=bridge,
            readiness=readiness,
            report=report,
            cycle_timings_ms={"v2_evaluation": 123.0, "signal_publication": 4.0},
        )

    rows = read_red_bar_v2_cycle_evaluations(path, trading_date="2026-08-31")
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "run-1"
    assert row["cycle_status"] == "BLOCKED"
    assert row["context_status"] == "BLOCKED"
    assert row["context_reason"] == "FUTURES_TIMESTAMP_MISMATCH"
    assert row["aligned_rows"] == 384
    assert row["price_vs_vwap"] == "ABOVE"
    assert row["bridge_status"] == "BLOCKED"
    assert row["readiness_status"] == "UNAVAILABLE"
    assert row["blocking_reasons"] == [
        "OPTION_QUOTE_UNAVAILABLE",
        "PCR_UNAVAILABLE",
    ]
    assert row["cycle_timings"]["v2_evaluation"] == 123.0
    assert row["authority"] == "OBSERVATIONAL_ONLY"


def test_cycle_evaluation_records_admission_summary(tmp_path: Path):
    path = tmp_path / "lab.sqlite3"
    live_v2, snapshot, bridge, readiness, report = _stubs()
    live_v2.admitted_candidates = 1
    live_v2.latest_admission = {
        "event_type": "CANDIDATE_ADMISSION",
        "direction": "BEARISH",
        "option_side": "PE",
        "entry_type": "INITIAL_DISPLACEMENT",
        "trend_strength": "MODERATE",
        "admission_code": "V2_ADMITTED",
        "admission_reason": "All gates passed.",
        "candidate_allowed": True,
        "score": 0.81,
    }

    persist_red_bar_v2_cycle_evaluation(
        path,
        run_id="run-2",
        observed_at="2026-08-31T13:02:05+05:30",
        trading_date="2026-08-31",
        underlying_name="NIFTY 50",
        instrument_key="NSE_INDEX|Nifty 50",
        live_v2=live_v2,
        snapshot=snapshot,
        bridge=bridge,
        readiness=readiness,
        report=report,
    )

    rows = read_red_bar_v2_cycle_evaluations(path)
    assert rows[0]["admitted_candidates"] == 1
    assert rows[0]["admission_direction"] == "BEARISH"
    assert rows[0]["admission_code"] == "V2_ADMITTED"


def test_cycle_evaluation_read_without_table_returns_empty(tmp_path: Path):
    assert read_red_bar_v2_cycle_evaluations(tmp_path / "missing.sqlite3") == []


def test_result_defaults_include_journal_fields():
    from red_bar_lab.services.red_bar_v2_current_session import (
        CurrentSessionV2Result,
    )

    result = CurrentSessionV2Result(status="WAITING", reason="INDEX_INTRADAY_UNAVAILABLE")
    assert result.session_health is None
    assert result.candidate_events_scanned == 0
    assert result.latest_admission is None


def test_evaluate_populates_session_health_from_monitored_replay():
    from red_bar_lab.services import red_bar_v2_current_session

    source = inspect.getsource(red_bar_v2_current_session)
    assert 'getattr(health, "to_dict", None)' in source
    assert "session_health=session_health" in source
    assert "candidate_events_scanned=len(candidate_events)" in source
    assert "latest_admission=admission_summary" in source


def test_monitor_persists_journal_after_automation_and_readiness():
    source = inspect.getsource(paper_monitor.main)
    automation_index = source.index("report = automation.run_cycle(")
    readiness_index = source.index("build_and_persist_global_readiness(")
    journal_index = source.index("persist_red_bar_v2_cycle_evaluation(")
    assert automation_index < readiness_index < journal_index
    assert "V2_CYCLE_EVALUATION_PERSIST_FAILED" in source


def test_journal_is_not_consumed_by_automation_cycle():
    source = inspect.getsource(paper_monitor.main)
    call = source[
        source.index("report = automation.run_cycle("):source.index(
            'totals["signals_seen"]'
        )
    ]
    assert "cycle_evaluation" not in call


def test_evaluation_monitor_page_is_read_only():
    from red_bar_lab.ui.pages import v2_evaluation_monitor

    source = inspect.getsource(v2_evaluation_monitor)
    assert "OBSERVATIONAL ONLY" in source
    assert "read_red_bar_v2_cycle_evaluations" in source
    assert "automation.run_cycle" not in source
    assert "close_position" not in source
