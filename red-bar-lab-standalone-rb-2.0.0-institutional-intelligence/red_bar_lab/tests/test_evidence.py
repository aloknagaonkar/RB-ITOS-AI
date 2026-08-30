"""Tests for the per-step evidence tracking and rendering."""

from __future__ import annotations

import time as _time
from datetime import datetime, timezone

import pytest

from red_bar_lab.observability.evidence import (
    generate_run_id,
    with_step_evidence,
)


class _InMemoryDatabase:
    """Minimal in-memory stand-in for ``RedBarDatabase`` for evidence tests."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._next_id = 1

    def write_step_evidence(
        self,
        *,
        process_name: str,
        run_id: str,
        step_name: str,
        parent_step,
        started_at: str,
        status: str,
        artifacts=None,
    ) -> int:
        step_id = self._next_id
        self._next_id += 1
        self.rows.append(
            {
                "id": step_id,
                "process_name": process_name,
                "run_id": run_id,
                "step_name": step_name,
                "parent_step": parent_step,
                "started_at": started_at,
                "completed_at": None,
                "status": status,
                "duration_ms": None,
                "error_message": None,
                "artifacts": artifacts,
            }
        )
        return step_id

    def update_step_evidence(
        self,
        *,
        step_id: int,
        completed_at: str,
        status: str,
        duration_ms: float,
        error_message=None,
    ) -> None:
        for row in self.rows:
            if row["id"] == step_id:
                row["completed_at"] = completed_at
                row["status"] = status
                row["duration_ms"] = duration_ms
                row["error_message"] = error_message
                return
        raise KeyError(f"step_id {step_id} not found")

    def read_step_timelines(
        self, *, process_name=None, limit_per_step: int = 5
    ) -> dict[str, list[dict]]:
        rows = self.rows
        if process_name is not None:
            rows = [r for r in rows if r["process_name"] == process_name]
        rows = sorted(rows, key=lambda r: r["started_at"], reverse=True)
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            key = f"{row['process_name']}::{row['step_name']}"
            if key not in grouped:
                grouped[key] = []
            if len(grouped[key]) < limit_per_step:
                grouped[key].append(row)
        return grouped

    def read_latest_step_evidence(
        self, *, process_name: str, step_name: str
    ):
        candidates = [
            r
            for r in self.rows
            if r["process_name"] == process_name
            and r["step_name"] == step_name
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda r: r["started_at"], reverse=True)[0]

    def read_running_steps(self, *, older_than_seconds: float = 60.0):
        now = _time.time()
        result = []
        for row in self.rows:
            if row["status"] != "RUNNING":
                continue
            try:
                parsed = datetime.fromisoformat(
                    row["started_at"].replace("Z", "+00:00")
                )
                age = now - parsed.timestamp()
            except (TypeError, ValueError):
                age = 0.0
            if age >= older_than_seconds:
                result.append({**row, "stuck_for_seconds": age})
        return result


def test_generate_run_id_format():
    rid = generate_run_id("orchestrator")
    parts = rid.split("-")
    assert parts[0] == "orchestrator"
    # Last part is a 6-char hex suffix
    assert len(parts[-1]) == 6
    int(parts[-1], 16)  # raises if not hex


def test_generate_run_id_uniqueness():
    ids = {generate_run_id("paper_monitor") for _ in range(20)}
    # All should be unique; the perf_counter-based suffix differentiates
    # within the same second.
    assert len(ids) >= 10  # at least most of them, allow for clock granularity


def test_with_step_evidence_writes_run_then_ok_rows():
    db = _InMemoryDatabase()
    with with_step_evidence(
        db, process_name="orchestrator", step_name="evaluate_day"
    ):
        pass
    assert len(db.rows) == 1
    row = db.rows[0]
    assert row["process_name"] == "orchestrator"
    assert row["step_name"] == "evaluate_day"
    assert row["parent_step"] is None
    assert row["status"] == "OK"
    assert row["started_at"] is not None
    assert row["completed_at"] is not None
    assert row["duration_ms"] is not None
    assert row["duration_ms"] >= 0


def test_with_step_evidence_marks_error_on_exception():
    db = _InMemoryDatabase()
    with pytest.raises(ValueError):
        with with_step_evidence(
            db, process_name="paper_monitor", step_name="paper_cycle"
        ):
            raise ValueError("candle feed missing")
    assert len(db.rows) == 1
    row = db.rows[0]
    assert row["status"] == "ERROR"
    assert "candle feed missing" in (row["error_message"] or "")


def test_with_step_evidence_records_artifacts():
    db = _InMemoryDatabase()
    with with_step_evidence(
        db,
        process_name="orchestrator",
        step_name="evaluate_day",
        artifacts={"trading_date": "2026-08-29", "confirmed": 8},
    ):
        pass
    row = db.rows[0]
    assert row["artifacts"] == {
        "trading_date": "2026-08-29",
        "confirmed": 8,
    }


def test_with_step_evidence_supplied_run_id_propagates():
    db = _InMemoryDatabase()
    rid = "test-run-123"
    with with_step_evidence(
        db,
        process_name="orchestrator",
        step_name="evaluate_day",
        run_id=rid,
    ):
        pass
    assert db.rows[0]["run_id"] == rid


def test_with_step_evidence_parent_step_propagates():
    db = _InMemoryDatabase()
    with with_step_evidence(
        db,
        process_name="orchestrator",
        step_name="build_market_context",
        run_id="rid-1",
        parent_step="orchestrator_run",
    ):
        pass
    assert db.rows[0]["parent_step"] == "orchestrator_run"


def test_with_step_evidence_reraises_original_exception():
    db = _InMemoryDatabase()
    try:
        with with_step_evidence(
            db, process_name="x", step_name="y"
        ):
            raise RuntimeError("inner")
    except RuntimeError as exc:
        assert str(exc) == "inner"
    else:
        pytest.fail("expected RuntimeError")


def test_read_step_timelines_groups_by_process_and_step():
    db = _InMemoryDatabase()
    with with_step_evidence(
        db, process_name="orchestrator", step_name="evaluate_day"
    ):
        pass
    with with_step_evidence(
        db, process_name="orchestrator", step_name="build_market_context"
    ):
        pass
    with with_step_evidence(
        db, process_name="paper_monitor", step_name="paper_cycle"
    ):
        pass
    timelines = db.read_step_timelines(limit_per_step=10)
    assert set(timelines.keys()) == {
        "orchestrator::evaluate_day",
        "orchestrator::build_market_context",
        "paper_monitor::paper_cycle",
    }
    assert len(timelines["orchestrator::evaluate_day"]) == 1


def test_read_step_timelines_filters_by_process_name():
    db = _InMemoryDatabase()
    with with_step_evidence(db, process_name="orchestrator", step_name="a"):
        pass
    with with_step_evidence(db, process_name="paper_monitor", step_name="b"):
        pass
    orchestrator_only = db.read_step_timelines(
        process_name="orchestrator", limit_per_step=10
    )
    assert "orchestrator::a" in orchestrator_only
    assert "paper_monitor::b" not in orchestrator_only


def test_read_latest_step_evidence_returns_most_recent():
    db = _InMemoryDatabase()
    with with_step_evidence(db, process_name="x", step_name="y"):
        pass
    _time.sleep(0.001)
    with with_step_evidence(db, process_name="x", step_name="y"):
        pass
    latest = db.read_latest_step_evidence(process_name="x", step_name="y")
    assert latest is not None
    assert latest["id"] == 2  # second insert has the higher id


def test_read_running_steps_returns_old_running_rows():
    db = _InMemoryDatabase()
    # Insert a row that is already RUNNING with an old started_at.
    old_iso = (
        datetime.now(timezone.utc)
        .replace(year=2020)  # ancient timestamp so it's "old"
        .isoformat()
    )
    db.rows.append(
        {
            "id": 1,
            "process_name": "x",
            "run_id": "r1",
            "step_name": "y",
            "parent_step": None,
            "started_at": old_iso,
            "completed_at": None,
            "status": "RUNNING",
            "duration_ms": None,
            "error_message": None,
            "artifacts": None,
        }
    )
    stuck = db.read_running_steps(older_than_seconds=60.0)
    assert len(stuck) == 1
    assert stuck[0]["status"] == "RUNNING"
    assert stuck[0]["stuck_for_seconds"] > 60


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
