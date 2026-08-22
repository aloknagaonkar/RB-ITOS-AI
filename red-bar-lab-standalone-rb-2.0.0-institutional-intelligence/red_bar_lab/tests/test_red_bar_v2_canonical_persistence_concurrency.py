from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3
from threading import Barrier

from red_bar_lab.services.red_bar_v2_canonical import (
    CanonicalPersistenceConflictError,
    PersistenceOutcome,
    RedBarV2CanonicalPersistenceService,
    SQLiteRedBarV2CanonicalRepository,
)
from red_bar_lab.tests.red_bar_v2_persistence_fixtures import UNDERLYING, make_resolution


def test_two_identical_concurrent_inserts_produce_one_immutable_state(tmp_path):
    path = tmp_path / "red_bar.db"
    repository = SQLiteRedBarV2CanonicalRepository(path)
    resolution, parity = make_resolution(provisional=True)
    barrier = Barrier(2)

    def persist_once():
        barrier.wait()
        return RedBarV2CanonicalPersistenceService(repository).persist(
            resolution=resolution,
            parity=parity,
            instrument_key=UNDERLYING,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: persist_once(), range(2)))

    assert {item.outcome for item in results} == {
        PersistenceOutcome.INSERTED,
        PersistenceOutcome.IDEMPOTENT_REPLAY,
    }
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_resolutions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundles").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_events").fetchone()[0] == 1


def test_two_conflicting_concurrent_inserts_preserve_one_complete_state(tmp_path):
    path = tmp_path / "red_bar.db"
    repository = SQLiteRedBarV2CanonicalRepository(path)
    resolution, parity = make_resolution()
    conflicting = replace(parity, matches=False, mismatches=("midpoint_aligned",))
    barrier = Barrier(2)

    def persist_once(selected_parity):
        barrier.wait()
        try:
            return RedBarV2CanonicalPersistenceService(repository).persist(
                resolution=resolution,
                parity=selected_parity,
                instrument_key=UNDERLYING,
            )
        except CanonicalPersistenceConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(persist_once, value) for value in (parity, conflicting)]
        results = tuple(item.result() for item in futures)

    assert sum(isinstance(item, CanonicalPersistenceConflictError) for item in results) == 1
    assert sum(getattr(item, "outcome", None) is PersistenceOutcome.INSERTED for item in results) == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_resolutions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundles").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_events").fetchone()[0] == 1
