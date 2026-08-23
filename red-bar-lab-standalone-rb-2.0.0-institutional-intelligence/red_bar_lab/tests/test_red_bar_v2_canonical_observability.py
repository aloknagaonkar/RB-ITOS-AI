from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from red_bar_lab.services.red_bar_v2_canonical.observability_repository import (
    SQLiteRedBarV2CanonicalObservabilityRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.observability_service import (
    RedBarV2CanonicalObservabilityService,
)
from red_bar_lab.services.red_bar_v2_canonical.persistence_models import (
    CanonicalPersistenceUnavailableError,
)

UNDERLYING = "NSE_INDEX|Nifty 50"


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


def test_query_limit_is_bounded_and_parameterized_source():
    source = Path(
        "red_bar_lab/services/red_bar_v2_canonical/observability_repository.py"
    ).read_text(encoding="utf-8")
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
    source = Path("red_bar_lab/ui/pages/red_bar_v2_validation.py").read_text(
        encoding="utf-8"
    )
    assert "NO — canonical processing is observational only" in source
    assert "Legacy Red Bar V2 remains execution authority" in source
    assert "LEGACY_RED_BAR_V2" not in source or "Execution authority" in source
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
    source = Path("red_bar_lab/ui/pages/red_bar_v2_validation.py").read_text(
        encoding="utf-8"
    )
    assert '.astype("string")' in source
    assert 'dtype="string"' in source
    assert "Runtime telemetry" in source
    assert "NOT DURABLY AVAILABLE" in Path(
        "red_bar_lab/services/red_bar_v2_canonical/observability_models.py"
    ).read_text(encoding="utf-8")
