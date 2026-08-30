"""Tests for the canonical shadow coordinator's evidence integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest


@dataclass
class _Row:
    id: int
    process_name: str
    run_id: str
    step_name: str
    parent_step: str | None
    started_at: str
    completed_at: str | None
    status: str
    duration_ms: float | None
    error_message: str | None
    artifacts: dict | None


class _FakeDatabase:
    """In-memory stand-in for RedBarDatabase that mirrors just the
    write/update/read methods used by the shadow coordinator's evidence
    helpers."""

    def __init__(self) -> None:
        self.rows: list[_Row] = []
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
            _Row(
                id=step_id,
                process_name=process_name,
                run_id=run_id,
                step_name=step_name,
                parent_step=parent_step,
                started_at=started_at,
                completed_at=None,
                status=status,
                duration_ms=None,
                error_message=None,
                artifacts=artifacts,
            )
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
            if row.id == step_id:
                row.completed_at = completed_at
                row.status = status
                row.duration_ms = duration_ms
                row.error_message = error_message
                return
        raise KeyError(step_id)

    def rows_for(self, step_name: str) -> list[_Row]:
        return [r for r in self.rows if r.step_name == step_name]


@dataclass
class _FakeResolution:
    section_1: Any
    section_2: Any
    section_3: Any


@dataclass
class _FakeSection1:
    outcome: Any
    reason: str | None = None
    reason_code: str | None = None


@dataclass
class _FakeSection2:
    admission_outcome: Any
    strategy_id: str = "RED_BAR_V2"
    strategy_version: str = "1.0"
    direction: Any = None
    option_side: Any = None
    entry_type: Any = None
    evaluation_timeframe: str = "5m"


@dataclass
class _FakeSection3:
    strategy_id: str = "RED_BAR_V2"


class _Outcome:
    def __init__(self, value: str) -> None:
        self.value = value


@dataclass
class _FakePersistenceService:
    """Stub persistence service that returns a fake result."""
    outcome: Any = field(default_factory=lambda: _Outcome("PERSISTED"))


def _build_persistence_service() -> MagicMock:
    svc = MagicMock()
    svc.persist.return_value = MagicMock(
        outcome=_Outcome("PERSISTED"),
        resolution_id="res-1",
        bundle_id="bnd-1",
    )
    return svc


def test_evidence_step_helper_yields_noop_when_database_is_none():
    from red_bar_lab.services.red_bar_v2_canonical.shadow_coordinator import (
        _evidence_step,
    )

    with _evidence_step(None, "canonical_shadow", "x", "rid") as step_id:
        assert step_id == -1


def test_evidence_step_helper_writes_when_database_is_provided():
    from red_bar_lab.services.red_bar_v2_canonical.shadow_coordinator import (
        _evidence_step,
    )

    db = _FakeDatabase()
    with _evidence_step(db, "canonical_shadow", "resolution", "rid-1") as step_id:
        assert step_id > 0
    rows = db.rows_for("resolution")
    assert len(rows) == 1
    assert rows[0].status == "OK"
    assert rows[0].duration_ms is not None
    assert rows[0].duration_ms >= 0


def test_record_section_outcome_writes_outcome_artifact():
    from red_bar_lab.services.red_bar_v2_canonical.shadow_coordinator import (
        _record_section_outcome,
    )

    db = _FakeDatabase()
    section = _FakeSection1(
        outcome=_Outcome("REFERENCE_READY"),
        reason="all inputs fresh",
        reason_code="OK",
    )
    _record_section_outcome(
        None,
        database=db,
        section=section,
        run_id="rid-1",
        step_name="section_1_signal_discovery",
    )
    rows = db.rows_for("section_1_signal_discovery")
    assert len(rows) == 1
    assert rows[0].artifacts is not None
    assert rows[0].artifacts["outcome"] == "REFERENCE_READY"
    assert rows[0].artifacts["reason"] == "all inputs fresh"


def test_record_section_outcome_noop_when_database_is_none():
    from red_bar_lab.services.red_bar_v2_canonical.shadow_coordinator import (
        _record_section_outcome,
    )

    # Should not raise even without a database.
    _record_section_outcome(
        None,
        section=_FakeSection1(outcome=_Outcome("REFERENCE_READY")),
        run_id="rid-1",
        step_name="section_1_signal_discovery",
    )


def test_evidence_writes_share_run_id_across_substeps():
    """All sub-step evidence rows for a single observe() call must share
    the same run_id so the user can correlate them.
    """
    from red_bar_lab.services.red_bar_v2_canonical.shadow_coordinator import (
        _writer_stage_evidence,
        _record_section_outcome,
    )

    db = _FakeDatabase()
    rid = "canonical-shadow-test-001"
    # Use the new writer-aware helper.
    with _writer_stage_evidence(
        None,
        db,
        process_name="canonical_shadow",
        step_name="resolution",
        run_id=rid,
    ):
        pass
    with _writer_stage_evidence(
        None,
        db,
        process_name="canonical_shadow",
        step_name="parity",
        run_id=rid,
    ):
        pass
    _record_section_outcome(
        None,
        db,
        section=_FakeSection1(outcome=_Outcome("REFERENCE_READY")),
        run_id=rid,
        step_name="section_1_signal_discovery",
    )
    _record_section_outcome(
        None,
        db,
        section=_FakeSection2(admission_outcome=_Outcome("ALLOWED")),
        run_id=rid,
        step_name="section_2_lifecycle_eligibility",
    )
    _record_section_outcome(
        None,
        db,
        section=_FakeSection3(),
        run_id=rid,
        step_name="section_3_signal_bundle",
    )
    run_ids = {r.run_id for r in db.rows}
    assert run_ids == {rid}
    # All FIVE expected steps are present: resolution, parity, and the
    # three section sub-steps. The persistence step is now written by
    # the persistence service itself, not by the coordinator.
    step_names = {r.step_name for r in db.rows}
    assert {
        "resolution",
        "parity",
        "section_1_signal_discovery",
        "section_2_lifecycle_eligibility",
        "section_3_signal_bundle",
    } == step_names


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
