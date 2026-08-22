import sqlite3

from red_bar_lab.services.red_bar_v2_canonical import (
    PersistenceOutcome,
    RedBarV2CanonicalPersistenceService,
    SQLiteRedBarV2CanonicalRepository,
    benchmark_persistence_call,
)
from red_bar_lab.tests.red_bar_v2_persistence_fixtures import (
    TRADING_DATE,
    UNDERLYING,
    make_resolution,
)


def _persist(repository, resolution, parity):
    return RedBarV2CanonicalPersistenceService(repository).persist(
        resolution=resolution,
        parity=parity,
        instrument_key=UNDERLYING,
    )


def test_allowed_resolution_bundle_and_event_round_trip(tmp_path):
    path = tmp_path / "red_bar.db"
    repository = SQLiteRedBarV2CanonicalRepository(path)
    resolution, parity = make_resolution()

    result = _persist(repository, resolution, parity)

    assert result.outcome is PersistenceOutcome.INSERTED
    assert result.resolution_inserted is True
    assert result.bundle_inserted is True
    assert result.lifecycle_event_inserted is True
    stored = repository.get_resolution(result.resolution_id)
    assert stored is not None
    assert stored.section_1 == resolution.section_1
    assert stored.section_2 == resolution.section_2
    assert stored.section_3 == resolution.section_3
    assert stored.parity == parity
    assert repository.get_bundle(result.bundle_id) == resolution.section_3
    assert repository.get_bundle_by_signal_id(resolution.section_3.signal_id) == resolution.section_3
    events = repository.list_bundle_events(result.bundle_id)
    assert len(events) == 1
    assert events[0].event_type.value == "BUNDLE_AVAILABLE"
    assert events[0].source == "CANONICAL_RESOLVER"
    assert events[0].reason_code == "CANONICAL_ADMISSION_ALLOWED"


def test_identical_retry_is_idempotent_across_restart(tmp_path):
    path = tmp_path / "red_bar.db"
    resolution, parity = make_resolution(provisional=True)
    first_repository = SQLiteRedBarV2CanonicalRepository(path)
    first = _persist(first_repository, resolution, parity)

    restarted = SQLiteRedBarV2CanonicalRepository(path)
    replayed = _persist(restarted, resolution, parity)

    assert replayed.resolution_id == first.resolution_id
    assert replayed.outcome is PersistenceOutcome.IDEMPOTENT_REPLAY
    assert replayed.resolution_inserted is False
    assert replayed.bundle_inserted is False
    assert replayed.lifecycle_event_inserted is False
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_resolutions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundles").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM canonical_red_bar_v2_bundle_events").fetchone()[0] == 1


def test_waiting_and_rejected_resolutions_persist_without_bundle(tmp_path):
    repository = SQLiteRedBarV2CanonicalRepository(tmp_path / "red_bar.db")
    for allowed in (None, False):
        resolution, parity = make_resolution(allowed=allowed)
        result = _persist(repository, resolution, parity)
        assert result.outcome is PersistenceOutcome.INSERTED
        assert result.bundle_id is None
        stored = repository.get_resolution(result.resolution_id)
        assert stored is not None
        assert stored.section_3 is None

    rows = repository.list_session_resolutions(
        instrument_key=UNDERLYING,
        trading_date=TRADING_DATE,
    )
    assert len(rows) == 2


def test_confirmed_reversal_bundle_round_trip(tmp_path):
    repository = SQLiteRedBarV2CanonicalRepository(tmp_path / "red_bar.db")
    resolution, parity = make_resolution(confirmed_reversal=True)
    result = _persist(repository, resolution, parity)
    stored = repository.get_resolution(result.resolution_id)
    assert stored is not None
    assert stored.section_3 == resolution.section_3
    assert stored.section_2.entry_type.value == "REVERSAL"
    assert stored.section_2.trend_strength.value == "CONFIRMED"


def test_prepared_local_persistence_benchmark_is_reported(tmp_path):
    repository = SQLiteRedBarV2CanonicalRepository(tmp_path / "red_bar.db")
    resolution, parity = make_resolution()
    _persist(repository, resolution, parity)
    benchmark = benchmark_persistence_call(
        10,
        lambda: _persist(repository, resolution, parity),
    )
    assert benchmark.iterations == 10
    assert benchmark.minimum_ms >= 0
    assert benchmark.maximum_ms >= benchmark.minimum_ms
