"""Tests for the three new observability features:
- retention / cleanup of process_evidence
- per-process last-error duration surfaced on the cadence panel
- 12 V2 lifecycle step renderers wrapping with_step_evidence
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _init_db(path: Path):
    from red_bar_lab.storage.database import RedBarDatabase

    return RedBarDatabase(path)


def test_cleanup_process_evidence_removes_old_rows(tmp_path: Path):
    db = _init_db(tmp_path / "test.db")
    rid = "test-run-1"
    # Insert one row that's recent and one that's old by setting its
    # started_at directly to a long-ago timestamp.
    step_id = db.write_step_evidence(
        process_name="x",
        run_id=rid,
        step_name="recent",
        parent_step=None,
        started_at=datetime.now(timezone.utc).isoformat(),
        status="OK",
    )
    db.update_step_evidence(
        step_id=step_id,
        completed_at=datetime.now(timezone.utc).isoformat(),
        status="OK",
        duration_ms=1.0,
    )
    old_step_id = db.write_step_evidence(
        process_name="x",
        run_id=rid,
        step_name="old",
        parent_step=None,
        started_at="2020-01-01T00:00:00+00:00",
        status="OK",
    )
    db.update_step_evidence(
        step_id=old_step_id,
        completed_at="2020-01-01T00:00:00+00:00",
        status="OK",
        duration_ms=1.0,
    )
    deleted = db.cleanup_process_evidence(retention_days=7)
    assert deleted == 1
    rows = db.read_step_timelines(limit_per_step=10)
    all_steps = [s for r in rows.values() for s in r]
    step_names = {r["step_name"] for r in all_steps}
    assert "recent" in step_names
    assert "old" not in step_names


def test_maybe_cleanup_is_self_throttling(tmp_path: Path):
    """Two calls within 24h should only delete once."""
    from red_bar_lab.observability.cleanup import maybe_cleanup_process_evidence

    db = _init_db(tmp_path / "test.db")
    # Insert one old row.
    old_step_id = db.write_step_evidence(
        process_name="x",
        run_id="rid",
        step_name="old",
        parent_step=None,
        started_at="2020-01-01T00:00:00+00:00",
        status="OK",
    )
    db.update_step_evidence(
        step_id=old_step_id,
        completed_at="2020-01-01T00:00:00+00:00",
        status="OK",
        duration_ms=1.0,
    )
    # First call: deletes 1, writes last-cleanup.
    deleted_1 = maybe_cleanup_process_evidence(db)
    assert deleted_1 == 1
    # Second call: should be self-throttled to 0.
    deleted_2 = maybe_cleanup_process_evidence(db)
    assert deleted_2 == 0
    # The last-cleanup timestamp is recorded.
    last = db.read_last_cleanup_at()
    assert last is not None


def test_read_latest_error_per_process_returns_most_recent_only(tmp_path: Path):
    db = _init_db(tmp_path / "test.db")
    # Two errors for "x", two for "y".
    for proc, step in [("x", "a"), ("x", "b"), ("y", "c"), ("y", "d")]:
        sid = db.write_step_evidence(
            process_name=proc,
            run_id="rid",
            step_name=step,
            parent_step=None,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="ERROR",
        )
        db.update_step_evidence(
            step_id=sid,
            completed_at=datetime.now(timezone.utc).isoformat(),
            status="ERROR",
            duration_ms=1.0,
            error_message=f"{step} failed",
        )
    rows = db.read_latest_error_per_process()
    by_proc = {r["process_name"]: r for r in rows}
    assert set(by_proc.keys()) == {"x", "y"}
    # One row per process, with error_age_seconds populated.
    for r in rows:
        assert "error_age_seconds" in r
        assert r["error_age_seconds"] >= 0


def test_render_error_banner_renders_st_error_with_duration():
    from red_bar_lab.ui import live_cadence as lc

    @dataclass
    class _St:
        error_calls: list = field(default_factory=list)

        def error(self, msg):
            self.error_calls.append(msg)

    st = _St()
    rows = [
        {
            "process_name": "market_collector",
            "step_name": "candle_fetch_online",
            "error_message": "Upstox 503",
            "error_age_seconds": 123.0,
        },
        {
            "process_name": "canonical_shadow",
            "step_name": "section_1_signal_discovery",
            "error_message": "reference missing",
            "error_age_seconds": 7200.0,  # 2 hours
        },
    ]

    class _FakeDb:
        def read_latest_error_per_process(self):
            return rows

    lc._render_error_banner_st = None  # ensure module-level state
    original = lc._get_database_handle

    def fake_get(st_arg):
        return _FakeDb()

    lc._get_database_handle = fake_get
    try:
        lc._render_error_banner(st)
    finally:
        lc._get_database_handle = original
    assert len(st.error_calls) == 2
    assert "market_collector" in st.error_calls[0]
    assert "2m" in st.error_calls[0]  # 123s -> "2m"
    assert "2.0h" in st.error_calls[1]  # 7200s -> "2.0h"


def test_render_lifecycle_all_with_evidence_writes_step_rows():
    """When ``process_name`` and ``database`` are passed, each step
    render writes one ``process_evidence`` row."""
    from red_bar_lab.ui.lifecycle_stepper import (
        LifecycleContext,
        make_step,
        render_lifecycle_all,
    )

    class _FakeSt:
        caption_calls: list = field(default_factory=list)
        markdown_calls: list = field(default_factory=list)

        def caption(self, *args, **kwargs):
            self.caption_calls.append((args, kwargs))
            return None

        def markdown(self, *args, **kwargs):
            self.markdown_calls.append((args, kwargs))
            return None

        def divider(self):
            return None

        def expander(self, label, expanded=True):
            class _C:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *a):
                    return False

            return _C()

        def error(self, *args, **kwargs):
            return None

    _FakeSt()

    @dataclass
    class _FakeDb:
        rows: list = field(default_factory=list)
        _next_id: int = 1

        def write_step_evidence(self, **kwargs):
            sid = self._next_id
            self._next_id += 1
            self.rows.append({"id": sid, **kwargs})
            return sid

        def update_step_evidence(self, **kwargs):
            for r in self.rows:
                if r["id"] == kwargs["step_id"]:
                    r.update({k: v for k, v in kwargs.items() if k != "step_id"})
                    return

    db = _FakeDb()
    run_id = "test-rid-001"

    def _step_one(st_arg, context):
        st_arg.caption("step one body")

    def _step_two(st_arg, context):
        st_arg.caption("step two body")

    steps = [
        make_step(
            step_id="signal_discovery",
            title="Reference Readiness",
            description="Section 1",
            renderer=_step_one,
        ),
        make_step(
            step_id="lifecycle_eligibility",
            title="Decision",
            description="Section 2",
            renderer=_step_two,
        ),
    ]
    ctx = LifecycleContext(
        settings=None,
        layout=None,
        database=db,
        token="",
        underlying_name="NIFTY 50",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
        trading_date="2026-08-29",
        signal_id=None,
    )
    render_lifecycle_all(
        steps=steps,
        context=ctx,
        page_key="test_page",
        banner_renderer=None,
        show_timings=False,
        process_name="v2_lifecycle_render",
        database=db,
        run_id=run_id,
    )
    # Two step renders => two evidence rows.
    assert len(db.rows) == 2
    for r in db.rows:
        assert r["run_id"] == run_id
        assert r["process_name"] == "v2_lifecycle_render"
        assert r["status"] == "OK"
        assert r["duration_ms"] >= 0
        assert r["step_name"] in ("step:signal_discovery", "step:lifecycle_eligibility")


def test_render_lifecycle_all_without_evidence_does_not_write():
    """When ``process_name`` is None, the legacy behavior is preserved."""
    from red_bar_lab.ui.lifecycle_stepper import (
        LifecycleContext,
        make_step,
        render_lifecycle_all,
    )

    class _FakeSt:
        def caption(self, *args, **kwargs):
            return None

        def markdown(self, *args, **kwargs):
            return None

        def divider(self):
            return None

        def expander(self, label, expanded=True):
            class _C:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *a):
                    return False

            return _C()

        def error(self, *args, **kwargs):
            return None

    _FakeSt()

    @dataclass
    class _FakeDb:
        def write_step_evidence(self, **kwargs):  # pragma: no cover
            raise AssertionError("should not be called")

    db = _FakeDb()

    def _step(st_arg, context):
        pass

    steps = [
        make_step(
            step_id="signal_discovery",
            title="x",
            description="y",
            renderer=_step,
        )
    ]
    ctx = LifecycleContext(
        settings=None,
        layout=None,
        database=db,
        token="",
        underlying_name="NIFTY 50",
        instrument_key="NSE_INDEX|Nifty 50",
        interval=1,
        trading_date="2026-08-29",
        signal_id=None,
    )
    # No process_name => no evidence writes. Should not raise.
    render_lifecycle_all(
        steps=steps,
        context=ctx,
        page_key="test_page",
        banner_renderer=None,
        show_timings=False,
        process_name=None,
        database=db,
        run_id="rid",
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# --------------------------------------------------------------------------
# Trading view tests
# --------------------------------------------------------------------------



@dataclass
class _TradingFakeSt:
    """Just enough of a Streamlit stand-in for the trading view tests."""
    caption_calls: list = field(default_factory=list)
    markdown_calls: list = field(default_factory=list)
    metric_calls: list = field(default_factory=list)
    caption_with_md: list = field(default_factory=list)
    checkbox_calls: list = field(default_factory=list)
    checkbox_responses: list = field(default_factory=list)

    def caption(self, text, *args, **kwargs):
        self.caption_calls.append(text)
        return None

    def markdown(self, text, *args, **kwargs):
        self.markdown_calls.append(text)
        return None

    def metric(self, *args, **kwargs):
        self.metric_calls.append((args, kwargs))
        return None

    def checkbox(self, label, value=False, key=None, **kwargs):
        self.checkbox_calls.append((label, value, key))
        if self.checkbox_responses:
            return self.checkbox_responses.pop(0)
        return value

    def columns(self, spec):
        class _C:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        # When the spec is a single int (e.g. st.columns(3)), return a
        # list of that many context managers so iteration works.
        if isinstance(spec, int):
            return [_C() for _ in range(spec)]
        if isinstance(spec, (list, tuple)):
            return [_C() for _ in spec]
        return _C()


@dataclass
class _TradingFakeDb:
    """Database stand-in for the trading view tests."""

    signal: dict | None = None
    counts: dict = field(default_factory=dict)
    activity: dict = field(default_factory=dict)

    def read_latest_signal_for_trading(self, *, instrument_key, trading_date):
        return self.signal

    def read_today_signal_counts(self, *, instrument_key, trading_date):
        return self.counts

    def read_today_paper_activity(self, *, account_id, trading_date):
        return self.activity


def test_trading_view_handles_no_signal():
    from red_bar_lab.ui import live_cadence as lc

    st = _TradingFakeSt()
    db = _TradingFakeDb(
        signal=None,
        activity={
            "entered": 0,
            "closed": 0,
            "open": 0,
            "last_entry": None,
            "last_close": None,
            "realized_pnl": 0.0,
        },
    )
    # Patch the database handle resolver.
    original = lc._get_database_handle
    lc._get_database_handle = lambda st_arg: db
    try:
        lc._render_trading_view(
            st,
            instrument_key="NSE_INDEX|Nifty 50",
            trading_date="2026-09-01",
            account_id="PAPER-STD",
        )
    finally:
        lc._get_database_handle = original
    # Should render the "no signal" caption, not raise.
    assert any(
        "No confirmed signal" in c for c in st.caption_calls
    )


def test_trading_view_renders_signal_and_activity_when_present():
    from red_bar_lab.ui import live_cadence as lc

    st = _TradingFakeSt()
    db = _TradingFakeDb(
        signal={
            "signal_id": "RBV2-001",
            "confirmation_timestamp": "2026-09-01T09:23:00+05:30",
            "level": "24815 CE",
            "direction": "LONG",
            "score": 82,
            "shadow_observation": {
                "section_1_outcome": "REFERENCE_READY",
                "section_2_outcome": "ALLOWED",
                "bundle_id": "BND-abc123",
            },
            "pipeline_status": {
                "core_eligible": 1,
                "hybrid_eligible": 0,
            },
        },
        counts={"CONFIRMED": 1, "PENDING": 0},
        activity={
            "entered": 1,
            "closed": 0,
            "open": 1,
            "last_entry": {
                "direction": "LONG",
                "option_type": "CE",
                "strike_price": 24815,
                "entry_price": 24830.5,
                "entry_timestamp": "2026-09-01T09:23:05+05:30",
            },
            "last_close": None,
            "realized_pnl": 0.0,
        },
    )
    original = lc._get_database_handle
    lc._get_database_handle = lambda st_arg: db
    try:
        lc._render_trading_view(
            st,
            instrument_key="NSE_INDEX|Nifty 50",
            trading_date="2026-09-01",
            account_id="PAPER-STD",
        )
    finally:
        lc._get_database_handle = original
    # The "Latest signal" section should mention the direction and level.
    full = " ".join(st.caption_calls + st.markdown_calls)
    assert "LONG" in full
    assert "24815" in full
    assert "REFERENCE_READY" in full
    assert "ALLOWED" in full
    assert "BND-abc123" in full
    assert "core eligible" in full
    # The "Today's activity" section should show counts and P&L.
    assert "1" in full
    assert "confirmed" in full
    assert "entered" in full
    assert "closed" in full
    assert "open" in full


def test_trading_view_omitted_when_instrument_or_date_missing():
    from red_bar_lab.ui import live_cadence as lc

    st = _TradingFakeSt()
    # Patch the database handle resolver so we get past the first
    # short-circuit; we want to exercise the "no instrument/date"
    # branch.
    original = lc._get_database_handle
    lc._get_database_handle = lambda st_arg: object()
    try:
        # No instrument, no date -> should render a helpful caption.
        lc._render_trading_view(
            st,
            instrument_key=None,
            trading_date=None,
            account_id="PAPER-STD",
        )
    finally:
        lc._get_database_handle = original
    assert any("No instrument" in c for c in st.caption_calls)


def test_advanced_diagnostics_toggle_drives_diagnostic_panel():
    """When the user ticks the Advanced diagnostics box, the
    correlation + step-evidence panels render. When they don't, those
    panels are not called. The trading view is always called."""
    from red_bar_lab.ui import live_cadence as lc

    cadences = [
        lc.UpstreamCadenceStatus(
            name="Paper Monitor",
            cadence_label="5s",
            last_heartbeat_at=None,
            seconds_since_heartbeat=None,
            is_stale=False,
            last_signal_id=None,
            last_decision=None,
            last_error=None,
            total_ms=None,
            stages={},
        ),
        lc.UpstreamCadenceStatus(
            name="Background Orchestrator",
            cadence_label="60s",
            last_heartbeat_at=None,
            seconds_since_heartbeat=None,
            is_stale=False,
            last_signal_id=None,
            last_decision=None,
            last_error=None,
            total_ms=None,
            stages={},
        ),
        lc.UpstreamCadenceStatus(
            name="Page Polling",
            cadence_label="5s",
            last_heartbeat_at=None,
            seconds_since_heartbeat=None,
            is_stale=False,
            last_signal_id=None,
            last_decision=None,
            last_error=None,
            total_ms=None,
            stages={},
        ),
    ]
    st = _TradingFakeSt()
    st.checkbox_responses = [False]  # Advanced OFF

    # Replace evidence + correlation renderers with sentinels.
    advanced_called = {"correlation": False, "step_evidence": False}
    trading_called = {"trading": False}

    def fake_correlation(st_arg):
        advanced_called["correlation"] = True

    def fake_step_evidence(st_arg):
        advanced_called["step_evidence"] = True

    def fake_trading(
        st_arg,
        *,
        instrument_key=None,
        trading_date=None,
        account_id=None,
    ):
        trading_called["trading"] = True

    orig_corr = lc._render_run_correlation_panel
    orig_step = lc._render_step_evidence_panel
    orig_trad = lc._render_trading_view
    lc._render_run_correlation_panel = fake_correlation
    lc._render_step_evidence_panel = fake_step_evidence
    lc._render_trading_view = fake_trading
    try:
        # Advanced OFF -> correlation and step evidence should not run.
        lc.render_upstream_cadence_panel(
            st,
            cadences=cadences,
            page_poll_interval_seconds=3,
            page_polls_since_start=0,
            page_last_poll_at=None,
            page_started_at=None,
            instrument_key="NSE_INDEX|Nifty 50",
            trading_date="2026-09-01",
            account_id="PAPER-STD",
        )
        assert trading_called["trading"] is True
        assert advanced_called["correlation"] is False
        assert advanced_called["step_evidence"] is False
        # Now toggle ON.
        trading_called["trading"] = False
        advanced_called["correlation"] = False
        advanced_called["step_evidence"] = False
        st.checkbox_responses = [True]
        lc.render_upstream_cadence_panel(
            st,
            cadences=cadences,
            page_poll_interval_seconds=3,
            page_polls_since_start=0,
            page_last_poll_at=None,
            page_started_at=None,
            instrument_key="NSE_INDEX|Nifty 50",
            trading_date="2026-09-01",
            account_id="PAPER-STD",
        )
        assert trading_called["trading"] is True
        assert advanced_called["correlation"] is True
        assert advanced_called["step_evidence"] is True
    finally:
        lc._render_run_correlation_panel = orig_corr
        lc._render_step_evidence_panel = orig_step
        lc._render_trading_view = orig_trad
