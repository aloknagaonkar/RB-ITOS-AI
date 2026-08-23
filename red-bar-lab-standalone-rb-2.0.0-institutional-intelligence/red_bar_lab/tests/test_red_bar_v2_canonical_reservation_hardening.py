from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sqlite3

from red_bar_lab.services.red_bar_v2_canonical import (
    RedBarV2CanonicalPersistenceService,
    SQLiteRedBarV2CanonicalRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_models import (
    ReservationOutcome,
    ReservationState,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_observability import (
    SQLiteReservationObservabilityRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_repository import (
    SQLiteCanonicalReservationRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_service import (
    OBSERVATIONAL_OWNER_ID,
    RedBarV2CanonicalReservationService,
)
from red_bar_lab.tests.red_bar_v2_persistence_fixtures import (
    RESOLVED_AT,
    UNDERLYING,
    make_resolution,
)


def _database(path: Path):
    resolution, parity = make_resolution()
    RedBarV2CanonicalPersistenceService(
        SQLiteRedBarV2CanonicalRepository(path),
        clock=lambda: RESOLVED_AT,
    ).persist(resolution=resolution, parity=parity, instrument_key=UNDERLYING)
    assert resolution.section_3 is not None
    return resolution.section_3


def _service(path: Path) -> RedBarV2CanonicalReservationService:
    return RedBarV2CanonicalReservationService(
        SQLiteCanonicalReservationRepository(path),
        enabled=True,
        lease_seconds=30,
        maximum_bundle_age_seconds=120,
    )


def _acquire(path: Path):
    bundle = _database(path)
    result = _service(path).reserve(
        bundle_id=bundle.bundle_id,
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=RESOLVED_AT + timedelta(seconds=1),
    )
    assert result.outcome is ReservationOutcome.ACQUIRED
    assert result.reservation is not None
    return bundle, result.reservation


def test_full_canonical_bundle_projection_corruption_blocks_reservation(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle = _database(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundles SET option_side='PE' WHERE bundle_id=?",
            (bundle.bundle_id,),
        )
    result = _service(path).reserve(
        bundle_id=bundle.bundle_id,
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=RESOLVED_AT + timedelta(seconds=1),
    )
    assert result.outcome is ReservationOutcome.BUNDLE_CORRUPT


def test_resolution_digest_and_orphaned_bundle_block_reservation(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle = _database(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_resolutions SET payload_sha256='bad' WHERE bundle_id=?",
            (bundle.bundle_id,),
        )
    assert _service(path).reserve(
        bundle_id=bundle.bundle_id,
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=RESOLVED_AT + timedelta(seconds=1),
    ).outcome is ReservationOutcome.BUNDLE_CORRUPT

    path2 = tmp_path / "orphan.sqlite"
    bundle2 = _database(path2)
    with sqlite3.connect(path2) as conn:
        conn.execute(
            "DELETE FROM canonical_red_bar_v2_resolutions WHERE bundle_id=?",
            (bundle2.bundle_id,),
        )
    assert _service(path2).reserve(
        bundle_id=bundle2.bundle_id,
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=RESOLVED_AT + timedelta(seconds=1),
    ).outcome is ReservationOutcome.BUNDLE_CORRUPT


def test_lifecycle_projection_corruption_blocks_reservation(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle = _database(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundle_events SET source='WRONG' WHERE bundle_id=?",
            (bundle.bundle_id,),
        )
    result = _service(path).reserve(
        bundle_id=bundle.bundle_id,
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=RESOLVED_AT + timedelta(seconds=1),
    )
    assert result.outcome is ReservationOutcome.BUNDLE_CORRUPT


def test_release_before_reservation_is_typed_and_does_not_mutate(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    _, reservation = _acquire(path)
    result = _service(path).release(
        reservation_id=reservation.reservation_id,
        owner_id=reservation.owner_id,
        released_at=reservation.reserved_at - timedelta(seconds=1),
        reason_code="MANUAL_RELEASE",
    )
    assert result.outcome is ReservationOutcome.INVALID_REQUEST
    with sqlite3.connect(path) as conn:
        state = conn.execute(
            "SELECT state FROM canonical_red_bar_v2_bundle_reservations WHERE reservation_id=?",
            (reservation.reservation_id,),
        ).fetchone()[0]
    assert state == "RESERVED"


def test_release_at_or_after_expiry_transitions_to_expired_only(tmp_path: Path):
    for seconds_after in (0, 5):
        path = tmp_path / f"expiry-{seconds_after}.sqlite"
        _, reservation = _acquire(path)
        result = _service(path).release(
            reservation_id=reservation.reservation_id,
            owner_id=reservation.owner_id,
            released_at=reservation.lease_expires_at + timedelta(seconds=seconds_after),
            reason_code="MANUAL_RELEASE",
        )
        assert result.outcome is ReservationOutcome.EXPIRED
        assert result.reservation is not None
        assert result.reservation.state is ReservationState.EXPIRED
        assert result.reservation.released_at == reservation.lease_expires_at
        with sqlite3.connect(path) as conn:
            types = {
                row[0]
                for row in conn.execute(
                    "SELECT event_type FROM canonical_red_bar_v2_bundle_reservation_events WHERE reservation_id=?",
                    (reservation.reservation_id,),
                )
            }
        assert "RESERVATION_EXPIRED" in types
        assert "RESERVATION_RELEASED" not in types


def test_release_during_active_lease_succeeds(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    _, reservation = _acquire(path)
    result = _service(path).release(
        reservation_id=reservation.reservation_id,
        owner_id=reservation.owner_id,
        released_at=reservation.reserved_at + timedelta(seconds=2),
        reason_code="MANUAL_RELEASE",
    )
    assert result.outcome is ReservationOutcome.RELEASED


def test_public_invalid_requests_are_typed_and_create_no_database(tmp_path: Path):
    path = tmp_path / "missing" / "db.sqlite"
    service = RedBarV2CanonicalReservationService(None, enabled=True)
    cases = (
        service.reserve(bundle_id="", owner_id="OWNER", requested_at=RESOLVED_AT),
        service.reserve(bundle_id="BUNDLE", owner_id="", requested_at=RESOLVED_AT),
        service.reserve(bundle_id="BUNDLE", owner_id="OWNER", requested_at=RESOLVED_AT.replace(tzinfo=None)),
        service.release(reservation_id="", owner_id="OWNER", released_at=RESOLVED_AT, reason_code="R"),
        service.release(reservation_id="R", owner_id="", released_at=RESOLVED_AT, reason_code="R"),
        service.release(reservation_id="R", owner_id="OWNER", released_at=RESOLVED_AT, reason_code=""),
        service.release(reservation_id="R", owner_id="OWNER", released_at=RESOLVED_AT.replace(tzinfo=None), reason_code="R"),
    )
    assert all(item.outcome is ReservationOutcome.INVALID_REQUEST for item in cases)
    assert not path.exists()


def test_reservation_observability_detects_digest_and_projection_corruption(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle, reservation = _acquire(path)
    repository = SQLiteReservationObservabilityRepository(path)
    assert repository.latest_for_bundle(bundle_id=bundle.bundle_id).status == "RESERVATION_DATA_AVAILABLE"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundle_reservations SET payload_sha256='bad' WHERE reservation_id=?",
            (reservation.reservation_id,),
        )
    result = repository.latest_for_bundle(bundle_id=bundle.bundle_id)
    assert result.status == "RESERVATION_DATA_CORRUPT"
    assert result.reservation is None
    assert result.events == ()


def test_reservation_event_corruption_is_not_rendered_as_trusted(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle, reservation = _acquire(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundle_reservation_events SET owner_id='WRONG' WHERE reservation_id=?",
            (reservation.reservation_id,),
        )
    result = SQLiteReservationObservabilityRepository(path).latest_for_bundle(bundle_id=bundle.bundle_id)
    assert result.status == "RESERVATION_DATA_CORRUPT"
    assert result.reservation is None


def test_missing_reservation_and_database_unavailable_are_distinct(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle = _database(path)
    repository = SQLiteReservationObservabilityRepository(path)
    assert repository.latest_for_bundle(bundle_id=bundle.bundle_id).status == "NO_RESERVATION"
    missing = SQLiteReservationObservabilityRepository(tmp_path / "missing.sqlite")
    assert missing.latest_for_bundle(bundle_id=bundle.bundle_id).status == "RESERVATION_DATABASE_UNAVAILABLE"
