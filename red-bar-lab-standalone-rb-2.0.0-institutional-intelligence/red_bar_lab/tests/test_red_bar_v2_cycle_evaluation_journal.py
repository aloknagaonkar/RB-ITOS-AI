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
    assert result.rule_state is None


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
    assert "_render_rule_state" in source
    assert "Strategy rule state" in source


def _rule_state_candles(closes, volumes):
    from datetime import datetime, timedelta, timezone

    import pandas as pd

    ist = timezone(timedelta(hours=5, minutes=30))
    timestamps = pd.date_range(
        datetime(2026, 8, 24, 9, 15, tzinfo=ist),
        periods=len(closes),
        freq="1min",
    )
    opens = [closes[0] - 0.2, *closes[:-1]]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) + 0.4 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 0.4 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": volumes,
        },
        index=timestamps,
    )


def _rule_state_market_frames():
    index_closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    index_closes += [103.0, 101.0, 99.0, 97.0, 95.0]
    index_closes += [96.0 + index * 0.9 for index in range(40)]
    futures_closes = [200.0 + index * 0.6 for index in range(50)]
    index_volumes = [10.0 + index for index in range(50)]
    futures_volumes = [1000.0 + index * 10.0 for index in range(50)]
    return (
        _rule_state_candles(index_closes, index_volumes),
        _rule_state_candles(futures_closes, futures_volumes),
    )


def test_replay_rule_state_reports_every_rule():
    from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
        replay_red_bar_v2_day_with_futures_vwap,
    )

    index_candles, futures_candles = _rule_state_market_frames()
    replay, _ = replay_red_bar_v2_day_with_futures_vwap(
        index_candles,
        futures_candles,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|NIFTY-FUT",
    )

    state = replay.rule_state
    assert state is not None
    for section in (
        "reference",
        "initial",
        "reversal",
        "mid_session",
        "upgrade",
        "reentry",
        "admission",
    ):
        assert section in state
    assert state["as_of"] is not None

    assert state["reference"]["established"] is True
    assert isinstance(state["reference"]["midpoint"], float)
    assert state["initial"]["status"] == "ESTABLISHED"
    assert state["initial"]["direction"] in {"BULLISH", "BEARISH"}
    assert state["initial"]["admitted"] is True
    assert state["initial"]["evaluations"] > 0
    assert state["admission"]["admitted"] >= 1
    assert state["admission"]["last_admission_code"]
    assert state["mid_session"]["active"] is False
    assert state["reentry"]["waiting"] is False
    assert state["upgrade"]["provisional_state"] is None
    assert state["current_direction"] in {"BULLISH", "BEARISH"}


def test_replay_rule_state_reference_pending_before_red_bar():
    from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
        replay_red_bar_v2_day_with_futures_vwap,
    )

    rising = [100.0 + index for index in range(5)]
    volumes = [10.0] * 5
    replay, _ = replay_red_bar_v2_day_with_futures_vwap(
        _rule_state_candles(rising, volumes),
        _rule_state_candles([200.0 + index for index in range(5)], volumes),
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|NIFTY-FUT",
    )

    state = replay.rule_state
    assert state is not None
    assert state["reference"]["established"] is False
    assert state["initial"]["status"] == "REFERENCE_PENDING"
    assert state["initial"]["evaluations"] == 0
    assert state["reversal"]["monitoring"] is False
    assert state["admission"]["admitted"] == 0


def test_cycle_evaluation_round_trips_rule_state(tmp_path: Path):
    path = tmp_path / "lab.sqlite3"
    live_v2, snapshot, bridge, readiness, report = _stubs()
    live_v2.rule_state = {
        "as_of": "2026-08-31T13:01:00+05:30",
        "reference": {"established": True, "midpoint": 24210.0},
        "initial": {"status": "ESTABLISHED", "direction": "BEARISH"},
    }

    persist_red_bar_v2_cycle_evaluation(
        path,
        run_id="run-3",
        observed_at="2026-08-31T13:01:05+05:30",
        trading_date="2026-08-31",
        underlying_name="NIFTY 50",
        instrument_key="NSE_INDEX|Nifty 50",
        live_v2=live_v2,
        snapshot=snapshot,
        bridge=bridge,
        readiness=readiness,
        report=report,
    )

    rows = read_red_bar_v2_cycle_evaluations(path, trading_date="2026-08-31")
    assert rows[0]["rule_state"]["initial"]["direction"] == "BEARISH"
    assert rows[0]["rule_state"]["reference"]["midpoint"] == 24210.0


def test_cycle_evaluation_migrates_legacy_table_without_rule_state(tmp_path: Path):
    import sqlite3

    from red_bar_lab.services import red_bar_v2_cycle_evaluation_store as store

    path = tmp_path / "lab.sqlite3"
    legacy_schema = store._SCHEMA.replace(
        "    rule_state_json TEXT NOT NULL DEFAULT '{}',\n", ""
    )
    assert "rule_state_json" not in legacy_schema
    connection = sqlite3.connect(path)
    connection.executescript(legacy_schema)
    connection.commit()
    connection.close()

    live_v2, snapshot, bridge, readiness, report = _stubs()
    live_v2.rule_state = {"initial": {"status": "SCANNING"}}
    persist_red_bar_v2_cycle_evaluation(
        path,
        run_id="run-legacy",
        observed_at="2026-08-31T13:05:05+05:30",
        trading_date="2026-08-31",
        underlying_name="NIFTY 50",
        instrument_key="NSE_INDEX|Nifty 50",
        live_v2=live_v2,
        snapshot=snapshot,
        bridge=bridge,
        readiness=readiness,
        report=report,
    )

    rows = read_red_bar_v2_cycle_evaluations(path, trading_date="2026-08-31")
    assert rows[0]["run_id"] == "run-legacy"
    assert rows[0]["rule_state"] == {"initial": {"status": "SCANNING"}}


def test_current_session_wires_rule_state_from_replay():
    from red_bar_lab.services import red_bar_v2_current_session

    source = inspect.getsource(red_bar_v2_current_session)
    assert 'rule_state=getattr(monitored.replay, "rule_state", None)' in source
