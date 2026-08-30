"""Tests for the Red Bar V2 strategy engine's per-step evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest


def test_record_strategy_subcheck_writes_evidence_row(tmp_path: Path):
    from red_bar_lab.observability import record_strategy_subcheck as _record_strategy_subcheck
    from red_bar_lab.storage.database import RedBarDatabase

    db = RedBarDatabase(tmp_path / "test.db")
    rid = "red-bar-run-001"
    _record_strategy_subcheck(
        db,
        run_id=rid,
        step_name="latest_completed_1m_candle",
        artifacts={"candle_close": 24817.5, "rsi_14": 62.4},
    )
    rows = db.read_run_evidence(run_id=rid)
    assert len(rows) == 1
    row = rows[0]
    assert row["process_name"] == "red_bar_v2_strategy"
    assert row["step_name"] == "latest_completed_1m_candle"
    assert row["status"] == "OK"
    assert row["artifacts"]["candle_close"] == 24817.5
    assert row["artifacts"]["rsi_14"] == 62.4


def test_record_strategy_subcheck_no_op_without_run_id(tmp_path: Path):
    from red_bar_lab.observability import record_strategy_subcheck as _record_strategy_subcheck
    from red_bar_lab.storage.database import RedBarDatabase

    db = RedBarDatabase(tmp_path / "test.db")
    # No run_id => no write, no raise.
    _record_strategy_subcheck(
        db,
        run_id=None,
        step_name="candidate_scan",
    )


def test_record_strategy_subcheck_writes_error_rows(tmp_path: Path):
    from red_bar_lab.observability import record_strategy_subcheck as _record_strategy_subcheck
    from red_bar_lab.storage.database import RedBarDatabase

    db = RedBarDatabase(tmp_path / "test.db")
    rid = "red-bar-run-error"
    _record_strategy_subcheck(
        db,
        run_id=rid,
        step_name="score_candidate",
        status="ERROR",
        error_message="score=58 below threshold 65",
    )
    rows = db.read_run_evidence(run_id=rid)
    assert len(rows) == 1
    assert rows[0]["status"] == "ERROR"
    assert "below threshold" in (rows[0]["error_message"] or "")


def test_record_strategy_subcheck_swallows_db_errors():
    """If the database has no write_step_evidence method, the helper
    must not raise. (Live mode might run with a partial database
    stand-in.)"""
    from red_bar_lab.observability import record_strategy_subcheck as _record_strategy_subcheck

    class _InertDb:
        pass

    # Should not raise even though the database lacks the methods.
    _record_strategy_subcheck(
        _InertDb(),
        run_id="rid-1",
        step_name="latest_completed_1m_candle",
    )


# --------------------------------------------------------------------------
# UI sub-block tests
# --------------------------------------------------------------------------


@dataclass
class _St:
    expander_calls: list = field(default_factory=list)
    caption_calls: list = field(default_factory=list)
    markdown_calls: list = field(default_factory=list)

    def expander(self, label, expanded=True):
        self.expander_calls.append(label)

        class _C:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        return _C()

    def caption(self, text, *args, **kwargs):
        self.caption_calls.append(text)
        return None

    def markdown(self, text, *args, **kwargs):
        self.markdown_calls.append(text)
        return None

    def write(self, *args, **kwargs):
        return None


def test_render_strategy_engine_audit_omits_when_no_run_id():
    from red_bar_lab.ui import live_cadence as lc

    st = _St()
    lc.render_strategy_engine_audit(st, run_id=None)
    # No expander, no caption.
    assert st.expander_calls == []
    assert st.caption_calls == []


def test_render_strategy_engine_audit_omits_when_no_database_handle(monkeypatch):
    from red_bar_lab.ui import live_cadence as lc

    # Patch the handle resolver to return None.
    monkeypatch.setattr(lc, "_get_database_handle", lambda st: None)
    st = _St()
    lc.render_strategy_engine_audit(st, run_id="rid-1")
    assert st.expander_calls == []


def test_render_strategy_engine_audit_renders_substeps(monkeypatch):
    from red_bar_lab.ui import live_cadence as lc

    class _Db:
        def read_run_evidence(self, *, run_id):
            return [
                {
                    "process_name": "red_bar_v2_strategy",
                    "step_name": "latest_completed_1m_candle",
                    "status": "OK",
                    "artifacts": {
                        "candle_close": 24817.5,
                        "candle_rsi_14": 62.4,
                        "candle_timestamp": "2026-09-01T09:23:00+05:30",
                    },
                },
                {
                    "process_name": "red_bar_v2_strategy",
                    "step_name": "candidate_scan",
                    "status": "OK",
                    "artifacts": {
                        "candidate_count": 1,
                        "candidate_event_types": ["INITIAL_DISPLACEMENT"],
                    },
                },
                {
                    "process_name": "red_bar_v2_strategy",
                    "step_name": "admission_decision",
                    "status": "OK",
                    "artifacts": {
                        "direction": "LONG",
                        "outcome": "True",
                        "candidate_score": 82,
                    },
                },
            ]

    monkeypatch.setattr(lc, "_get_database_handle", lambda st: _Db())
    st = _St()
    lc.render_strategy_engine_audit(st, run_id="rid-1")
    # The expander was opened, and captions for each sub-step were
    # rendered with the artifacts.
    assert any(
        "Strategy Engine Audit" in label for label in st.expander_calls
    )
    captions = " ".join(st.caption_calls)
    assert "24817.5" in captions
    assert "62.4" in captions
    assert "INITIAL_DISPLACEMENT" in captions
    assert "LONG" in captions
    assert "82" in captions


def test_render_strategy_engine_audit_omits_other_processes(monkeypatch):
    """If the run_id has only `canonical_shadow` rows, the audit is
    not shown — it's specific to red_bar_v2_strategy."""
    from red_bar_lab.ui import live_cadence as lc

    class _Db:
        def read_run_evidence(self, *, run_id):
            return [
                {
                    "process_name": "canonical_shadow",
                    "step_name": "resolution",
                    "status": "OK",
                    "artifacts": {},
                },
            ]

    monkeypatch.setattr(lc, "_get_database_handle", lambda st: _Db())
    st = _St()
    lc.render_strategy_engine_audit(st, run_id="rid-1")
    # No expander because no red_bar_v2_strategy rows exist.
    assert st.expander_calls == []


def test_render_why_this_signal_fired_shows_5_gates(monkeypatch):
    """The 'Why this signal fired' panel should list the 5 gates as
    checkmarks, plus the admission header with event/direction/etc."""
    from red_bar_lab.ui import live_cadence as lc

    class _Db:
        def read_run_evidence(self, *, run_id):
            return [
                {
                    "process_name": "red_bar_v2_strategy",
                    "step_name": "admission_decision",
                    "status": "OK",
                    "artifacts": {
                        "event_type": "INITIAL_DISPLACEMENT",
                        "direction": "LONG",
                        "option_side": "CE",
                        "entry_type": "BREAKOUT",
                        "trend_strength": "STRONG",
                        "outcome": "True",
                        "candidate_score": 82,
                        "reason": "5m closed above VWAP with RSI=62.4",
                    },
                },
                {
                    "process_name": "red_bar_v2_strategy",
                    "step_name": "check:reference_ready",
                    "status": "OK",
                    "artifacts": {"passed": True, "state": "READY"},
                },
                {
                    "process_name": "red_bar_v2_strategy",
                    "step_name": "check:context_fresh",
                    "status": "OK",
                    "artifacts": {"passed": True},
                },
                {
                    "process_name": "red_bar_v2_strategy",
                    "step_name": "check:rsi_informational",
                    "status": "OK",
                    "artifacts": {"passed": True},
                },
                {
                    "process_name": "red_bar_v2_strategy",
                    "step_name": "check:vwap_aligned",
                    "status": "OK",
                    "artifacts": {"passed": True},
                },
                {
                    "process_name": "red_bar_v2_strategy",
                    "step_name": "check:midpoint_aligned",
                    "status": "ERROR",
                    "artifacts": {"passed": False},
                },
            ]

    monkeypatch.setattr(lc, "_get_database_handle", lambda st: _Db())
    st = _St()
    lc.render_strategy_engine_audit(st, run_id="rid-1")
    # The header should mention the event type, direction, etc.
    markdown_text = " ".join(st.markdown_calls)
    assert "INITIAL_DISPLACEMENT" in markdown_text
    assert "LONG" in markdown_text
    assert "BREAKOUT" in markdown_text
    assert "STRONG" in markdown_text
    assert "5m closed above VWAP" in markdown_text
    # 4 of 5 gates should show ✓, 1 should show ✗ (midpoint_aligned)
    captions = " ".join(st.caption_calls)
    assert "Reference ready" in captions
    assert "Context fresh" in captions
    assert "RSI (informational)" in captions
    assert "VWAP aligned" in captions
    assert "RedBar reference aligned" in captions
    # The ✗ should be on midpoint_aligned since that's the only ERROR.
    midpoint_caption = next(
        c for c in st.caption_calls if "RedBar reference aligned" in c
    )
    assert "✗" in midpoint_caption
    # The 4 passing gates should each have a ✓
    passing_caps = [
        c for c in st.caption_calls
        if any(name in c for name in ("Reference ready", "Context fresh",
                                     "RSI aligned", "VWAP aligned"))
        and "Midpoint" not in c
    ]
    for c in passing_caps:
        assert "✓" in c


@dataclass
class _PipelineFakeSt:
    """Just enough of a Streamlit stand-in for the pipeline sub-status test."""
    caption_calls: list = field(default_factory=list)

    def caption(self, text, *args, **kwargs):
        self.caption_calls.append(text)
        return None


def test_render_pipeline_sub_status_omits_when_no_run_id():
    from red_bar_lab.ui import live_cadence as lc

    st = _PipelineFakeSt()
    lc.render_pipeline_sub_status(
        st, section_id="lifecycle_eligibility", run_id=None
    )
    assert st.caption_calls == []


def test_render_pipeline_sub_status_omits_when_no_pipeline_rows(monkeypatch):
    from red_bar_lab.ui import live_cadence as lc

    class _Db:
        def read_run_evidence(self, *, run_id):
            return [{"process_name": "red_bar_v2_strategy", "step_name": "x"}]

    monkeypatch.setattr(lc, "_get_database_handle", lambda st: _Db())
    st = _PipelineFakeSt()
    lc.render_pipeline_sub_status(
        st, section_id="lifecycle_eligibility", run_id="rid-1"
    )
    assert st.caption_calls == []


def test_render_pipeline_sub_status_renders_lifecycle_check(monkeypatch):
    from red_bar_lab.ui import live_cadence as lc

    class _Db:
        def read_run_evidence(self, *, run_id):
            return [
                {
                    "process_name": "paper_trading_pipeline",
                    "step_name": "lifecycle_check",
                    "status": "OK",
                    "artifacts": {
                        "state": "FRESH",
                        "reason": "no_replacement",
                    },
                },
                {
                    "process_name": "paper_trading_pipeline",
                    "step_name": "score_candidates",
                    "status": "OK",
                    "artifacts": {
                        "best_candidate": "NIFTY26AUG25000CE",
                        "best_score": 82.0,
                        "minimum_score": 65.0,
                        "score_ok": True,
                    },
                },
            ]

    monkeypatch.setattr(lc, "_get_database_handle", lambda st: _Db())
    st = _PipelineFakeSt()
    # The "lifecycle_eligibility" section cares about lifecycle_check.
    lc.render_pipeline_sub_status(
        st, section_id="lifecycle_eligibility", run_id="rid-1"
    )
    captions = " ".join(st.caption_calls)
    assert "Lifecycle Check" in captions
    assert "FRESH" in captions
    # The score_candidates row is NOT in this section's checklist, so
    # it should not appear.
    assert "Score Candidates" not in captions


def test_render_pipeline_sub_status_renders_entry_section(monkeypatch):
    """The 'entry' section cares about lifecycle, regime, scoring, and
    order placement — all 4 rows should appear as a 4-step checklist."""
    from red_bar_lab.ui import live_cadence as lc

    class _Db:
        def read_run_evidence(self, *, run_id):
            return [
                {
                    "process_name": "paper_trading_pipeline",
                    "step_name": "lifecycle_check",
                    "status": "OK",
                    "artifacts": {"state": "FRESH"},
                },
                {
                    "process_name": "paper_trading_pipeline",
                    "step_name": "directional_regime",
                    "status": "OK",
                    "artifacts": {"regime": "BULLISH"},
                },
                {
                    "process_name": "paper_trading_pipeline",
                    "step_name": "score_candidates",
                    "status": "OK",
                    "artifacts": {
                        "best_candidate": "NIFTY26AUG25000CE",
                        "best_score": 82.0,
                        "minimum_score": 65.0,
                        "score_ok": True,
                    },
                },
                {
                    "process_name": "paper_trading_pipeline",
                    "step_name": "order_placement",
                    "status": "OK",
                    "artifacts": {
                        "order_id": "PE-001",
                        "symbol": "NIFTY26AUG25000CE",
                        "fill_price": 24830.5,
                    },
                },
                {
                    "process_name": "paper_trading_pipeline",
                    "step_name": "exit_decision",
                    "status": "OK",
                    "artifacts": {"reason": "TARGET_HIT"},
                },
            ]

    monkeypatch.setattr(lc, "_get_database_handle", lambda st: _Db())
    st = _PipelineFakeSt()
    lc.render_pipeline_sub_status(
        st, section_id="entry", run_id="rid-1"
    )
    captions = " ".join(st.caption_calls)
    # 4 of the 5 rows belong to the entry section checklist.
    assert "Lifecycle Check" in captions
    assert "Directional Regime" in captions
    assert "Score Candidates" in captions
    assert "Order Placement" in captions
    # exit_decision is NOT in the entry section, so it should be
    # omitted.
    assert "Exit Decision" not in captions
    # Each row's detail is surfaced (state, regime, score, fill_price).
    assert "FRESH" in captions
    assert "BULLISH" in captions
    assert "82.0" in captions
    assert "PE-001" in captions


def test_render_pipeline_sub_status_marks_failures_red(monkeypatch):
    """An ERROR step should be marked with ✗."""
    from red_bar_lab.ui import live_cadence as lc

    class _Db:
        def read_run_evidence(self, *, run_id):
            return [
                {
                    "process_name": "paper_trading_pipeline",
                    "step_name": "execution_committee",
                    "status": "ERROR",
                    "artifacts": {},
                    "error_message": "exec_prob below threshold",
                },
            ]

    monkeypatch.setattr(lc, "_get_database_handle", lambda st: _Db())
    st = _PipelineFakeSt()
    # risk_gates section cares about score, committee, portfolio_risk.
    # The execution_committee row is the only one that matches.
    lc.render_pipeline_sub_status(
        st, section_id="risk_gates", run_id="rid-1"
    )
    captions = " ".join(st.caption_calls)
    assert "✗" in captions
    assert "ERROR" in captions
    assert "Execution Committee" in captions


def test_render_pipeline_sub_status_shows_committee_reason_on_error(monkeypatch):
    """When the committee says ERROR, the user sees the full reason
    text (e.g. 'PERFORMANCE_HARD_BLOCK[...] | OPPORTUNITY_TERMINAL[...]')."""
    from red_bar_lab.ui import live_cadence as lc

    class _Db:
        def read_run_evidence(self, *, run_id):
            return [
                {
                    "process_name": "paper_trading_pipeline",
                    "step_name": "execution_committee",
                    "status": "ERROR",
                    "artifacts": {
                        "eligible": False,
                        "decision": "REJECTED",
                        "execution_probability_pct": 12.0,
                        "expected_value_pct": 0.0,
                        "intelligence_score": 65.0,
                        "reason": (
                            "PERFORMANCE_HARD_BLOCK[score=58 below threshold 65] "
                            "| EXECUTION_PROBABILITY=12.00<MIN=70.00"
                        ),
                    },
                },
            ]

    monkeypatch.setattr(lc, "_get_database_handle", lambda st: _Db())
    st = _PipelineFakeSt()
    lc.render_pipeline_sub_status(
        st, section_id="risk_gates", run_id="rid-1"
    )
    captions = " ".join(st.caption_calls)
    # The reason text appears in full, in its own caption (no
    # truncation).
    assert (
        "PERFORMANCE_HARD_BLOCK[score=58 below threshold 65]"
        in captions
    )
    assert "EXECUTION_PROBABILITY=12.00<MIN=70.00" in captions
    # The user doesn't need to expand anything to see this.
    assert "✗" in captions


def test_render_pipeline_sub_status_shows_committee_pass_on_ok(monkeypatch):
    """When the committee says OK, the sub-status shows the prob and
    a positive reason string (e.g. 'EXECUTION_COMMITTEE_APPROVED')."""
    from red_bar_lab.ui import live_cadence as lc

    class _Db:
        def read_run_evidence(self, *, run_id):
            return [
                {
                    "process_name": "paper_trading_pipeline",
                    "step_name": "execution_committee",
                    "status": "OK",
                    "artifacts": {
                        "eligible": True,
                        "decision": "ADMITTED",
                        "execution_probability_pct": 78.0,
                        "expected_value_pct": 2.4,
                        "intelligence_score": 82.0,
                        "reason": "EXECUTION_COMMITTEE_APPROVED | ALL_SELECTION_GATES_PASS",
                    },
                },
            ]

    monkeypatch.setattr(lc, "_get_database_handle", lambda st: _Db())
    st = _PipelineFakeSt()
    lc.render_pipeline_sub_status(
        st, section_id="risk_gates", run_id="rid-1"
    )
    captions = " ".join(st.caption_calls)
    assert "✓" in captions
    assert "OK" in captions
    assert "78.0%" in captions
    assert "EXECUTION_COMMITTEE_APPROVED" in captions


# --------------------------------------------------------------------------
# Active paper config / strategy / exit policy header tests
# --------------------------------------------------------------------------


@dataclass
class _ConfigFakeSt:
    caption_calls: list = field(default_factory=list)
    database_session_state: dict = field(default_factory=dict)

    def caption(self, text, *args, **kwargs):
        self.caption_calls.append(text)
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_render_active_paper_config_shows_default_strategy_and_exit():
    """When no orders exist yet, the header shows the Red Bar V2
    defaults (strategy + exit policy + thresholds)."""
    from red_bar_lab.ui import live_cadence as lc

    st = _ConfigFakeSt()
    # Patch _get_database_handle to return None (no DB session).
    def fake_get(st_arg):
        return None

    import red_bar_lab.ui.live_cadence as lc_module
    saved = lc_module._get_database_handle
    lc_module._get_database_handle = fake_get
    try:
        lc.render_active_paper_config(st)
    finally:
        lc_module._get_database_handle = saved
    captions = " ".join(st.caption_calls)
    assert "RED_BAR_V2" in captions
    assert "STANDARD_MULTI_FACTOR" in captions
    assert "OBSERVATIONAL" in captions
    assert "65" in captions  # min_candidate_score
    assert "85" in captions  # min_opportunity_score
    assert "70%" in captions  # min_execution_probability


def test_render_active_paper_config_reads_live_order():
    """When orders exist, the header infers strategy and exit_mode
    from the most-recent order's columns."""
    from red_bar_lab.ui import live_cadence as lc

    st = _ConfigFakeSt()

    class _Db:
        def read_paper_execution_orders(self, account_id):
            return [
                {
                    "execution_strategy_source": "RED_BAR_V2",
                    "exit_mode": "STANDARD_MULTI_FACTOR",
                    "stop_loss_pct": 7.0,
                    "target_pct": 1.5,
                    "entry_mode": "OPPORTUNITY_EXTENSION",
                    "order_id": "PE-001",
                    "entry_timestamp": "2026-09-01T09:30:00+05:30",
                }
            ]

    import red_bar_lab.ui.live_cadence as lc_module
    saved = lc_module._get_database_handle
    lc_module._get_database_handle = lambda st_arg: _Db()
    try:
        lc.render_active_paper_config(st)
    finally:
        lc_module._get_database_handle = saved
    captions = " ".join(st.caption_calls)
    assert "RED_BAR_V2" in captions
    assert "STANDARD_MULTI_FACTOR" in captions
    assert "PE-001" in captions
    assert "OPPORTUNITY_EXTENSION" in captions
    assert "7.0" in captions  # stop_loss_pct
    assert "1.5" in captions  # target_pct


# --------------------------------------------------------------------------
# Opportunity extension audit row tests
# --------------------------------------------------------------------------


def test_opportunity_extension_audit_helper_writes_row(tmp_path: Path):
    """When the extension path is taken, an opportunity_extension
    evidence row is written. The `process_evidence` table captures the
    artifacts so the per-step evidence panel can show it."""
    from red_bar_lab.storage.database import RedBarDatabase

    db = RedBarDatabase(tmp_path / "test.db")
    db.write_step_evidence(
        process_name="paper_trading_pipeline",
        run_id="rid-1",
        step_name="opportunity_extension",
        parent_step="pipeline",
        started_at="2026-09-01T09:30:00+05:30",
        status="OK",
        artifacts={
            "stale_for_extension": True,
            "eligible_candidates": 1,
        },
    )
    rows = db.read_step_timelines(limit_per_step=5)
    all_rows = [r for r in rows.values() for r in r]
    ext_rows = [
        r for r in all_rows
        if r["step_name"] == "opportunity_extension"
        and r["process_name"] == "paper_trading_pipeline"
    ]
    assert len(ext_rows) == 1
    assert ext_rows[0]["artifacts"]["stale_for_extension"] is True


def test_opportunity_extension_audit_helper_records_failure(tmp_path: Path):
    """When the extension path is tried but no candidate clears,
    the row's status is ERROR and carries an error_message."""
    from red_bar_lab.storage.database import RedBarDatabase

    db = RedBarDatabase(tmp_path / "test.db")
    db.write_step_evidence(
        process_name="paper_trading_pipeline",
        run_id="rid-1",
        step_name="opportunity_extension",
        parent_step="pipeline",
        started_at="2026-09-01T09:30:00+05:30",
        status="ERROR",
        artifacts={
            "stale_for_extension": True,
            "eligible_candidates": 0,
        },
    )
    db.update_step_evidence(
        step_id=1,
        completed_at="2026-09-01T09:30:00+05:30",
        status="ERROR",
        duration_ms=0.0,
        error_message=(
            "No candidate cleared the guarded opportunity extension."
        ),
    )
    rows = db.read_step_timelines(limit_per_step=5)
    all_rows = [r for r in rows.values() for r in r]
    ext_rows = [
        r for r in all_rows
        if r["step_name"] == "opportunity_extension"
    ]
    assert len(ext_rows) == 1
    assert ext_rows[0]["status"] == "ERROR"
    assert "guarded opportunity" in (
        ext_rows[0].get("error_message") or ""
    )


# --------------------------------------------------------------------------
# Tests for the new strategy rules
# --------------------------------------------------------------------------
# These rules live in the Red Bar V2 strategy functions and in the
# current_session pipeline. They are tested at the function level
# (decision dataclass output) and at the audit row level (process_evidence).


def test_mid_session_rule_active_outside_window_is_inactive():
    """Outside 12:45-1:15 IST, mid_session_active is False and
    mid_session_passed is None (the rule is implicitly passed, not
    evaluated)."""
    from datetime import datetime, timezone
    from red_bar_lab.strategy.red_bar_v2_futures import _is_mid_session_window

    # 9:30 AM - well before 12:45
    assert _is_mid_session_window(
        datetime(2026, 9, 1, 9, 30, tzinfo=timezone.utc)
    ) is False
    # 3:00 PM - well after 1:15
    assert _is_mid_session_window(
        datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)
    ) is False


def test_mid_session_rule_active_in_window():
    """Inside 12:45-1:15 IST, the rule is active. The 12:50 close
    is checked against the reference midpoint."""
    from datetime import datetime, timezone
    from red_bar_lab.strategy.red_bar_v2_futures import _is_mid_session_window

    # 12:50 PM
    assert _is_mid_session_window(
        datetime(2026, 9, 1, 12, 50, tzinfo=timezone.utc)
    ) is True
    # 1:10 PM
    assert _is_mid_session_window(
        datetime(2026, 9, 1, 13, 10, tzinfo=timezone.utc)
    ) is True


def test_mid_session_evaluate_passes_when_12_50_close_above_midpoint():
    """When the 12:50 close is above the reference midpoint, the rule
    passes with a BULLISH confirmation."""
    from datetime import datetime, timezone
    from red_bar_lab.strategy.red_bar_v2_futures import _evaluate_mid_session

    candle_ts = datetime(2026, 9, 1, 12, 50, tzinfo=timezone.utc)
    midpoint = 24800.0
    close = 24820.0  # 20 points above midpoint
    passed, reason = _evaluate_mid_session(candle_ts, midpoint, close)
    assert passed is True
    assert "BULLISH" in reason


def test_mid_session_evaluate_passes_when_12_50_close_below_midpoint():
    """When the 12:50 close is below the reference midpoint, the rule
    passes with a BEARISH confirmation."""
    from datetime import datetime, timezone
    from red_bar_lab.strategy.red_bar_v2_futures import _evaluate_mid_session

    candle_ts = datetime(2026, 9, 1, 12, 50, tzinfo=timezone.utc)
    midpoint = 24800.0
    close = 24780.0
    passed, reason = _evaluate_mid_session(candle_ts, midpoint, close)
    assert passed is True
    assert "BEARISH" in reason


def test_mid_session_evaluate_blocks_when_12_50_close_equals_midpoint():
    """When the 12:50 close exactly equals the midpoint, the rule
    returns (False, ...) — the signal is blocked because no
    direction is established."""
    from datetime import datetime, timezone
    from red_bar_lab.strategy.red_bar_v2_futures import _evaluate_mid_session

    candle_ts = datetime(2026, 9, 1, 12, 50, tzinfo=timezone.utc)
    midpoint = 24800.0
    close = 24800.0
    passed, reason = _evaluate_mid_session(candle_ts, midpoint, close)
    assert passed is False


def test_redbar_v2_decision_has_pcr_and_morning_pcr_fields():
    """The new informational fields exist and default to None."""
    from red_bar_lab.strategy.red_bar_v2 import RedBarV2DirectionDecision

    decision = RedBarV2DirectionDecision(
        event_type="INITIAL_BULLISH_ALIGNMENT",
        state="CONFIRMED_BULLISH",
        direction="BULLISH",
        option_side="CE",
        entry_type="INITIAL",
        trend_strength="CONFIRMED",
        context_timestamp=None,
        reference_timestamp=None,
        close_price=None,
        reason="test",
    )
    assert hasattr(decision, "pcr_value")
    assert hasattr(decision, "morning_pcr_value")
    assert hasattr(decision, "redbar_vwap_aligned")
    assert hasattr(decision, "mid_session_active")
    assert hasattr(decision, "mid_session_passed")
    assert hasattr(decision, "reentry_state")
    assert hasattr(decision, "reentry_alignment_passed")


def test_redbar_v2_decision_default_rsi_is_informational():
    """The new gate layout: rsi_aligned defaults to True
    (informational), redbar_vwap_aligned defaults to True
    (the new combined check), and vwap_aligned and midpoint_aligned
    are kept for backward compat."""
    from red_bar_lab.strategy.red_bar_v2 import RedBarV2DirectionDecision

    decision = RedBarV2DirectionDecision(
        event_type="INITIAL_BULLISH_ALIGNMENT",
        state="CONFIRMED_BULLISH",
        direction="BULLISH",
        option_side="CE",
        entry_type="INITIAL",
        trend_strength="CONFIRMED",
        context_timestamp=None,
        reference_timestamp=None,
        close_price=None,
        reason="test",
    )
    # rsi is informational -> defaults to True
    assert decision.rsi_aligned is True
    # redbar_vwap_aligned defaults to True (gate passes)
    assert decision.redbar_vwap_aligned is True
    # vwap_aligned and midpoint_aligned also default to True
    assert decision.vwap_aligned is True
    assert decision.midpoint_aligned is True


def test_pcr_informational_audit_row_renders_both_values():
    """When the user opens section 1, the new PCR audit row shows
    both the current 5m PCR and the morning fixed-level PCR."""
    from red_bar_lab.ui import live_cadence as lc

    captured: list = []

    class _St:
        def caption(self, text, *args, **kwargs):
            captured.append(text)

        def expander(self, *args, **kwargs):
            class _C:
                def __enter__(s):
                    return s

                def __exit__(s, *a):
                    return False

            return _C()

        def markdown(self, *args, **kwargs):
            return None

    rows = [
        {
            "process_name": "red_bar_v2_strategy",
            "step_name": "admission_decision",
            "status": "OK",
            "artifacts": {
                "event_type": "INITIAL_DISPLACEMENT",
                "direction": "BULLISH",
                "option_side": "CE",
                "entry_type": "BREAKOUT",
                "trend_strength": "STRONG",
                "outcome": "True",
                "candidate_score": 82,
                "reason": "5m closed above VWAP with RSI=62.4",
            },
        },
        {
            "process_name": "red_bar_v2_strategy",
            "step_name": "check:pcr_informational",
            "status": "OK",
            "artifacts": {
                "passed": True,
                "current_pcr": 0.85,
                "morning_pcr": 0.92,
                "shift": -0.07,
            },
        },
    ]

    class _Db:
        def read_run_evidence(self, *, run_id):
            return rows

    import red_bar_lab.ui.live_cadence as lc_module
    saved = lc_module._get_database_handle
    lc_module._get_database_handle = lambda st: _Db()
    try:
        lc.render_strategy_engine_audit(_St(), run_id="rid-1")
    finally:
        lc_module._get_database_handle = saved
    captions = " ".join(captured)
    assert "PCR (informational)" in captions or "pcr_informational" in captions


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
