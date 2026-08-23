from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sqlite3

from red_bar_lab.services.red_bar_v2_canonical.paper_execution_models import (
    PaperExecutionOutcome,
    PaperExecutionState,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_observability import (
    SQLiteCanonicalPaperExecutionObservabilityRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_recovery import (
    ControlledCanonicalPaperRecoveryService,
)
from red_bar_lab.tests.test_red_bar_v2_canonical_paper_execution import (
    FakePaperAdapter,
    _service,
)


def test_observability_rejects_corrupt_correlated_reservation(tmp_path: Path):
    path = tmp_path / "observability-corrupt-reservation.db"
    bundle, service, _, _ = _service(path)
    result = service.execute(
        bundle_id=bundle.bundle_id,
        spot_price=25000.0,
        requested_at=bundle.created_at,
    )
    assert result.command is not None

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundle_reservations "
            "SET payload_sha256='corrupt' WHERE reservation_id=?",
            (result.command.reservation_id,),
        )

    observed = SQLiteCanonicalPaperExecutionObservabilityRepository(
        path
    ).latest_for_bundle(bundle_id=bundle.bundle_id)
    assert observed.status == "EXECUTION_DATA_CORRUPT"
    assert observed.evidence is None


class _TwoCandidateRepository:
    def __init__(self) -> None:
        self.rows = {
            "E1": SimpleNamespace(
                command=SimpleNamespace(reservation_id="R1"),
                state=PaperExecutionState.SUBMISSION_STARTED,
                paper_order_id=None,
                reason_code="SUBMISSION_STARTED",
            ),
            "E2": SimpleNamespace(
                command=SimpleNamespace(reservation_id="R2"),
                state=PaperExecutionState.SUBMISSION_STARTED,
                paper_order_id=None,
                reason_code="SUBMISSION_STARTED",
            ),
        }

    def get_verified(self, *, execution_id: str):
        return self.rows[execution_id]


class _TwoCandidateRecovery(ControlledCanonicalPaperRecoveryService):
    def _candidate_ids(self, *, limit: int) -> tuple[str, ...]:
        return ("E1", "E2")


class _FailFirstLookupAdapter:
    def __init__(self) -> None:
        self.lookups: list[str] = []
        self.submissions = 0

    def lookup(self, *, execution_id: str):
        self.lookups.append(execution_id)
        if execution_id == "E1":
            raise TimeoutError("simulated recovery lookup timeout")
        return None

    def submit(self, *, command):
        self.submissions += 1
        raise AssertionError("recovery must never submit")


class _UnusedReservationService:
    def release(self, **kwargs):
        raise AssertionError("nonterminal lookup failure must not release")


def test_recovery_lookup_failure_isolated_and_next_candidate_continues():
    adapter = _FailFirstLookupAdapter()
    service = _TwoCandidateRecovery(
        repository=_TwoCandidateRepository(),
        adapter=adapter,
        reservation_service=_UnusedReservationService(),
    )

    results = service.recover(
        observed_at=datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc),
    )

    assert len(results) == 2
    assert results[0].outcome is PaperExecutionOutcome.RECOVERY_REQUIRED
    assert results[0].reason_code == "RECOVERY_LOOKUP_UNAVAILABLE"
    assert results[0].state is PaperExecutionState.SUBMISSION_STARTED
    assert results[1].outcome is PaperExecutionOutcome.RECOVERY_REQUIRED
    assert results[1].reason_code == "NO_PROVEN_PAPER_RESULT"
    assert adapter.lookups == ["E1", "E2"]
    assert adapter.submissions == 0
