from dataclasses import replace
import sqlite3

import pytest

from red_bar_lab.services.red_bar_v2_canonical import (
    CanonicalPersistenceConflictError,
    CanonicalPersistenceCorruptionError,
    RedBarV2CanonicalPersistenceService,
    SQLiteRedBarV2CanonicalRepository,
)
from red_bar_lab.tests.red_bar_v2_persistence_fixtures import UNDERLYING, make_resolution


def _persist(path):
    repository = SQLiteRedBarV2CanonicalRepository(path)
    resolution, parity = make_resolution()
    result = RedBarV2CanonicalPersistenceService(repository).persist(
        resolution=resolution,
        parity=parity,
        instrument_key=UNDERLYING,
    )
    return repository, resolution, parity, result


def test_same_resolution_identity_with_changed_parity_is_conflict_and_first_wins(tmp_path):
    path = tmp_path / "red_bar.db"
    repository, resolution, parity, result = _persist(path)
    conflicting_parity = replace(parity, matches=False, mismatches=("direction",))

    with pytest.raises(CanonicalPersistenceConflictError, match="resolution"):
        RedBarV2CanonicalPersistenceService(repository).persist(
            resolution=resolution,
            parity=conflicting_parity,
            instrument_key=UNDERLYING,
        )

    stored = repository.get_resolution(result.resolution_id)
    assert stored is not None
    assert stored.parity == parity
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_resolutions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundles").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_events").fetchone()[0] == 1


def test_modified_resolution_payload_is_detected(tmp_path):
    path = tmp_path / "red_bar.db"
    repository, _, _, result = _persist(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_resolutions SET payload_json='{}' WHERE resolution_id=?",
            (result.resolution_id,),
        )
        conn.commit()
    with pytest.raises(CanonicalPersistenceCorruptionError, match="digest mismatch"):
        repository.get_resolution(result.resolution_id)


def test_modified_digest_is_detected(tmp_path):
    path = tmp_path / "red_bar.db"
    repository, resolution, _, _ = _persist(path)
    bundle_id = resolution.section_3.bundle_id
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundles SET payload_sha256=? WHERE bundle_id=?",
            ("0" * 64, bundle_id),
        )
        conn.commit()
    with pytest.raises(CanonicalPersistenceCorruptionError, match="digest mismatch"):
        repository.get_bundle(bundle_id)


def test_projection_mismatch_is_detected(tmp_path):
    path = tmp_path / "red_bar.db"
    repository, _, _, result = _persist(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_resolutions SET source_replay_id='OTHER' WHERE resolution_id=?",
            (result.resolution_id,),
        )
        conn.commit()
    with pytest.raises(CanonicalPersistenceCorruptionError, match="projection mismatch"):
        repository.get_resolution(result.resolution_id)
