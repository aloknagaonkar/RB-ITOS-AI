from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from threading import Barrier, Thread

import pytest

from red_bar_lab.domain.red_bar_v2 import BundleLifecycleStatus
from red_bar_lab.services.red_bar_v2_canonical import (
    RedBarV2CanonicalPersistenceService,
    SQLiteRedBarV2CanonicalRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_identity import build_reservation_id
from red_bar_lab.services.red_bar_v2_canonical.reservation_models import (
    CanonicalBundleReservation,
    ReservationOutcome,
    ReservationState,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_observability import SQLiteReservationObservabilityRepository
from red_bar_lab.services.red_bar_v2_canonical.reservation_policy import evaluate_reservation_eligibility
from red_bar_lab.services.red_bar_v2_canonical.reservation_repository import SQLiteCanonicalReservationRepository
from red_bar_lab.services.red_bar_v2_canonical.reservation_service import (
    OBSERVATIONAL_OWNER_ID,
    RedBarV2CanonicalReservationService,
)
from red_bar_lab.tests.red_bar_v2_persistence_fixtures import (
    RESOLVED_AT,
    UNDERLYING,
    make_resolution,
)


def _canonical_database(path: Path):
    resolution, parity = make_resolution()
    RedBarV2CanonicalPersistenceService(
        SQLiteRedBarV2CanonicalRepository(path),
        clock=lambda: RESOLVED_AT,
    ).persist(
        resolution=resolution,
        parity=parity,
        instrument_key=UNDERLYING,
    )
    assert resolution.section_3 is not None
    return resolution.section_3


def _reservation(bundle, *, owner: str = OBSERVATIONAL_OWNER_ID) -> CanonicalBundleReservation:
    reserved_at = RESOLVED_AT + timedelta(seconds=1)
    return CanonicalBundleReservation(
        reservation_id=build_reservation_id(
            bundle_id=bundle.bundle_id,
            idempotency_key=bundle.idempotency_key,
            owner_id=owner,
            lease_epoch=reserved_at,
        ),
        bundle_id=bundle.bundle_id,
        signal_id=bundle.signal_id,
        idempotency_key=bundle.idempotency_key,
        strategy_id=bundle.strategy_id,
        strategy_version=bundle.strategy_version,
        instrument_key=bundle.instrument_key or "",
        trading_date=bundle.trading_date,
        direction=bundle.direction,
        option_side=bundle.option_side,
        entry_type=bundle.entry_type,
        owner_id=owner,
        state=ReservationState.RESERVED,
        reserved_at=reserved_at,
        lease_expires_at=reserved_at + timedelta(seconds=30),
        released_at=None,
        release_reason=None,
    )


def test_valid_reservation_model_and_deterministic_identity(tmp_path: Path):
    bundle = _canonical_database(tmp_path / "db.sqlite")
    reservation = _reservation(bundle)
    assert reservation.state is ReservationState.RESERVED
    same_instant = reservation.reserved_at.astimezone(timezone.utc)
    assert reservation.reservation_id == build_reservation_id(
        bundle_id=bundle.bundle_id,
        idempotency_key=bundle.idempotency_key,
        owner_id=OBSERVATIONAL_OWNER_ID,
        lease_epoch=same_instant,
    )


def test_reservation_model_rejects_invalid_timestamps_and_release_fields(tmp_path: Path):
    bundle = _canonical_database(tmp_path / "db.sqlite")
    valid = _reservation(bundle)
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(valid, reserved_at=valid.reserved_at.replace(tzinfo=None))
    with pytest.raises(ValueError, match="later"):
        replace(valid, lease_expires_at=valid.reserved_at)
    with pytest.raises(ValueError, match="release fields"):
        replace(valid, released_at=valid.reserved_at, release_reason="BAD")
    with pytest.raises(ValueError, match="terminal reservation"):
        replace(valid, state=ReservationState.RELEASED)


def test_eligibility_is_pure_and_time_bounded(tmp_path: Path):
    bundle = _canonical_database(tmp_path / "db.sqlite")
    eligible = evaluate_reservation_eligibility(
        bundle=bundle,
        evaluated_at=bundle.created_at + timedelta(seconds=10),
        feature_enabled=True,
    )
    assert eligible.eligible and eligible.reason_code == "ELIGIBLE"
    assert evaluate_reservation_eligibility(
        bundle=bundle,
        evaluated_at=bundle.created_at + timedelta(seconds=121),
        feature_enabled=True,
    ).reason_code == "BUNDLE_TOO_OLD"
    assert evaluate_reservation_eligibility(
        bundle=bundle,
        evaluated_at=bundle.created_at - timedelta(seconds=6),
        feature_enabled=True,
    ).reason_code == "BUNDLE_IN_FUTURE"
    assert evaluate_reservation_eligibility(
        bundle=bundle,
        evaluated_at=bundle.created_at,
        feature_enabled=False,
    ).reason_code == "FEATURE_DISABLED"
    unavailable = replace(bundle, lifecycle_status=BundleLifecycleStatus.CONSUMED)
    assert evaluate_reservation_eligibility(
        bundle=unavailable,
        evaluated_at=bundle.created_at,
        feature_enabled=True,
    ).reason_code == "BUNDLE_NOT_AVAILABLE"


def test_first_owner_acquires_replay_is_idempotent_and_other_owner_conflicts(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle = _canonical_database(path)
    repository = SQLiteCanonicalReservationRepository(path)
    requested_at = bundle.created_at + timedelta(seconds=10)
    first = repository.reserve(
        bundle_id=bundle.bundle_id,
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=requested_at,
        lease_seconds=30,
        feature_enabled=True,
    )
    replay = repository.reserve(
        bundle_id=bundle.bundle_id,
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=requested_at + timedelta(seconds=1),
        lease_seconds=30,
        feature_enabled=True,
    )
    other = repository.reserve(
        bundle_id=bundle.bundle_id,
        owner_id="OTHER_OWNER",
        requested_at=requested_at + timedelta(seconds=2),
        lease_seconds=30,
        feature_enabled=True,
    )
    assert first.outcome is ReservationOutcome.ACQUIRED
    assert replay.outcome is ReservationOutcome.IDEMPOTENT_REPLAY
    assert replay.reservation == first.reservation
    assert other.outcome is ReservationOutcome.ALREADY_RESERVED
    with sqlite3.connect(path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_reservations WHERE bundle_id=? AND state='RESERVED'",
            (bundle.bundle_id,),
        ).fetchone()[0]
    assert count == 1


def test_expired_lease_transitions_and_new_owner_acquires(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle = _canonical_database(path)
    repository = SQLiteCanonicalReservationRepository(path)
    requested_at = bundle.created_at + timedelta(seconds=5)
    first = repository.reserve(
        bundle_id=bundle.bundle_id,
        owner_id="OWNER_A",
        requested_at=requested_at,
        lease_seconds=5,
        feature_enabled=True,
    )
    second = repository.reserve(
        bundle_id=bundle.bundle_id,
        owner_id="OWNER_B",
        requested_at=requested_at + timedelta(seconds=6),
        lease_seconds=30,
        feature_enabled=True,
    )
    assert first.outcome is ReservationOutcome.ACQUIRED
    assert second.outcome is ReservationOutcome.ACQUIRED
    with sqlite3.connect(path) as conn:
        states = [row[0] for row in conn.execute(
            "SELECT state FROM canonical_red_bar_v2_bundle_reservations WHERE bundle_id=? ORDER BY created_at",
            (bundle.bundle_id,),
        )]
    assert states == ["EXPIRED", "RESERVED"]


def test_release_requires_owner_and_is_idempotent(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle = _canonical_database(path)
    repository = SQLiteCanonicalReservationRepository(path)
    acquired = repository.reserve(
        bundle_id=bundle.bundle_id,
        owner_id="OWNER_A",
        requested_at=bundle.created_at + timedelta(seconds=5),
        lease_seconds=30,
        feature_enabled=True,
    )
    assert acquired.reservation is not None
    denied = repository.release(
        reservation_id=acquired.reservation.reservation_id,
        owner_id="OWNER_B",
        released_at=bundle.created_at + timedelta(seconds=10),
        reason_code="DONE",
    )
    released = repository.release(
        reservation_id=acquired.reservation.reservation_id,
        owner_id="OWNER_A",
        released_at=bundle.created_at + timedelta(seconds=10),
        reason_code="VALIDATION_COMPLETE",
    )
    replay = repository.release(
        reservation_id=acquired.reservation.reservation_id,
        owner_id="OWNER_A",
        released_at=bundle.created_at + timedelta(seconds=11),
        reason_code="VALIDATION_COMPLETE",
    )
    assert denied.reason_code == "OWNER_MISMATCH"
    assert released.outcome is ReservationOutcome.RELEASED
    assert replay.outcome is ReservationOutcome.IDEMPOTENT_REPLAY


def test_concurrent_different_owners_produce_one_winner(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle = _canonical_database(path)
    SQLiteCanonicalReservationRepository(path)
    barrier = Barrier(2)
    outcomes: list[ReservationOutcome] = []

    def attempt(owner: str) -> None:
        repository = SQLiteCanonicalReservationRepository(path)
        barrier.wait()
        result = repository.reserve(
            bundle_id=bundle.bundle_id,
            owner_id=owner,
            requested_at=bundle.created_at + timedelta(seconds=10),
            lease_seconds=30,
            feature_enabled=True,
        )
        outcomes.append(result.outcome)

    threads = [Thread(target=attempt, args=("OWNER_A",)), Thread(target=attempt, args=("OWNER_B",))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count(ReservationOutcome.ACQUIRED) == 1
    assert outcomes.count(ReservationOutcome.ALREADY_RESERVED) == 1


def test_feature_disabled_instantiates_no_repository_and_writes_nothing(tmp_path: Path):
    path = tmp_path / "never-created.db"
    service = RedBarV2CanonicalReservationService(None, enabled=False)
    result = service.reserve(
        bundle_id="BUNDLE",
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=datetime.now(timezone.utc),
    )
    assert result.outcome is ReservationOutcome.RESERVATION_DISABLED
    assert not path.exists()


def test_missing_and_corrupt_bundle_are_distinct(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle = _canonical_database(path)
    repository = SQLiteCanonicalReservationRepository(path)
    missing = repository.reserve(
        bundle_id="MISSING",
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=bundle.created_at,
        lease_seconds=30,
        feature_enabled=True,
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundles SET payload_sha256='bad' WHERE bundle_id=?",
            (bundle.bundle_id,),
        )
    corrupt = repository.reserve(
        bundle_id=bundle.bundle_id,
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=bundle.created_at,
        lease_seconds=30,
        feature_enabled=True,
    )
    assert missing.outcome is ReservationOutcome.BUNDLE_UNAVAILABLE
    assert corrupt.outcome is ReservationOutcome.BUNDLE_CORRUPT


def test_reservation_does_not_modify_immutable_bundle_rows(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle = _canonical_database(path)
    repository = SQLiteCanonicalReservationRepository(path)
    with sqlite3.connect(path) as conn:
        before = conn.execute(
            "SELECT payload_json,payload_sha256 FROM canonical_red_bar_v2_bundles WHERE bundle_id=?",
            (bundle.bundle_id,),
        ).fetchone()
    repository.reserve(
        bundle_id=bundle.bundle_id,
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=bundle.created_at + timedelta(seconds=5),
        lease_seconds=30,
        feature_enabled=True,
    )
    with sqlite3.connect(path) as conn:
        after = conn.execute(
            "SELECT payload_json,payload_sha256 FROM canonical_red_bar_v2_bundles WHERE bundle_id=?",
            (bundle.bundle_id,),
        ).fetchone()
    assert before == after


def test_read_only_observability_loads_scalar_evidence_without_writes(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    bundle = _canonical_database(path)
    repository = SQLiteCanonicalReservationRepository(path)
    repository.reserve(
        bundle_id=bundle.bundle_id,
        owner_id=OBSERVATIONAL_OWNER_ID,
        requested_at=bundle.created_at + timedelta(seconds=5),
        lease_seconds=30,
        feature_enabled=True,
    )
    before = path.stat().st_mtime_ns
    result = SQLiteReservationObservabilityRepository(path).latest_for_bundle(
        bundle_id=bundle.bundle_id
    )
    assert result.status == "RESERVATION_DATA_AVAILABLE"
    assert result.reservation is not None
    assert result.reservation.state is ReservationState.RESERVED
    assert result.events and result.events[0].event_type == "RESERVATION_ACQUIRED"
    assert path.stat().st_mtime_ns == before


def test_ui_section_is_read_only_and_execution_neutral():
    source = Path("red_bar_lab/ui/pages/red_bar_v2_validation.py").read_text(encoding="utf-8")
    # Match on the section title only. The leading ordinal moves whenever a
    # section is inserted above it and is not part of the read-only contract.
    assert "Reservation Boundary" in source
    assert "RESERVED does not mean ordered or executed" in source
    assert "No capital, order or position was created" in source
    assert "SQLiteCanonicalReservationRepository" not in source
    for forbidden in (
        "paper_signal_bridge",
        "portfolio_admission",
        "order_service",
        "position_monitor",
        "exit_management",
    ):
        assert forbidden not in source
