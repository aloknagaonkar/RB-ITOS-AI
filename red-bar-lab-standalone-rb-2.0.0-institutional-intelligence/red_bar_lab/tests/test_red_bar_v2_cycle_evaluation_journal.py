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
        pcr_context={
            "overall_pcr": 0.72,
            "overall_direction": "BEARISH",
            "morning_pcr": 0.68,
            "combined_pcr": 0.81,
            "combined_direction": "BULLISH",
            "combined_coverage": 0.92,
            "source_timestamp": "2026-08-31T07:30:12+00:00",
            "trading_date": "2026-08-31",
        },
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
    assert row["pcr"]["overall_pcr"] == 0.72
    assert row["pcr"]["morning_pcr"] == 0.68
    assert row["pcr"]["combined_pcr"] == 0.81
    assert row["pcr"]["combined_direction"] == "BULLISH"


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
    assert result.pcr_context is None


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
        "upgrade",
        "reentry",
        "admission",
    ):
        assert section in state
    assert state["as_of"] is not None
    # The 12:45-13:15 rule was deleted, so the section it reported is gone too.
    # Leaving an always-inactive section behind would keep advertising a rule the
    # strategy no longer has.
    assert "mid_session" not in state

    assert state["reference"]["established"] is True
    assert isinstance(state["reference"]["midpoint"], float)
    assert state["initial"]["status"] == "ESTABLISHED"
    assert state["initial"]["direction"] in {"BULLISH", "BEARISH"}
    assert state["initial"]["admitted"] is True
    assert state["initial"]["evaluations"] > 0
    assert state["admission"]["admitted"] >= 1
    assert state["admission"]["last_admission_code"]
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
    ).replace(
        "    pcr_json TEXT NOT NULL DEFAULT '{}',\n", ""
    )
    assert "rule_state_json" not in legacy_schema
    assert "pcr_json" not in legacy_schema
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
    assert rows[0]["pcr"]["overall_pcr"] == 0.72


def test_current_session_wires_rule_state_from_replay():
    from red_bar_lab.services import red_bar_v2_current_session

    source = inspect.getsource(red_bar_v2_current_session)
    assert 'rule_state=getattr(monitored.replay, "rule_state", None)' in source
    assert 'pcr_context=getattr(monitored, "pcr_context", None)' in source


def test_read_pcr_context_from_history_payload(tmp_path: Path):
    import json
    import sqlite3

    from types import SimpleNamespace

    from red_bar_lab.services.red_bar_v2_futures_replay_service import (
        read_red_bar_v2_pcr_context,
    )

    path = tmp_path / "lab.sqlite3"
    payload = {
        "overall_pcr": 0.72,
        "morning_pcr": 0.68,
        "combined_index_pcr": 0.81,
        "combined_direction": "BULLISH",
        "combined_coverage": 0.92,
    }
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE market_trend_research_pcr_5m_history (
            underlying TEXT NOT NULL,
            trading_date TEXT NOT NULL,
            candle_close_timestamp TEXT NOT NULL,
            source_timestamp TEXT NOT NULL,
            overall_pcr REAL NOT NULL,
            overall_direction TEXT NOT NULL,
            quality_state TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(underlying, candle_close_timestamp)
        )
        """
    )
    connection.execute(
        "INSERT INTO market_trend_research_pcr_5m_history VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "NIFTY 50",
            "2026-08-31",
            "2026-08-31T07:30:00+00:00",
            "2026-08-31T07:30:12+00:00",
            0.72,
            "BEARISH",
            "COMPLETE",
            json.dumps(payload),
            "2026-08-31T07:30:15+00:00",
        ),
    )
    connection.commit()
    connection.close()

    context = read_red_bar_v2_pcr_context(
        SimpleNamespace(path=path),
        "NSE_INDEX|Nifty 50",
        "2026-08-31",
    )
    assert context["overall_pcr"] == 0.72
    assert context["overall_direction"] == "BEARISH"
    assert context["morning_pcr"] == 0.68
    assert context["combined_pcr"] == 0.81
    assert context["combined_direction"] == "BULLISH"
    assert context["combined_coverage"] == 0.92
    assert context["source_timestamp"] == "2026-08-31T07:30:12+00:00"


def test_read_pcr_context_degrades_without_tables(tmp_path: Path):
    from types import SimpleNamespace

    from red_bar_lab.services.red_bar_v2_futures_replay_service import (
        read_red_bar_v2_pcr_context,
    )

    context = read_red_bar_v2_pcr_context(
        SimpleNamespace(path=tmp_path / "missing.sqlite3"),
        "NSE_INDEX|Nifty 50",
        "2026-08-31",
    )
    assert context["overall_pcr"] is None
    assert context["morning_pcr"] is None
    assert context["combined_pcr"] is None


def test_monitored_replay_result_exposes_pcr_context():
    from red_bar_lab.services import red_bar_v2_futures_replay_service

    source = inspect.getsource(red_bar_v2_futures_replay_service)
    assert "pcr_context=pcr_context" in source
    assert "pcr_context: Mapping[str, Any] | None = None" in source
    assert "_read_latest_pcr_snapshot" not in source


def test_replay_rule_state_reentry_narrative_keys():
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
    reentry = replay.rule_state["reentry"]
    for key in (
        "waiting_since",
        "last_touch_at",
        "last_touch_direction",
        "last_vwap_confirmed",
        "last_direction",
    ):
        assert key in reentry


def test_replay_rule_state_reentry_wait_after_trade_close():
    from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
        replay_red_bar_v2_day_with_futures_vwap,
    )

    index_candles, futures_candles = _rule_state_market_frames()
    base, _ = replay_red_bar_v2_day_with_futures_vwap(
        index_candles,
        futures_candles,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|NIFTY-FUT",
    )
    admitted_at = next(
        event.timestamp
        for event in base.events
        if event.event_type == "CANDIDATE_ADMISSION" and event.candidate_allowed
    )
    from datetime import timedelta

    exit_at = admitted_at + timedelta(minutes=2)
    replay, _ = replay_red_bar_v2_day_with_futures_vwap(
        index_candles,
        futures_candles,
        instrument_key="NSE_INDEX|Nifty 50",
        vwap_instrument_key="NSE_FO|NIFTY-FUT",
        exit_timestamps=(exit_at,),
    )
    reentry = replay.rule_state["reentry"]
    # The closed trade must start the re-entry wait and record when.
    assert reentry["waiting_since"] == exit_at.isoformat()
    assert reentry["waiting"] is True or reentry["last_outcome"] in {
        "VALIDATED",
        "FAILED",
    }


def test_rule_sentence_builders():
    from red_bar_lab.ui.pages import v2_evaluation_monitor as page

    row = {
        "index_close": 24219.0,
        "futures_close": 24245.0,
        "futures_vwap": 24234.49,
        "price_vs_vwap": "ABOVE",
        "pcr": {
            "overall_pcr": 0.72,
            "morning_pcr": 0.68,
            "combined_pcr": 0.81,
        },
    }
    state = {
        "current_direction": "BULLISH",
        "reference": {"midpoint": 24210.0},
        "initial": {"direction": "BULLISH"},
        "reversal": {
            "last_direction": "BULLISH",
            "last_detected_at": "2026-08-31T10:35:00+05:30",
            "last_trend_strength": "CONFIRMED",
        },
        "reentry": {
            "waiting": True,
            "waiting_since": "2026-08-31T13:02:00+05:30",
            "last_touch_at": "2026-08-31T13:08:00+05:30",
            "last_touch_direction": "BEARISH",
            "last_vwap_confirmed": False,
            "last_outcome": "FAILED",
            "last_outcome_at": "2026-08-31T13:13:00+05:30",
        },
        "admission": {"active_trade_count": 1, "trade_state": "OPEN"},
    }

    rule_one = page._rule_one_sentence(row, state)
    assert rule_one == (
        "BULLISH: futures close 24,245.00 > futures VWAP 24,234.49 AND "
        "index close 24,219.00 > red-bar midpoint 24,210.00."
    )

    rule_two = page._rule_two_sentence(row, state)
    assert "Currently BEARISH + futures close > futures VWAP" in rule_two
    assert "BULLISH reversal detected at 10:35:00" in rule_two
    assert "confirmed" in rule_two

    # The grade has to come from the grade, not from midpoint alignment: every
    # admitted reversal clears the midpoint, so reading it off that flag would
    # report every reversal as confirmed and hide the provisional ones.
    provisional = dict(state)
    provisional["reversal"] = {
        **state["reversal"],
        "last_trend_strength": "PROVISIONAL",
    }
    assert "provisional" in page._rule_two_sentence(row, provisional)

    rule_five = page._rule_five_sentence(state)
    assert "trade closed at 13:02:00" in rule_five
    assert "BEARISH touch of the midpoint at 13:08:00" in rule_five
    assert "opposite side of VWAP" in rule_five
    assert "Re-entry FAILED at 13:13:00" in rule_five

    rule_six = page._rule_six_sentence(row, state)
    assert "Trade ACTIVE (state OPEN)" in rule_six
    assert "overall 0.720" in rule_six
    assert "morning 0.680" in rule_six
    assert "combined 0.810" in rule_six

    assert page._pcr_brief(row["pcr"]) == (
        "Overall 0.720 · Morning 0.680 · Combined 0.810"
    )
    assert page._rule_six_sentence(row, {"admission": {"active_trade_count": 0}}) is None
    assert page._rule_two_sentence(row, {"reversal": {}}) is None


def _frozen_bearish_cycle() -> tuple[dict, dict]:
    """The 2026-09-03 live row, reduced to the fields the note reads.

    Reference established 09:20 on a red bar with midpoint 23973.15; the 09:25
    close was below it with futures below VWAP, so BEARISH/PE was admitted and
    was correct at 09:25. By 10:21 the index was 18 points *above* that midpoint
    and a BULLISH reversal had been pending since 09:30 -- and the display still
    read BEARISH, because the 09:25 trade row never closed.
    """
    row = {
        "admission_direction": "BEARISH",
        "admission_code": "INITIAL_BEARISH_ALIGNMENT",
        "index_close": 23991.15,
        "reference_midpoint": 23973.15,
    }
    state = {
        "current_direction": "BEARISH",
        "reference": {"midpoint": 23973.15},
        "initial": {"status": "ESTABLISHED", "direction": "BEARISH"},
        "reversal": {
            "pending": True,
            "monitoring": True,
            "detections": 1,
            "last_direction": "BULLISH",
            "last_detected_at": "2026-09-03T09:30:00+05:30",
        },
        "admission": {
            "admitted": 1,
            "blocked": 49,
            "active_trade_count": 1,
            "trade_state": "ACTIVE",
            "last_admitted_at": "2026-09-03T09:25:00+05:30",
            "last_block_code": "ACTIVE_TRADE_BLOCK",
            "last_block_at": "2026-09-03T10:18:00+05:30",
        },
    }
    return row, state


def test_a_frozen_direction_is_reported_as_stale():
    from red_bar_lab.ui.pages import v2_evaluation_monitor as page

    row, state = _frozen_bearish_cycle()
    note = page._admission_staleness(row, state)

    assert note is not None
    # It must say the direction is historical, and when it was taken -- a reader
    # cannot judge a verdict without its age.
    assert "last ADMITTED direction" in note
    assert "09:25:00" in note
    assert "not a live verdict" in note
    # Both failures, separately: the premise is gone, and it cannot be acted on.
    assert "above the 23,973.15 midpoint" in note
    assert "+18.00 pts" in note
    assert "BULLISH reversal has been pending since 09:30:00" in note
    assert "ACTIVE_TRADE_BLOCK" in note
    assert "49 blocked" in note


def test_an_aligned_direction_is_not_called_stale():
    """An open position with price on its own side is a trade, not a defect."""
    from red_bar_lab.ui.pages import v2_evaluation_monitor as page

    row, state = _frozen_bearish_cycle()
    row["index_close"] = 23950.0
    state["reversal"] = {"pending": False, "monitoring": True}

    # ACTIVE_TRADE_BLOCK is still the last block code and the row is still ACTIVE
    # -- neither is staleness on its own, or every healthy position would warn.
    assert page._admission_staleness(row, state) is None


def test_price_through_the_midpoint_is_stale_even_with_no_reversal_detected():
    """The premise failing does not depend on the reversal machinery firing.

    Reversal detection is a 5-minute rule with its own gates; if it has not
    fired, or fired and was discarded, the displayed direction is still being
    contradicted by the index close and must still say so.
    """
    from red_bar_lab.ui.pages import v2_evaluation_monitor as page

    row, state = _frozen_bearish_cycle()
    state["reversal"] = {"pending": False, "monitoring": True, "detections": 0}
    note = page._admission_staleness(row, state)

    assert note is not None
    assert "above the 23,973.15 midpoint" in note
    assert "reversal has been pending" not in note


def test_staleness_reads_either_direction_field_and_survives_thin_rows():
    from red_bar_lab.ui.pages import v2_evaluation_monitor as page

    row, state = _frozen_bearish_cycle()
    # Journal rows written before ``admission_direction`` existed fall back to
    # the rule state, so section 4's metric can be marked as well as section 3's.
    del row["admission_direction"]
    assert page._admission_staleness(row, state) is not None

    # No direction, no midpoint, no state: a note is impossible, not an error.
    assert page._admission_staleness({}, {}) is None
    assert page._admission_staleness({"admission_direction": "—"}, {}) is None
    assert page._admission_staleness({"admission_direction": "BEARISH"}, {}) is None
    assert (
        page._admission_staleness(
            {"admission_direction": "BEARISH", "index_close": "n/a"},
            {"reference": {"midpoint": "n/a"}},
        )
        is None
    )


def test_the_monitor_page_surfaces_staleness_where_direction_is_shown():
    from red_bar_lab.ui.pages import v2_evaluation_monitor

    source = inspect.getsource(v2_evaluation_monitor)
    # Both places that print a direction must consult the same helper, or one of
    # them goes on presenting a frozen verdict as current.
    assert source.count("_admission_staleness(row, state)") == 2
    assert "STALE" in source


def test_monitor_page_renders_pcr_and_sentences():
    from red_bar_lab.ui.pages import v2_evaluation_monitor

    source = inspect.getsource(v2_evaluation_monitor)
    assert "Overall PCR" in source
    assert "Morning PCR" in source
    assert "Combined PCR" in source
    assert "PCR info" in source
    assert "red-bar midpoint" in source
