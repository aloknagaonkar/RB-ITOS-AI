from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sqlite3

import pytest

from red_bar_lab.services.red_bar_v2_canonical import (
    RedBarV2CanonicalPersistenceService,
    SQLiteRedBarV2CanonicalRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_evidence_verification import (
    ReservationCorruptionError,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_models import (
    ReservationOutcome,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_observability import (
    SQLiteReservationObservabilityRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_repository import (
    SQLiteCanonicalReservationRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_service import (
    OBSERVATIONAL_OWNER_ID,
)
from red_bar_lab.tests.red_bar_v2_persistence_fixtures import (
    RESOLVED_AT,
    UNDERLYING,
    make_resolution,
)


def _setup(path: Path):
    resolution, parity = make_resolution()
    RedBarV2CanonicalPersistenceService(
        SQLiteRedBarV2CanonicalRepository(path),
        clock=lambda: RESOLVED_AT,
    ).persist(resolution=resolution, parity=parity, instrument_key=UNDERLYING)
    assert resolution.section_3 is not None
    repository = SQLiteCanonicalReservationRepository(path)
    acquired = repository.reserve(
        bundle_id=resolution.section_3.bundle_id,
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=resolution.section_3.created_at,
        lease_seconds=30,
        feature_enabled=True,
    )
    assert acquired.outcome is ReservationOutcome.ACQUIRED
    assert acquired.reservation is not None
    return resolution.section_3, repository, acquired.reservation


def test_valid_reserved_released_and_expired_chains(tmp_path: Path):
    bundle, repository, reservation = _setup(tmp_path / "released.db")
    released = repository.release(
        reservation_id=reservation.reservation_id,
        owner_id=reservation.owner_id,
        released_at=reservation.reserved_at + timedelta(seconds=1),
        reason_code="OPERATOR_RELEASE",
    )
    assert released.outcome is ReservationOutcome.RELEASED
    result = SQLiteReservationObservabilityRepository(tmp_path / "released.db").latest_for_bundle(bundle_id=bundle.bundle_id)
    assert result.status == "RESERVATION_DATA_AVAILABLE"

    bundle2, repository2, reservation2 = _setup(tmp_path / "expired.db")
    expired = repository2.release(
        reservation_id=reservation2.reservation_id,
        owner_id=reservation2.owner_id,
        released_at=reservation2.lease_expires_at,
        reason_code="IGNORED",
    )
    assert expired.outcome is ReservationOutcome.EXPIRED
    result2 = SQLiteReservationObservabilityRepository(tmp_path / "expired.db").latest_for_bundle(bundle_id=bundle2.bundle_id)
    assert result2.status == "RESERVATION_DATA_AVAILABLE"


def test_zero_events_is_corrupt_and_blocks_replay_release_and_active(tmp_path: Path):
    bundle, repository, reservation = _setup(tmp_path / "db.sqlite")
    with sqlite3.connect(tmp_path / "db.sqlite") as conn:
        conn.execute("DELETE FROM canonical_red_bar_v2_bundle_reservation_events WHERE reservation_id=?", (reservation.reservation_id,))
    replay = repository.reserve(
        bundle_id=bundle.bundle_id,
        owner_id=reservation.owner_id,
        requested_at=reservation.reserved_at + timedelta(seconds=1),
        lease_seconds=30,
        feature_enabled=True,
    )
    assert replay.outcome is ReservationOutcome.RESERVATION_CORRUPT
    released = repository.release(
        reservation_id=reservation.reservation_id,
        owner_id=reservation.owner_id,
        released_at=reservation.reserved_at + timedelta(seconds=1),
        reason_code="RELEASE",
    )
    assert released.outcome is ReservationOutcome.RESERVATION_CORRUPT
    with pytest.raises(ReservationCorruptionError, match="no lifecycle event history"):
        repository.get_active(
            bundle_id=bundle.bundle_id,
            at=reservation.reserved_at + timedelta(seconds=1),
        )
    observed = SQLiteReservationObservabilityRepository(tmp_path / "db.sqlite").latest_for_bundle(bundle_id=bundle.bundle_id)
    assert observed.status == "RESERVATION_DATA_CORRUPT"
    assert observed.reservation is None and observed.events == ()


def test_terminal_event_on_reserved_row_is_corrupt_without_mutation(tmp_path: Path):
    bundle, repository, reservation = _setup(tmp_path / "db.sqlite")
    with sqlite3.connect(tmp_path / "db.sqlite") as conn:
        acquired = conn.execute("SELECT * FROM canonical_red_bar_v2_bundle_reservation_events WHERE reservation_id=?", (reservation.reservation_id,)).fetchone()
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundle_reservation_events SET event_type='RESERVATION_RELEASED' WHERE event_id=?",
            (acquired[0],),
        )
        before = conn.execute("SELECT state,payload_sha256 FROM canonical_red_bar_v2_bundle_reservations WHERE reservation_id=?", (reservation.reservation_id,)).fetchone()
    result = repository.release(
        reservation_id=reservation.reservation_id,
        owner_id=reservation.owner_id,
        released_at=reservation.reserved_at + timedelta(seconds=1),
        reason_code="RELEASE",
    )
    assert result.outcome is ReservationOutcome.RESERVATION_CORRUPT
    with sqlite3.connect(tmp_path / "db.sqlite") as conn:
        after = conn.execute("SELECT state,payload_sha256 FROM canonical_red_bar_v2_bundle_reservations WHERE reservation_id=?", (reservation.reservation_id,)).fetchone()
    assert tuple(after) == tuple(before)
    observed = SQLiteReservationObservabilityRepository(tmp_path / "db.sqlite").latest_for_bundle(bundle_id=bundle.bundle_id)
    assert observed.status == "RESERVATION_DATA_CORRUPT"


def test_missing_bundle_table_is_corrupt_not_storage_unavailable(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    repository = SQLiteCanonicalReservationRepository(path)
    result = repository.reserve(
        bundle_id="MISSING",
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=RESOLVED_AT,
        lease_seconds=30,
        feature_enabled=True,
    )
    assert result.outcome is ReservationOutcome.BUNDLE_CORRUPT
    assert result.reason_code == "MISSING_CANONICAL_BUNDLE_TABLE"


def test_no_reservation_and_missing_database_statuses_are_distinct(tmp_path: Path):
    missing = SQLiteReservationObservabilityRepository(tmp_path / "missing.db").latest_for_bundle(bundle_id="B")
    assert missing.status == "RESERVATION_DATABASE_UNAVAILABLE"
    path = tmp_path / "empty.db"
    SQLiteCanonicalReservationRepository(path)
    empty = SQLiteReservationObservabilityRepository(path).latest_for_bundle(bundle_id="B")
    assert empty.status == "NO_RESERVATION"
