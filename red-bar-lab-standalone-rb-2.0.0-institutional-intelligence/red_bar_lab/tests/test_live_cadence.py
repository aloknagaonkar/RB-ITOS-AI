from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

import red_bar_lab.ui.live_cadence as lc  # noqa: F401  (imported for module-level coverage)
from red_bar_lab.ui.live_cadence import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    POLL_INTERVAL_KEY,
    POLL_INTERVAL_OPTIONS,
    UpstreamCadenceStatus,
    _resolve_status_and_reason,
    detect_new_signal,
    init_live_session_state,
    record_follow,
    record_poll_completed,
    record_step_timing,
    reset_step_timings,
    format_timing_caption,
    read_orchestrator_cadence,
    read_paper_monitor_cadence,
)


@dataclass
class FakeSessionState:
    _data: dict = field(default_factory=dict)

    def __contains__(self, key):
        return key in self._data

    def __setitem__(self, key, value):
        self._data[key] = value

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)


@dataclass
class FakeSt:
    session_state: Any = field(default_factory=FakeSessionState)


def _st_with_state(**state) -> FakeSt:
    st = FakeSt()
    for key, value in state.items():
        st.session_state[key] = value
    return st


def test_init_live_session_state_sets_defaults():
    st = FakeSt()
    init_live_session_state(st)
    assert st.session_state[POLL_INTERVAL_KEY] == DEFAULT_POLL_INTERVAL_SECONDS
    assert st.session_state["live_cadence_polls_since_start"] == 0
    assert st.session_state["live_cadence_last_poll_at"] is None
    assert st.session_state["live_cadence_last_seen_signal_id"] is None
    assert st.session_state["live_cadence_step_timings"] == {}


def test_init_live_session_state_preserves_existing_values():
    st = _st_with_state(
        **{POLL_INTERVAL_KEY: 10, "live_cadence_polls_since_start": 5}
    )
    init_live_session_state(st)
    assert st.session_state[POLL_INTERVAL_KEY] == 10
    assert st.session_state["live_cadence_polls_since_start"] == 5


def test_record_poll_completed_increments_counter_and_sets_timestamp():
    st = FakeSt()
    record_poll_completed(st)
    assert st.session_state["live_cadence_polls_since_start"] == 1
    record_poll_completed(st)
    assert st.session_state["live_cadence_polls_since_start"] == 2
    assert st.session_state["live_cadence_last_poll_at"] is not None


def test_detect_new_signal_returns_none_when_unchanged():
    st = _st_with_state(**{"live_cadence_last_seen_signal_id": "RBV2-1"})
    result = detect_new_signal(st, current_signal_id="RBV2-1")
    assert result is None


def test_detect_new_signal_returns_new_id_on_change():
    st = _st_with_state(**{"live_cadence_last_seen_signal_id": "RBV2-1"})
    result = detect_new_signal(st, current_signal_id="RBV2-2")
    assert result == "RBV2-2"
    assert st.session_state["live_cadence_last_seen_signal_id"] == "RBV2-2"


def test_detect_new_signal_returns_none_for_empty_input():
    st = FakeSt()
    assert detect_new_signal(st, current_signal_id=None) is None


def test_record_follow_sets_followed_signal_id():
    st = FakeSt()
    record_follow(st, "RBV2-99")
    assert st.session_state["live_cadence_last_followed_signal_id"] == "RBV2-99"
    assert st.session_state["live_cadence_last_follow_flash"] is not None


def test_record_step_timing_keeps_history_per_step():
    st = FakeSt()
    record_step_timing(st, "step_a", read_ms=1.0, render_ms=2.0)
    record_step_timing(st, "step_b", read_ms=0.5, render_ms=1.5)
    timings = st.session_state["live_cadence_step_timings"]
    assert timings["step_a"]["total_ms"] == 3.0
    assert timings["step_b"]["total_ms"] == 2.0


def test_reset_step_timings_clears_all_entries():
    st = FakeSt()
    record_step_timing(st, "step_a", read_ms=1.0, render_ms=2.0)
    reset_step_timings(st)
    assert st.session_state["live_cadence_step_timings"] == {}


def test_format_timing_caption_for_empty_input_returns_empty_string():
    assert format_timing_caption(None) == ""


def test_format_timing_caption_includes_total_read_and_render():
    caption = format_timing_caption(
        {"read_ms": 1.0, "render_ms": 2.0, "total_ms": 3.0, "at": "now"}
    )
    assert "3 ms" in caption
    assert "1 ms" in caption
    assert "2 ms" in caption
    assert "⚡" in caption


def test_poll_interval_options_includes_default():
    values = [option[1] for option in POLL_INTERVAL_OPTIONS]
    assert DEFAULT_POLL_INTERVAL_SECONDS in values
    assert 2 in values
    assert 30 in values


def test_read_paper_monitor_cadence_returns_stale_when_no_heartbeat():
    class FakeDb:
        def read_paper_monitor_status(self, monitor_id):
            return {
                "monitor_id": "PAPER-MONITOR",
                "status": "RUNNING",
                "heartbeat_at": None,
                "last_signal_id": "RBV2-1",
                "last_decision": "OPEN",
                "last_error": None,
            }

    cadence = read_paper_monitor_cadence(FakeDb())
    assert cadence.name == "Paper Monitor"
    assert cadence.last_heartbeat_at is None
    assert cadence.seconds_since_heartbeat is None
    assert cadence.last_signal_id == "RBV2-1"
    assert cadence.last_decision == "OPEN"


def test_read_paper_monitor_cadence_handles_db_failure():
    class ExplodingDb:
        def read_paper_monitor_status(self, monitor_id):
            raise RuntimeError("db unavailable")

    cadence = read_paper_monitor_cadence(ExplodingDb())
    assert cadence.last_heartbeat_at is None
    assert cadence.last_signal_id is None


def test_read_orchestrator_cadence_returns_status():
    class FakeDb:
        def read_pipeline_run_status(self, instrument_key, trading_date):
            return {
                "instrument_key": instrument_key,
                "trading_date": trading_date,
                "status": "HEALTHY",
                "message": "OK",
                "updated_at": "2024-01-01T09:00:00+00:00",
            }

        def read_latest_pipeline_run_status(self, instrument_key):
            return None

    cadence = read_orchestrator_cadence(
        FakeDb(), instrument_key="NSE_INDEX|Nifty 50", trading_date="2024-01-01"
    )
    assert cadence.name == "Background Orchestrator"
    assert cadence.last_decision == "HEALTHY"
    assert cadence.last_heartbeat_at is not None


def test_read_orchestrator_cadence_returns_empty_when_no_row():
    class FakeDb:
        def read_pipeline_run_status(self, instrument_key, trading_date):
            return None

        def read_latest_pipeline_run_status(self, instrument_key):
            return None

    cadence = read_orchestrator_cadence(
        FakeDb(), instrument_key="NSE_INDEX|Nifty 50", trading_date="2024-01-01"
    )
    assert cadence.last_heartbeat_at is None
    assert cadence.last_decision is None


def test_read_orchestrator_cadence_falls_back_to_latest_when_today_missing():
    """When no row exists for today but a previous run is on file,
    the panel should show the most recent run as last_success rather
    than as a stale/failed current state."""
    class FakeDb:
        def read_pipeline_run_status(self, instrument_key, trading_date):
            return None

        def read_latest_pipeline_run_status(self, instrument_key):
            return {
                "instrument_key": instrument_key,
                "trading_date": "2026-08-28",
                "status": "HEALTHY",
                "message": "2 confirmed; 2 core eligible; 2 hybrid eligible.",
                "updated_at": "2026-08-28T22:50:24+05:30",
            }

    cadence = read_orchestrator_cadence(
        FakeDb(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-29",
    )
    assert cadence.last_heartbeat_at == "2026-08-28T22:50:24+05:30"
    assert cadence.last_decision == "HEALTHY"
    # Message is a status summary, not an error
    assert cadence.last_error is None
    # Surfaces the last run date and the run summary in success fields
    assert "2026-08-28" in cadence.cadence_label
    assert (
        cadence.last_success_bridge_alignment
        == "2 confirmed; 2 core eligible; 2 hybrid eligible."
    )
    # "today's run has not started yet" is the gentle explanation
    assert (
        cadence.last_success_readiness_reason
        == "today's run has not started yet"
    )


def test_read_orchestrator_cadence_today_row_wins_over_older_row():
    class FakeDb:
        def read_pipeline_run_status(self, instrument_key, trading_date):
            return {
                "instrument_key": instrument_key,
                "trading_date": trading_date,
                "status": "HEALTHY",
                "message": "today's run is healthy",
                "updated_at": "2026-08-29T10:00:00+05:30",
            }

        def read_latest_pipeline_run_status(self, instrument_key):
            return {
                "instrument_key": instrument_key,
                "trading_date": "2026-08-28",
                "status": "HEALTHY",
                "message": "yesterday's run",
                "updated_at": "2026-08-28T22:50:24+05:30",
            }

    cadence = read_orchestrator_cadence(
        FakeDb(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-29",
    )
    # Today's row should be primary
    assert cadence.last_success_bridge_alignment == "today's run is healthy"
    # Cadence label should reflect today's date
    assert "2026-08-29" in cadence.cadence_label


def test_read_orchestrator_cadence_includes_run_duration_and_counts():
    """The orchestrator card should surface how long the last run took
    and how many signals it processed, so it has parity with the Paper
    Monitor's per-stage breakdown."""
    class FakeDb:
        def read_pipeline_run_status(self, instrument_key, trading_date):
            return {
                "instrument_key": instrument_key,
                "trading_date": trading_date,
                "status": "HEALTHY",
                "message": "8 confirmed; 8 core eligible; 7 hybrid eligible.",
                "updated_at": "2026-08-29T22:50:24+05:30",
                "confirmed_count": 8,
                "core_eligible_count": 8,
                "hybrid_eligible_count": 7,
                "run_duration_ms": 4250.5,
                "started_at": "2026-08-29T22:50:20+05:30",
            }

        def read_latest_pipeline_run_status(self, instrument_key):
            return None

    cadence = read_orchestrator_cadence(
        FakeDb(),
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-29",
    )
    assert cadence.run_duration_ms == 4250.5
    assert cadence.confirmed_count == 8
    assert cadence.core_eligible_count == 8
    assert cadence.hybrid_eligible_count == 7
    assert cadence.started_at == "2026-08-29T22:50:20+05:30"


def test_build_last_success_lines_renders_orchestrator_duration_and_counts():
    from red_bar_lab.ui.live_cadence import _build_last_success_lines

    cadence = UpstreamCadenceStatus(
        name="Background Orchestrator",
        cadence_label="last run on 2026-08-28",
        last_heartbeat_at="2026-08-28T22:50:24+05:30",
        seconds_since_heartbeat=44000.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="HEALTHY",
        last_error=None,
        total_ms=4250.5,
        stages={},
        last_success_at="2026-08-28T22:50:24+05:30",
        last_success_decision="HEALTHY",
        seconds_since_last_success=44000.0,
        last_success_underlying_status="2026-08-28",
        last_success_bridge_alignment="8 confirmed; 8 core eligible; 7 hybrid eligible.",
        run_duration_ms=4250.5,
        confirmed_count=8,
        core_eligible_count=8,
        hybrid_eligible_count=7,
        started_at="2026-08-28T22:50:20+05:30",
    )
    lines = _build_last_success_lines(cadence)
    # Subtitle-style "last run trading date"
    assert any("last run trading date: 2026-08-28" in line for line in lines)
    # Existing summary line
    assert any(
        "8 confirmed; 8 core eligible; 7 hybrid eligible." in line
        for line in lines
    )
    # New: duration + counts in one compact line
    duration_line = next(
        (line for line in lines if "ran for" in line and "ms" not in line),
        None,
    )
    assert duration_line is not None
    assert "4.3s" in duration_line
    assert "8 confirmed" in duration_line
    assert "8 core" in duration_line
    assert "7 hybrid" in duration_line
    # Started-at line
    assert any("started at: 2026-08-28T22:50:20" in line for line in lines)


def test_read_paper_monitor_cadence_sets_dependency_metadata():
    """The Paper Monitor should advertise that it feeds the orchestrator."""
    class FakeDb:
        def read_paper_monitor_status(self, monitor_id):
            return None

    cadence = read_paper_monitor_cadence(FakeDb())
    assert cadence.dependency == "upstream-of:orchestrator"
    assert cadence.dependency_label is not None
    assert "5s upstream" in cadence.dependency_label


def test_read_orchestrator_cadence_sets_dependency_metadata():
    class FakeDb:
        def read_pipeline_run_status(self, instrument_key, trading_date):
            return None

        def read_latest_pipeline_run_status(self, instrument_key):
            return None

    cadence = read_orchestrator_cadence(
        FakeDb(), instrument_key="NSE_INDEX|Nifty 50", trading_date="2026-08-29"
    )
    assert cadence.dependency == "downstream-of:paper-monitor"
    assert cadence.dependency_label is not None
    assert "1m upstream" in cadence.dependency_label


def test_render_dependency_strip_renders_arrows_and_helps(monkeypatch):
    """The dependency strip helper should emit captions for both arrows
    and tooltips (helps) for the three components."""

    class _Column:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _FakeSt:
        def __init__(self):
            self.markdown_calls = []
            self.caption_calls = []

        def columns(self, _spec):
            return [_Column(), _Column(), _Column()]

        def markdown(self, text, help=None):
            self.markdown_calls.append((text, help))

        def caption(self, text):
            self.caption_calls.append(text)

    st = _FakeSt()
    lc._render_dependency_strip(st)
    # Three components should have been rendered as markdown
    names = [str(call[0]) for call in st.markdown_calls]
    assert any("Paper Monitor" in n for n in names)
    assert any("Background Orchestrator" in n for n in names)
    assert any("Page Polling" in n for n in names)
    # The two arrow captions should mention the next component and a label
    captions = [str(c) for c in st.caption_calls]
    assert any(
        "feeds → Background Orchestrator" in c for c in captions
    ), "expected paper-monitor → orchestrator arrow caption"
    assert any(
        "feeds → Page Polling" in c for c in captions
    ), "expected orchestrator → page-polling arrow caption"
    # All three components should have a help/tooltip
    helps = [str(call[1]) for call in st.markdown_calls if call[1]]
    assert any("5s upstream" in h for h in helps)
    assert any("Background Orchestrator" in h for h in helps)
    assert any("page poll loop" in h.lower() or "user-config" in h.lower() for h in helps)


def test_dependency_labels_cover_all_three_cards():
    """The flow metadata should be wired up on every card so the
    dependency strip has something to render for each one."""
    from red_bar_lab.ui.live_cadence import _FLOW_HELP, _FLOW_ORDER

    # The strip references all three names
    assert set(_FLOW_ORDER) == {
        "Paper Monitor",
        "Background Orchestrator",
        "Page Polling",
    }
    # Each one has a help tooltip
    for name in _FLOW_ORDER:
        assert name in _FLOW_HELP
        assert _FLOW_HELP[name], f"empty help for {name}"


def test_upstream_cadence_dataclass_is_frozen():
    status = UpstreamCadenceStatus(
        name="Test",
        cadence_label="1s",
        last_heartbeat_at=None,
        seconds_since_heartbeat=None,
        is_stale=False,
        last_signal_id=None,
        last_decision=None,
        last_error=None,
        total_ms=None,
        stages={},
    )
    with pytest.raises(Exception):
        status.name = "Other"  # type: ignore[misc]


def test_resolve_status_and_reason_for_no_heartbeat_explains_waiting():
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at=None,
        seconds_since_heartbeat=None,
        is_stale=False,
        last_signal_id=None,
        last_decision=None,
        last_error=None,
        total_ms=None,
        stages={},
    )
    status, reason, hint = _resolve_status_and_reason(cadence)
    assert status == "NO DATA"
    assert "no heartbeat" in reason.lower()
    assert "5s upstream loop" in reason
    assert hint is None


def test_resolve_status_and_reason_for_stale_explains_silence():
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T09:00:00+00:00",
        seconds_since_heartbeat=120.0,
        is_stale=True,
        last_signal_id=None,
        last_decision="OPEN",
        last_error=None,
        total_ms=None,
        stages={},
    )
    status, reason, hint = _resolve_status_and_reason(cadence)
    assert status == "STALE"
    assert "silent" in reason.lower() or "120" in reason
    assert hint is None


def test_resolve_status_and_reason_for_block_decision_explains_not_page_fault():
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T09:00:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id="RBV2-1",
        last_decision="BLOCK",
        last_error=None,
        total_ms=None,
        stages={},
    )
    status, reason, hint = _resolve_status_and_reason(cadence)
    assert status == "BLOCK"
    assert "not a page fault" in reason.lower() or "could not act" in reason.lower()
    assert hint is None


def test_resolve_status_and_reason_for_open_decision_explains_follow():
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T09:00:00+00:00",
        seconds_since_heartbeat=1.0,
        is_stale=False,
        last_signal_id="RBV2-99",
        last_decision="OPEN",
        last_error=None,
        total_ms=None,
        stages={},
    )
    status, reason, hint = _resolve_status_and_reason(cadence)
    assert status == "OPEN"
    assert "auto-follow" in reason.lower() or "new signal" in reason.lower()
    assert hint is None


def test_resolve_status_and_reason_for_healthy_decision_is_quiet():
    cadence = UpstreamCadenceStatus(
        name="Background Orchestrator",
        cadence_label="60s upstream loop",
        last_heartbeat_at="2024-01-01T09:00:00+00:00",
        seconds_since_heartbeat=10.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="HEALTHY",
        last_error=None,
        total_ms=None,
        stages={},
    )
    status, reason, hint = _resolve_status_and_reason(cadence)
    assert status == "HEALTHY"
    assert "healthy" in reason.lower()
    assert hint is None


def test_resolve_status_and_reason_for_suspended_is_not_a_failure():
    """ENTRY_SUSPENDED is an intentional circuit-breaker state, not a failure."""
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T09:00:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id="RBV2-1",
        last_decision="ENTRY_SUSPENDED",
        last_error="ENTRY_SUSPENDED:UNDERLYING_FEED_MISSING",
        total_ms=None,
        stages={},
    )
    status, reason, hint = _resolve_status_and_reason(cadence)
    assert status == "SUSPENDED"
    assert "circuit-breaker" in reason.lower() or "intentionally" in reason.lower()
    assert hint is not None
    assert "UNDERLYING_FEED_MISSING" in hint
    assert "NIFTY 50" in hint


def test_resolve_status_and_reason_for_suspended_process_ownership():
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T09:00:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="ENTRY_SUSPENDED",
        last_error="ENTRY_SUSPENDED:PROCESS_OWNERSHIP_UNAVAILABLE",
        total_ms=None,
        stages={},
    )
    status, _reason, hint = _resolve_status_and_reason(cadence)
    assert status == "SUSPENDED"
    assert hint is not None
    assert "PROCESS_OWNERSHIP_UNAVAILABLE" in hint
    assert "another process" in hint.lower() or "owns" in hint.lower()


def test_resolve_status_and_reason_for_unknown_error_reports_failed():
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T09:00:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id="RBV2-1",
        last_decision="OPEN",
        last_error="Traceback: ValueError: something exploded",
        total_ms=None,
        stages={},
    )
    status, reason, hint = _resolve_status_and_reason(cadence)
    assert status == "FAILED"
    assert "error" in reason.lower()
    assert hint is None


def test_resolve_status_and_reason_for_suspended_with_unknown_reason_code():
    """A reason code we don't have a human hint for should still surface."""
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T09:00:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="ENTRY_SUSPENDED",
        last_error="ENTRY_SUSPENDED:WHATEVER_NEW_REASON_CODE",
        total_ms=None,
        stages={},
    )
    status, _reason, hint = _resolve_status_and_reason(cadence)
    assert status == "SUSPENDED"
    assert hint is not None
    assert "WHATEVER_NEW_REASON_CODE" in hint


def test_format_last_check_returns_none_without_heartbeat():
    from red_bar_lab.ui.live_cadence import _format_last_check

    cadence = UpstreamCadenceStatus(
        name="X",
        cadence_label="5s",
        last_heartbeat_at=None,
        seconds_since_heartbeat=None,
        is_stale=False,
        last_signal_id=None,
        last_decision=None,
        last_error=None,
        total_ms=None,
        stages={},
    )
    assert _format_last_check(cadence) is None


def test_format_last_check_includes_iso_timestamp():
    from red_bar_lab.ui.live_cadence import _format_last_check

    cadence = UpstreamCadenceStatus(
        name="X",
        cadence_label="5s",
        last_heartbeat_at="2024-01-01T09:30:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id=None,
        last_decision=None,
        last_error=None,
        total_ms=None,
        stages={},
    )
    line = _format_last_check(cadence)
    assert line is not None
    assert "Last feed check" in line
    assert "2024-01-01T09:30:00" in line


def test_format_stage_timings_renames_known_stages_and_skips_total():
    from red_bar_lab.ui.live_cadence import _format_stage_timings

    cadence = UpstreamCadenceStatus(
        name="X",
        cadence_label="5s",
        last_heartbeat_at="2024-01-01T09:30:00+00:00",
        seconds_since_heartbeat=1.0,
        is_stale=False,
        last_signal_id=None,
        last_decision=None,
        last_error=None,
        total_ms=42.0,
        stages={
            "readiness": 12.0,
            "v2_evaluation": 18.0,
            "automation": 7.0,
            "total": 42.0,
            "new_future_stage": 1.0,
        },
    )
    lines = _format_stage_timings(cadence)
    assert any("readiness" in line and "12 ms" in line for line in lines)
    assert any("v2 evaluation" in line and "18 ms" in line for line in lines)
    assert any("automation" in line and "7 ms" in line for line in lines)
    assert any("new_future_stage" in line for line in lines)
    # total stage is excluded from the per-stage breakdown
    assert not any(line.startswith("  · total") for line in lines)


def test_format_total_with_breakdown_includes_stage_sum():
    from red_bar_lab.ui.live_cadence import _format_total_with_breakdown

    cadence = UpstreamCadenceStatus(
        name="X",
        cadence_label="5s",
        last_heartbeat_at="2024-01-01T09:30:00+00:00",
        seconds_since_heartbeat=1.0,
        is_stale=False,
        last_signal_id=None,
        last_decision=None,
        last_error=None,
        total_ms=42.0,
        stages={"a": 10.0, "b": 12.0, "total": 42.0},
    )
    line = _format_total_with_breakdown(cadence)
    assert line is not None
    assert "42 ms total" in line
    assert "22 ms in stages" in line


def test_format_total_with_breakdown_handles_missing_stages():
    from red_bar_lab.ui.live_cadence import _format_total_with_breakdown

    cadence = UpstreamCadenceStatus(
        name="X",
        cadence_label="5s",
        last_heartbeat_at="2024-01-01T09:30:00+00:00",
        seconds_since_heartbeat=1.0,
        is_stale=False,
        last_signal_id=None,
        last_decision=None,
        last_error=None,
        total_ms=42.0,
        stages={},
    )
    line = _format_total_with_breakdown(cadence)
    assert line is not None
    assert "42 ms total" in line
    assert "in stages" not in line


def test_build_detail_lines_orders_last_check_total_then_stages():
    from red_bar_lab.ui.live_cadence import _build_detail_lines

    cadence = UpstreamCadenceStatus(
        name="X",
        cadence_label="5s",
        last_heartbeat_at="2024-01-01T09:30:00+00:00",
        seconds_since_heartbeat=1.0,
        is_stale=False,
        last_signal_id=None,
        last_decision=None,
        last_error=None,
        total_ms=42.0,
        stages={"readiness": 12.0, "v2_evaluation": 18.0, "total": 42.0},
    )
    lines = _build_detail_lines(cadence)
    assert lines
    assert lines[0].startswith("Last feed check")
    assert any("ms total" in line for line in lines)
    # stages come after the totals line
    first_stage_index = next(
        i for i, line in enumerate(lines) if line.startswith("  · ")
    )
    last_check_index = 0
    total_index = next(
        i for i, line in enumerate(lines) if "ms total" in line
    )
    assert last_check_index < total_index < first_stage_index


def test_build_last_success_lines_empty_when_no_success_recorded():
    from red_bar_lab.ui.live_cadence import _build_last_success_lines

    cadence = UpstreamCadenceStatus(
        name="X",
        cadence_label="5s",
        last_heartbeat_at="2024-01-01T09:30:00+00:00",
        seconds_since_heartbeat=1.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="ENTRY_SUSPENDED",
        last_error="ENTRY_SUSPENDED:UNDERLYING_FEED_MISSING",
        total_ms=12.0,
        stages={"readiness": 12.0},
        last_success_at=None,
    )
    assert _build_last_success_lines(cadence) == []


def test_build_last_success_lines_includes_decision_signal_total_and_stages():
    from red_bar_lab.ui.live_cadence import _build_last_success_lines

    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s",
        last_heartbeat_at="2024-01-01T09:32:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="ENTRY_SUSPENDED",
        last_error="ENTRY_SUSPENDED:UNDERLYING_FEED_MISSING",
        total_ms=12.0,
        stages={"readiness": 12.0},
        last_success_at="2024-01-01T09:30:00+00:00",
        last_success_decision="OPEN",
        last_success_signal_id="RBV2-LAST-OK",
        last_success_total_ms=85.0,
        last_success_stages={
            "readiness": 12.0,
            "v2_evaluation": 30.0,
            "automation": 35.0,
            "total": 85.0,
        },
        seconds_since_last_success=120.0,
    )
    lines = _build_last_success_lines(cadence)
    assert lines
    assert any("Last successful cycle" in line for line in lines)
    assert any("120s ago" in line for line in lines)
    assert any("OPEN" in line and "decision" in line for line in lines)
    assert any("RBV2-LAST-OK" in line for line in lines)
    assert any("85 ms" in line and "77 ms in stages" in line for line in lines)
    # Stages are present, total is excluded
    assert any("readiness" in line and "12 ms" in line for line in lines)
    assert any("v2 evaluation" in line and "30 ms" in line for line in lines)
    assert any("automation" in line and "35 ms" in line for line in lines)
    assert not any(line.startswith("  · total") for line in lines)


def test_build_last_success_lines_includes_feed_health_details():
    from red_bar_lab.ui.live_cadence import _build_last_success_lines

    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s",
        last_heartbeat_at="2024-01-01T09:32:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="ENTRY_SUSPENDED",
        last_error="ENTRY_SUSPENDED:UNDERLYING_FEED_MISSING",
        total_ms=None,
        stages={},
        last_success_at="2024-01-01T09:30:00+00:00",
        last_success_decision="OPEN",
        last_success_underlying_status="CANDLE_READY",
        last_success_futures_status="READY",
        last_success_candle_timestamp="2024-01-01T09:29:55+00:00",
        last_success_candle_age_seconds=5.0,
        last_success_readiness_ms=12.0,
        seconds_since_last_success=120.0,
    )
    lines = _build_last_success_lines(cadence)
    assert any("underlying feed" in line and "CANDLE_READY" in line for line in lines)
    assert any("futures feed" in line and "READY" in line for line in lines)
    assert any(
        "latest underlying candle fetched" in line
        and "2024-01-01T09:29:55" in line
        and "was 5.0s old at fetch" in line
        for line in lines
    )
    assert any("readiness check" in line and "12 ms" in line for line in lines)


def test_resolve_status_and_reason_uses_never_seen_hint_for_underlying_missing():
    """When the monitor has never recorded a successful feed check, the
    SUSPENDED hint should make that clear instead of the optimistic
    'will resume on its own' wording."""
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T09:00:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="ENTRY_SUSPENDED",
        last_error="ENTRY_SUSPENDED:UNDERLYING_FEED_MISSING",
        total_ms=None,
        stages={},
        last_success_at=None,
    )
    status, reason, hint = _resolve_status_and_reason(cadence)
    assert status == "SUSPENDED"
    assert "no successful readiness check" in reason.lower()
    assert hint is not None
    assert "no successful feed check has been recorded yet" in hint
    assert "will resume on its own" not in hint


def test_resolve_status_and_reason_uses_resume_hint_when_success_exists():
    """When the monitor has had a successful feed check before, the
    SUSPENDED hint should use the 'will resume' wording."""
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T09:10:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="ENTRY_SUSPENDED",
        last_error="ENTRY_SUSPENDED:UNDERLYING_FEED_MISSING",
        total_ms=None,
        stages={},
        last_success_at="2024-01-01T09:00:00+00:00",
        last_success_underlying_status="CANDLE_READY",
    )
    status, reason, hint = _resolve_status_and_reason(cadence)
    assert status == "SUSPENDED"
    assert "circuit-breaker" in reason.lower()
    assert hint is not None
    assert "will resume on its own" in hint
    assert "no successful feed check has been recorded yet" not in hint


def test_read_paper_monitor_cadence_populates_feed_health_fields():
    class FakeDb:
        def read_paper_monitor_status(self, monitor_id):
            return {
                "monitor_id": monitor_id,
                "status": "DEGRADED",
                "heartbeat_at": "2024-01-01T09:32:00+00:00",
                "last_signal_id": "RBV2-NOW",
                "last_decision": "ENTRY_SUSPENDED",
                "last_error": "ENTRY_SUSPENDED:UNDERLYING_FEED_MISSING",
                "cycle_timings_ms": {"readiness": 12.0, "total": 12.0},
                "last_success_at": "2024-01-01T09:30:00+00:00",
                "last_success_decision": "OPEN",
                "last_success_signal_id": "RBV2-LAST-OK",
                "last_success_total_ms": 85.0,
                "last_success_stages_json": (
                    '{"readiness": 12, "v2_evaluation": 30, "total": 85}'
                ),
                "last_success_underlying_status": "CANDLE_READY",
                "last_success_readiness_ms": 12.0,
                "last_success_futures_status": "READY",
                "last_success_candle_timestamp": "2024-01-01T09:29:55+00:00",
                "last_success_candle_age_seconds": 5.0,
            }

    cadence = read_paper_monitor_cadence(FakeDb())
    assert cadence.last_success_underlying_status == "CANDLE_READY"
    assert cadence.last_success_readiness_ms == 12.0
    assert cadence.last_success_futures_status == "READY"
    assert cadence.last_success_candle_timestamp == "2024-01-01T09:29:55+00:00"
    assert cadence.last_success_candle_age_seconds == 5.0
    assert cadence.last_decision == "ENTRY_SUSPENDED"


def test_read_paper_monitor_cadence_populates_candle_ohlcv_fields():
    class FakeDb:
        def read_paper_monitor_status(self, monitor_id):
            return {
                "monitor_id": monitor_id,
                "status": "DEGRADED",
                "heartbeat_at": "2024-01-01T09:32:00+00:00",
                "last_signal_id": None,
                "last_decision": "ENTRY_SUSPENDED",
                "last_error": "ENTRY_SUSPENDED:UNDERLYING_FEED_MISSING",
                "last_success_at": "2024-01-01T09:30:00+00:00",
                "last_success_underlying_status": "CANDLE_READY",
                "last_success_bridge_alignment": "CONSISTENT",
                "last_success_readiness_reason": "FRESH",
            }

    cadence = read_paper_monitor_cadence(FakeDb())
    assert cadence.last_success_bridge_alignment == "CONSISTENT"
    assert cadence.last_success_readiness_reason == "FRESH"
    assert cadence.last_success_underlying_status == "CANDLE_READY"


def test_resolve_status_and_reason_market_closed_uses_friendly_hint():
    """When the monitor says the market is closed, the SUSPENDED hint
    should say so plainly and not as a failure."""
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T09:00:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="MARKET_CLOSED",
        last_error=None,
        total_ms=None,
        stages={},
        last_success_at="2024-01-01T03:45:00+00:00",
    )
    status, reason, hint = _resolve_status_and_reason(cadence)
    assert status == "SUSPENDED"
    assert hint is not None
    assert "market is closed" in hint.lower()
    assert "expected state" in hint.lower()
    assert "missing or stale" not in hint.lower()


def test_resolve_status_and_reason_market_closed_never_seen_uses_calmer_wording():
    """If the market has been closed the whole time we've been watching,
    the hint should make that clear without alarming language."""
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T09:00:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="MARKET_CLOSED",
        last_error=None,
        total_ms=None,
        stages={},
        last_success_at=None,
    )
    status, _reason, hint = _resolve_status_and_reason(cadence)
    assert status == "SUSPENDED"
    assert hint is not None
    assert "market is closed" in hint.lower()
    assert "expected" in hint.lower()
    assert "circuit-breaker" not in hint.lower()


def test_resolve_status_and_reason_outside_entry_hours_is_friendly():
    cadence = UpstreamCadenceStatus(
        name="Paper Monitor",
        cadence_label="5s upstream loop",
        last_heartbeat_at="2024-01-01T08:00:00+00:00",
        seconds_since_heartbeat=2.0,
        is_stale=False,
        last_signal_id=None,
        last_decision="OUTSIDE_AUTOMATIC_ENTRY_HOURS",
        last_error=None,
        total_ms=None,
        stages={},
        last_success_at=None,
    )
    status, _reason, hint = _resolve_status_and_reason(cadence)
    assert status == "SUSPENDED"
    assert hint is not None
    assert "outside automatic entry hours" in hint.lower()
    # The never-seen variant mentions this is expected before the trading
    # window opens, rather than the alarming "circuit-breaker" wording.
    assert "expected" in hint.lower()
    assert "circuit-breaker" not in hint.lower()


def test_read_paper_monitor_cadence_populates_last_success_fields():
    class FakeDb:
        def read_paper_monitor_status(self, monitor_id):
            return {
                "monitor_id": monitor_id,
                "status": "DEGRADED",
                "heartbeat_at": "2024-01-01T09:32:00+00:00",
                "last_signal_id": "RBV2-NOW",
                "last_decision": "ENTRY_SUSPENDED",
                "last_error": "ENTRY_SUSPENDED:UNDERLYING_FEED_MISSING",
                "cycle_timings_ms": {
                    "readiness": 12.0,
                    "total": 12.0,
                },
                "last_success_at": "2024-01-01T09:30:00+00:00",
                "last_success_decision": "OPEN",
                "last_success_signal_id": "RBV2-LAST-OK",
                "last_success_total_ms": 85.0,
                "last_success_stages_json": (
                    '{"readiness": 12, "v2_evaluation": 30, "automation": 35, "total": 85}'
                ),
            }

    cadence = read_paper_monitor_cadence(FakeDb())
    assert cadence.last_success_at == "2024-01-01T09:30:00+00:00"
    assert cadence.last_success_decision == "OPEN"
    assert cadence.last_success_signal_id == "RBV2-LAST-OK"
    assert cadence.last_success_total_ms == 85.0
    assert cadence.last_success_stages is not None
    assert cadence.last_success_stages["v2_evaluation"] == 30.0
    # current cycle should still be SUSPENDED, not the success state
    assert cadence.last_decision == "ENTRY_SUSPENDED"


def test_parse_success_stages_handles_already_parsed_dict():
    from red_bar_lab.ui.live_cadence import _parse_success_stages

    row = {"last_success_stages_json": {"readiness": 12.0, "total": 42.0}}
    parsed = _parse_success_stages(row)
    assert parsed == {"readiness": 12.0, "total": 42.0}


def test_parse_success_stages_returns_none_for_invalid_json():
    from red_bar_lab.ui.live_cadence import _parse_success_stages

    assert _parse_success_stages({"last_success_stages_json": "not json"}) is None
    assert _parse_success_stages({"last_success_stages_json": None}) is None
    assert _parse_success_stages(None) is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
