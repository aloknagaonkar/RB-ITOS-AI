from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sqlite3

from red_bar_lab.services.red_bar_v2_canonical.paper_execution_adapter import (
    PaperAdapterResult,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_ledger import (
    StrictSQLiteCanonicalPaperExecutionRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_models import (
    PaperExecutionOutcome,
    PaperExecutionState,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_repository import (
    PaperExecutionStorageError,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_replay_guard import (
    ReplayGuardedCanonicalPaperService,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_models import (
    CanonicalReservationResult,
    ReservationOutcome,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_repository import (
    SQLiteCanonicalReservationRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_service import (
    RedBarV2CanonicalReservationService,
)
from red_bar_lab.tests.test_red_bar_v2_canonical_paper_execution import (
    FakePaperAdapter,
    FixedSelector,
    _contract,
    _database,
)


class RaisingAdapter(FakePaperAdapter):
    def submit(self, *, command):
        self.submissions += 1
        raise TimeoutError("simulated acknowledgement loss")


class FailingReleaseService:
    def __init__(self, delegate):
        self.delegate = delegate

    def reserve(self, **kwargs):
        return self.delegate.reserve(**kwargs)

    def release(self, **kwargs):
        return CanonicalReservationResult(
            outcome=ReservationOutcome.STORAGE_UNAVAILABLE,
            reason_code="STORAGE_UNAVAILABLE",
            reservation=None,
        )


class FailingLookupRepository(StrictSQLiteCanonicalPaperExecutionRepository):
    def find_by_idempotency_key(self, *, idempotency_key):
        raise PaperExecutionStorageError("simulated lookup failure")


class CountingSelector(FixedSelector):
    pass


def _service(path: Path, *, adapter, reservations=None, repository=None):
    bundle = _database(path)
    reservations = reservations or RedBarV2CanonicalReservationService(
        SQLiteCanonicalReservationRepository(path),
        enabled=True,
    )
    repository = repository or StrictSQLiteCanonicalPaperExecutionRepository(path)
    selector = CountingSelector(_contract(bundle))
    service = ReplayGuardedCanonicalPaperService(
        database_path=path,
        repository=repository,
        reservation_service=reservations,
        selector=selector,
        adapter=adapter,
        enabled=True,
        mode="PAPER_CANARY",
    )
    return bundle, service, selector


def test_preflight_repository_failure_is_fail_closed(tmp_path: Path):
    path = tmp_path / "preflight.db"
    bundle = _database(path)
    repository = FailingLookupRepository(path)
    reservations = RedBarV2CanonicalReservationService(
        SQLiteCanonicalReservationRepository(path), enabled=True
    )
    selector = CountingSelector(_contract(bundle))
    adapter = FakePaperAdapter()
    service = ReplayGuardedCanonicalPaperService(
        database_path=path,
        repository=repository,
        reservation_service=reservations,
        selector=selector,
        adapter=adapter,
        enabled=True,
        mode="PAPER_CANARY",
    )
    result = service.execute(
        bundle_id=bundle.bundle_id,
        spot_price=25000.0,
        requested_at=bundle.created_at,
    )
    assert result.outcome is PaperExecutionOutcome.STORAGE_UNAVAILABLE
    assert selector.calls == 0
    assert adapter.submissions == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_reservations"
        ).fetchone()[0] == 0


def test_adapter_exception_becomes_durable_uncertainty(tmp_path: Path):
    path = tmp_path / "uncertain.db"
    adapter = RaisingAdapter()
    bundle, service, selector = _service(path, adapter=adapter)
    result = service.execute(
        bundle_id=bundle.bundle_id,
        spot_price=25000.0,
        requested_at=bundle.created_at,
    )
    assert result.outcome is PaperExecutionOutcome.SUBMISSION_UNCERTAIN
    assert result.state is PaperExecutionState.SUBMISSION_UNCERTAIN
    assert adapter.submissions == 1
    assert selector.calls == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_reservations "
            "WHERE state='RESERVED'"
        ).fetchone()[0] == 1


def test_unproven_release_returns_recovery_required(tmp_path: Path):
    path = tmp_path / "release.db"
    delegate = RedBarV2CanonicalReservationService(
        SQLiteCanonicalReservationRepository(path), enabled=True
    )
    failing = FailingReleaseService(delegate)
    adapter = FakePaperAdapter()
    bundle, service, _ = _service(
        path,
        adapter=adapter,
        reservations=failing,
    )
    result = service.execute(
        bundle_id=bundle.bundle_id,
        spot_price=25000.0,
        requested_at=bundle.created_at,
    )
    assert result.outcome is PaperExecutionOutcome.RECOVERY_REQUIRED
    assert result.state is PaperExecutionState.PAPER_FILLED
    assert result.paper_order_id == "PAPER-1"
    assert adapter.submissions == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT state FROM canonical_red_bar_v2_paper_commands"
        ).fetchone()[0] == "PAPER_FILLED"
        assert conn.execute(
            "SELECT state FROM canonical_red_bar_v2_bundle_reservations"
        ).fetchone()[0] == "RESERVED"


def test_equal_time_acquire_and_release_verify_semantically(tmp_path: Path):
    path = tmp_path / "equal-time.db"
    bundle = _database(path)
    repository = SQLiteCanonicalReservationRepository(path)
    service = RedBarV2CanonicalReservationService(repository, enabled=True)
    acquired = service.reserve(
        bundle_id=bundle.bundle_id,
        owner_id="CANONICAL_RED_BAR_V2_PAPER_WORKER",
        requested_at=bundle.created_at,
    )
    assert acquired.reservation is not None
    released = service.release(
        reservation_id=acquired.reservation.reservation_id,
        owner_id=acquired.reservation.owner_id,
        released_at=acquired.reservation.reserved_at,
        reason_code="PAPER_CONSTRUCTION_REJECTED",
    )
    assert released.outcome is ReservationOutcome.RELEASED
    verified = repository.get_active(
        bundle_id=bundle.bundle_id,
        at=bundle.created_at + timedelta(microseconds=1),
    )
    assert verified is None
