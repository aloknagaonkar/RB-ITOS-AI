"""Tests for the process_run_correlation table and the per-step evidence
panel's run timeline selector."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest


def _init_db(path: Path):
    """Create a fresh RedBarDatabase at ``path`` with the production
    schema. This is enough for the new tests to run without importing
    the rest of the application."""
    from red_bar_lab.storage.database import RedBarDatabase

    return RedBarDatabase(path)


def test_write_process_run_correlation_persists_and_updates(tmp_path: Path):
    db = _init_db(tmp_path / "test.db")
    db.write_process_run_correlation(
        process_name="market_collector",
        run_id="MC-001",
        started_at="2026-08-29T10:30:00+05:30",
        artifacts={"phase": "OPEN"},
    )
    row = db.read_process_run_correlation(process_name="market_collector")
    assert row is not None
    assert row["run_id"] == "MC-001"
    assert row["artifacts"]["phase"] == "OPEN"
    # Second write replaces the first.
    db.write_process_run_correlation(
        process_name="market_collector",
        run_id="MC-002",
        started_at="2026-08-29T10:30:05+05:30",
        artifacts={"phase": "OPEN"},
    )
    row = db.read_process_run_correlation(process_name="market_collector")
    assert row["run_id"] == "MC-002"


def test_read_all_process_run_correlations_returns_recent_first(tmp_path: Path):
    db = _init_db(tmp_path / "test.db")
    db.write_process_run_correlation(
        process_name="market_collector",
        run_id="MC-001",
        started_at="2026-08-29T10:30:00+05:30",
    )
    db.write_process_run_correlation(
        process_name="canonical_shadow",
        run_id="CS-001",
        started_at="2026-08-29T10:30:01+05:30",
    )
    db.write_process_run_correlation(
        process_name="paper_monitor",
        run_id="PM-001",
        started_at="2026-08-29T10:30:02+05:30",
    )
    rows = db.read_all_process_run_correlations()
    assert len(rows) == 3
    # Newest first.
    starteds = [r["started_at"] for r in rows]
    assert starteds == sorted(starteds, reverse=True)


def test_read_run_evidence_returns_only_rows_for_that_run(tmp_path: Path):
    db = _init_db(tmp_path / "test.db")
    # Run A: 3 rows.
    rid_a = "run-A"
    for step in ("candle_fetch", "orchestrator_run", "evaluate_day"):
        step_id = db.write_step_evidence(
            process_name="orchestrator",
            run_id=rid_a,
            step_name=step,
            parent_step=None,
            started_at="2026-08-29T10:00:00+05:30",
            status="OK",
        )
        db.update_step_evidence(
            step_id=step_id,
            completed_at="2026-08-29T10:00:00+05:30",
            status="OK",
            duration_ms=100.0,
        )
    # Run B: 2 rows.
    rid_b = "run-B"
    for step in ("candle_fetch", "orchestrator_run"):
        step_id = db.write_step_evidence(
            process_name="orchestrator",
            run_id=rid_b,
            step_name=step,
            parent_step=None,
            started_at="2026-08-29T10:00:05+05:30",
            status="OK",
        )
        db.update_step_evidence(
            step_id=step_id,
            completed_at="2026-08-29T10:00:05+05:30",
            status="OK",
            duration_ms=200.0,
        )
    a_rows = db.read_run_evidence(run_id=rid_a)
    b_rows = db.read_run_evidence(run_id=rid_b)
    assert len(a_rows) == 3
    assert len(b_rows) == 2
    assert {r["step_name"] for r in a_rows} == {
        "candle_fetch",
        "orchestrator_run",
        "evaluate_day",
    }
    assert {r["step_name"] for r in b_rows} == {
        "candle_fetch",
        "orchestrator_run",
    }
    # All rows for a run share the same run_id.
    for r in a_rows:
        assert r["run_id"] == rid_a
    for r in b_rows:
        assert r["run_id"] == rid_b


@dataclass
class _SessionState:
    data: dict = field(default_factory=dict)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __contains__(self, key):
        return key in self.data


@dataclass
class _St:
    session_state: _SessionState = field(default_factory=_SessionState)
    caption_calls: list = field(default_factory=list)
    selectbox_calls: list = field(default_factory=list)

    def caption(self, text):
        self.caption_calls.append(text)
        return None

    def selectbox(self, label, options, key=None, **kwargs):
        self.selectbox_calls.append((label, list(options), key))
        if options:
            return options[0]
        return None

    def markdown(self, text, help=None):
        return None


def test_render_run_correlation_panel_renders_each_process():
    from red_bar_lab.ui import live_cadence as lc

    st = _St()
    rows = [
        {
            "process_name": "market_collector",
            "run_id": "MC-001",
            "started_at": "2026-08-29T10:30:00+05:30",
            "artifacts": None,
        },
        {
            "process_name": "canonical_shadow",
            "run_id": "CS-001",
            "started_at": "2026-08-29T10:30:01+05:30",
            "artifacts": {"resolution_id": "R-1"},
        },
    ]

    def fake_reader():
        return rows

    monkeypatch_fixture = _St()
    monkeypatch_fixture.session_state.data["step_evidence_database"] = object()
    # Inject our reader via the session_state pattern isn't possible; we
    # monkeypatch _get_correlation_reader instead.
    original = lc._get_correlation_reader

    def fake_get_correlation_reader(st_arg):
        return fake_reader

    lc._get_correlation_reader = fake_get_correlation_reader
    try:
        lc._render_run_correlation_panel(st)
    finally:
        lc._get_correlation_reader = original

    captions = " ".join(st.caption_calls)
    assert "market_collector" in captions
    assert "MC-001" in captions
    assert "canonical_shadow" in captions
    assert "CS-001" in captions


def test_render_run_timeline_renders_rows_in_order():
    from red_bar_lab.ui import live_cadence as lc

    st = _St()
    rows = [
        {
            "process_name": "market_collector",
            "step_name": "candle_fetch",
            "parent_step": "tick",
            "started_at": "2026-08-29T10:00:00+05:30",
            "completed_at": "2026-08-29T10:00:00+05:30",
            "status": "OK",
            "duration_ms": 234.0,
            "artifacts": {"phase": "OPEN"},
        },
        {
            "process_name": "canonical_shadow",
            "step_name": "section_1_signal_discovery",
            "parent_step": "resolution",
            "started_at": "2026-08-29T10:00:00+05:30",
            "completed_at": "2026-08-29T10:00:00+05:30",
            "status": "OK",
            "duration_ms": 12.0,
            "artifacts": {"outcome": "REFERENCE_READY"},
        },
    ]

    class _FakeDb:
        def read_all_process_run_correlations(self):
            return [
                {
                    "process_name": "market_collector",
                    "run_id": "MC-001",
                    "started_at": "2026-08-29T10:00:00+05:30",
                    "artifacts": None,
                },
                {
                    "process_name": "canonical_shadow",
                    "run_id": "CS-001",
                    "started_at": "2026-08-29T10:00:01+05:30",
                    "artifacts": None,
                },
            ]

        def read_run_evidence(self, *, run_id):
            return rows if run_id == "MC-001" else []

    st.session_state.data["step_evidence_database"] = _FakeDb()
    lc._render_run_timeline_section(st)
    # The selectbox should have been called with our run_ids.
    assert any("MC-001" in str(c[1]) for c in st.selectbox_calls)
    # Captions should mention both steps.
    captions = " ".join(st.caption_calls)
    assert "candle_fetch" in captions
    assert "section_1_signal_discovery" in captions
    assert "REFERENCE_READY" in captions
    assert "phase" in captions  # artifact surfaced


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
