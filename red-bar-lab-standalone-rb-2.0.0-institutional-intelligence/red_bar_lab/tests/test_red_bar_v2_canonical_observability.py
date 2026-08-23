from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from red_bar_lab.services.red_bar_v2_canonical import (
    RedBarV2CanonicalPersistenceService,
    SQLiteRedBarV2CanonicalRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.observability_repository import (
    ObservabilityResolutionRecord,
    SQLiteRedBarV2CanonicalObservabilityRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.observability_service import (
    CLOCK_SKEW_TOLERANCE_SECONDS,
    RedBarV2CanonicalObservabilityService,
    _freshness,
    _section_3,
)
from red_bar_lab.services.red_bar_v2_canonical.persistence_models import (
    CanonicalPersistenceCorruptionError,
    CanonicalPersistenceUnavailableError,
)
from red_bar_lab.tests.red_bar_v2_persistence_fixtures import (
    EVALUATED_AT,
    IST,
    RESOLVED_AT,
    UNDERLYING,
    make_resolution,
)

INDIA = ZoneInfo("Asia/Kolkata")


def _persist(path: Path, *, allowed: bool | None = True, provisional: bool = False, confirmed_reversal: bool = False) -> None:
    resolution, parity = make_resolution(
        allowed=allowed,
        provisional=provisional,
        confirmed_reversal=confirmed_reversal,
    )
    RedBarV2CanonicalPersistenceService(
        SQLiteRedBarV2CanonicalRepository(path),
        clock=lambda: RESOLVED_AT,
    ).persist(resolution=resolution, parity=parity, instrument_key=UNDERLYING)


def test_missing_database_is_unavailable_and_not_created(tmp_path: Path):
    path = tmp_path / "missing" / "red_bar_strategy.db"
    repository = SQLiteRedBarV2CanonicalObservabilityRepository(path)
    with pytest.raises(CanonicalPersistenceUnavailableError):
        repository.recent_resolutions(instrument_key=UNDERLYING, limit=25)
    assert not path.exists()
    assert not path.parent.exists()


def test_missing_canonical_tables_returns_empty_without_schema_creation(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY)")
    before = path.stat().st_mtime_ns
    repository = SQLiteRedBarV2CanonicalObservabilityRepository(path)
    assert repository.recent_resolutions(instrument_key=UNDERLYING, limit=25) == ()
    assert path.stat().st_mtime_ns == before
    with sqlite3.connect(path) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"unrelated"}


def test_real_persistence_is_newest_first_filtered_and_read_only(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    before = path.stat().st_mtime_ns
    repository = SQLiteRedBarV2CanonicalObservabilityRepository(path)
    records = repository.recent_resolutions(instrument_key=UNDERLYING, limit=1000)
    assert len(records) == 1
    assert records[0].envelope.instrument_key == UNDERLYING
    assert repository.recent_resolutions(instrument_key="OTHER", limit=25) == ()
    assert repository.recent_resolutions(
        instrument_key=UNDERLYING,
        trading_date=records[0].envelope.trading_date,
        limit=25,
    ) == records
    assert path.stat().st_mtime_ns == before


def test_resolution_digest_corruption_is_distinct(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE canonical_red_bar_v2_resolutions SET payload_sha256='bad'")
    with pytest.raises(CanonicalPersistenceCorruptionError, match="resolution payload digest mismatch"):
        SQLiteRedBarV2CanonicalObservabilityRepository(path).recent_resolutions(
            instrument_key=UNDERLYING,
            limit=25,
        )


def test_bundle_projection_mismatch_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE canonical_red_bar_v2_bundles SET option_side='PE'")
    with pytest.raises(CanonicalPersistenceCorruptionError, match="bundle projection mismatch: option_side"):
        SQLiteRedBarV2CanonicalObservabilityRepository(path).recent_resolutions(
            instrument_key=UNDERLYING,
            limit=25,
        )


def test_lifecycle_projection_mismatch_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository = SQLiteRedBarV2CanonicalObservabilityRepository(path)
    record = repository.latest_resolution(instrument_key=UNDERLYING)
    assert record is not None and record.envelope.section_3 is not None
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE canonical_red_bar_v2_bundle_events SET source='WRONG'")
    with pytest.raises(CanonicalPersistenceCorruptionError, match="lifecycle event projection mismatch: source"):
        repository.bundle_events(bundle_id=record.envelope.section_3.bundle_id)


def test_naive_persisted_at_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE canonical_red_bar_v2_resolutions SET persisted_at='2026-08-24T10:05:01'")
    with pytest.raises(CanonicalPersistenceCorruptionError, match="naive persisted_at"):
        SQLiteRedBarV2CanonicalObservabilityRepository(path).recent_resolutions(
            instrument_key=UNDERLYING,
            limit=25,
        )


def test_india_market_fresh_stale_and_historical(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    record = SQLiteRedBarV2CanonicalObservabilityRepository(path).latest_resolution(instrument_key=UNDERLYING)
    assert record is not None
    assert _freshness(record, EVALUATED_AT + timedelta(seconds=60))[0] == "FRESH"
    assert _freshness(record, EVALUATED_AT + timedelta(seconds=121))[0] == "STALE"
    assert _freshness(record, EVALUATED_AT + timedelta(days=1))[0] == "HISTORICAL"


def test_utc_india_midnight_boundary_uses_market_date(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    record = SQLiteRedBarV2CanonicalObservabilityRepository(path).latest_resolution(instrument_key=UNDERLYING)
    assert record is not None
    now_utc = datetime(2026, 8, 24, 4, 36, tzinfo=timezone.utc)
    freshness, _ = _freshness(record, now_utc)
    assert freshness in {"FRESH", "STALE"}


def test_negative_age_beyond_tolerance_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    record = SQLiteRedBarV2CanonicalObservabilityRepository(path).latest_resolution(instrument_key=UNDERLYING)
    assert record is not None
    with pytest.raises(CanonicalPersistenceCorruptionError, match="materially in the future"):
        _freshness(record, EVALUATED_AT - timedelta(seconds=CLOCK_SKEW_TOLERANCE_SECONDS + 1))


def test_complete_section_3_and_lifecycle_status(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository = SQLiteRedBarV2CanonicalObservabilityRepository(path)
    record = repository.latest_resolution(instrument_key=UNDERLYING)
    assert record is not None and record.envelope.section_3 is not None
    events = repository.bundle_events(bundle_id=record.envelope.section_3.bundle_id)
    section = _section_3(record, events)
    assert section.lifecycle_status == "AVAILABLE"
    assert section.event_history[0].event_type == "BUNDLE_AVAILABLE"
    assert section.underlying_instrument == UNDERLYING
    assert section.direction == "BULLISH"
    assert section.option_side == "CE"
    assert section.entry_type == "INITIAL"
    assert section.evaluation_timeframe == "1m"


@pytest.mark.parametrize("allowed", [None, False])
def test_waiting_and_rejected_have_no_bundle(tmp_path: Path, allowed: bool | None):
    path = tmp_path / f"{allowed}.db"
    _persist(path, allowed=allowed)
    record = SQLiteRedBarV2CanonicalObservabilityRepository(path).latest_resolution(instrument_key=UNDERLYING)
    assert record is not None
    section = _section_3(record, ())
    assert section.bundle_available is False
    assert section.bundle_id is None
    assert "not ALLOWED" in section.explanation


def test_service_disabled_is_true_noop(tmp_path: Path):
    path = tmp_path / "never-created.db"
    service = RedBarV2CanonicalObservabilityService(
        SQLiteRedBarV2CanonicalObservabilityRepository(path),
        database_path=path,
    )
    view = service.load(
        instrument_key=UNDERLYING,
        feature_enabled=False,
        now=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )
    assert view.status.availability == "SHADOW_DISABLED"
    assert view.status.authority == "LEGACY_RED_BAR_V2"
    assert view.status.canonical_authority == "NONE"
    assert view.status.runtime_telemetry == "NOT DURABLY AVAILABLE"
    assert not path.exists()


def test_naive_now_maps_to_read_failed(tmp_path: Path):
    service = RedBarV2CanonicalObservabilityService(
        SQLiteRedBarV2CanonicalObservabilityRepository(tmp_path / "missing.db"),
        database_path=tmp_path / "missing.db",
    )
    view = service.load(
        instrument_key=UNDERLYING,
        feature_enabled=True,
        now=datetime(2026, 8, 24, 10, 0),
    )
    assert view.status.availability == "CANONICAL_READ_FAILED"
    assert view.section_1 is None


def test_query_limit_is_bounded_and_parameterized_source():
    source = Path("red_bar_lab/services/red_bar_v2_canonical/observability_repository.py").read_text(encoding="utf-8")
    assert "min(max(int(limit), 1), 100)" in source
    assert "WHERE instrument_key=?" in source
    assert "AND trading_date=?" in source
    assert "LIMIT ?" in source
    assert "mode=ro" in source
    assert "CREATE TABLE" not in source
    assert "INSERT INTO" not in source
    assert "UPDATE " not in source
    assert "DELETE FROM" not in source


def test_page_is_observational_and_has_required_authority_banner():
    source = Path("red_bar_lab/ui/pages/red_bar_v2_validation.py").read_text(encoding="utf-8")
    assert "NO — canonical processing is observational only" in source
    assert "Legacy Red Bar V2 remains execution authority" in source
    assert "CANONICAL_READ_FAILED" in source
    forbidden = (
        "resolve_red_bar_v2_canonical",
        "RedBarV2CanonicalShadowCoordinator",
        "get_red_bar_v2_shadow_runtime",
        "paper_signal_bridge",
        "portfolio_admission",
        "order_service",
        "position_monitor",
        "exit_management",
    )
    for value in forbidden:
        assert value not in source


def test_page_uses_arrow_safe_string_frames_and_runtime_telemetry_label():
    source = Path("red_bar_lab/ui/pages/red_bar_v2_validation.py").read_text(encoding="utf-8")
    assert '.astype("string")' in source
    assert 'dtype="string"' in source
    assert "Runtime telemetry" in source
    assert "Bundle lifecycle status" in source
    assert "Audit event type" in source
