from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sqlite3

from red_bar_lab.services.red_bar_v2_canonical.paper_execution_adapter import PaperAdapterResult
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_models import (
    PaperExecutionEventType,
    PaperExecutionOutcome,
    PaperExecutionState,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_recovery import (
    ControlledCanonicalPaperRecoveryService,
)
from red_bar_lab.tests.test_red_bar_v2_canonical_paper_execution import (
    FakePaperAdapter,
    _service,
)


def test_recovery_finds_existing_result_without_resubmission(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle, service, adapter, ledger = _service(
        path,
        adapter=FakePaperAdapter(uncertain=True),
    )
    uncertain = service.execute(
        bundle_id=bundle.bundle_id,
        spot_price=25000.0,
        requested_at=bundle.created_at,
    )
    assert uncertain.state is PaperExecutionState.SUBMISSION_UNCERTAIN
    assert uncertain.command is not None
    adapter.uncertain = False
    adapter.accepted = True
    adapter.rows[uncertain.command.execution_id] = PaperAdapterResult(
        accepted=True,
        uncertain=False,
        reason_code="EXISTING_PAPER_OPEN",
        paper_order_id="PAPER-RECOVERED",
    )
    recovery = ControlledCanonicalPaperRecoveryService(
        repository=ledger,
        adapter=adapter,
        reservation_service=service.reservation_service,
    )
    result = recovery.recover(
        observed_at=bundle.created_at + timedelta(seconds=2)
    )
    assert len(result) == 1
    assert result[0].outcome is PaperExecutionOutcome.SUBMISSION_ACCEPTED
    assert result[0].state is PaperExecutionState.PAPER_FILLED
    assert adapter.submissions == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_reservations "
            "WHERE state='RESERVED'"
        ).fetchone()[0] == 0


def test_recovery_without_proven_result_does_not_submit_or_release(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle, service, adapter, ledger = _service(
        path,
        adapter=FakePaperAdapter(uncertain=True),
    )
    uncertain = service.execute(
        bundle_id=bundle.bundle_id,
        spot_price=25000.0,
        requested_at=bundle.created_at,
    )
    assert uncertain.command is not None
    adapter.uncertain = False
    adapter.rows.clear()
    recovery = ControlledCanonicalPaperRecoveryService(
        repository=ledger,
        adapter=adapter,
        reservation_service=service.reservation_service,
    )
    result = recovery.recover(
        observed_at=bundle.created_at + timedelta(seconds=2)
    )
    assert result[0].outcome is PaperExecutionOutcome.RECOVERY_REQUIRED
    assert adapter.submissions == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_reservations "
            "WHERE state='RESERVED'"
        ).fetchone()[0] == 1


def test_lifecycle_tampering_is_detected(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle, service, _, ledger = _service(path)
    result = service.execute(
        bundle_id=bundle.bundle_id,
        spot_price=25000.0,
        requested_at=bundle.created_at,
    )
    assert result.command is not None
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_paper_execution_events "
            "SET event_type=? WHERE execution_id=? AND event_type=?",
            (
                PaperExecutionEventType.PAPER_REJECTED.value,
                result.command.execution_id,
                PaperExecutionEventType.PAPER_FILLED.value,
            ),
        )
    from red_bar_lab.services.red_bar_v2_canonical.paper_execution_repository import (
        PaperExecutionCorruptionError,
    )
    import pytest

    with pytest.raises(PaperExecutionCorruptionError):
        ledger.get_verified(execution_id=result.command.execution_id)
