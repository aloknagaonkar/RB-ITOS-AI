from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from red_bar_lab.domain.red_bar_v2 import red_bar_v2_bundle_from_dict
from red_bar_lab.services.red_bar_v2_canonical import (
    RedBarV2CanonicalPersistenceService,
    SQLiteRedBarV2CanonicalRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.observability_repository import (
    SQLiteRedBarV2CanonicalObservabilityRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.observability_service import (
    CLOCK_SKEW_TOLERANCE_SECONDS,
    RedBarV2CanonicalObservabilityService,
    _freshness,
    _section_3,
)
from red_bar_lab.services.red_bar_v2_canonical.persistence_identity import (
    build_canonical_bundle_event_id,
    canonical_json,
    payload_sha256,
)
from red_bar_lab.services.red_bar_v2_canonical.persistence_models import (
    CanonicalBundleEventType,
    CanonicalBundleLifecycleEvent,
    CanonicalPersistenceCorruptionError,
    CanonicalPersistenceUnavailableError,
)
from red_bar_lab.services.red_bar_v2_canonical.persistence_serialization import (
    lifecycle_event_to_json,
)
from red_bar_lab.tests.red_bar_v2_persistence_fixtures import (
    EVALUATED_AT,
    RESOLVED_AT,
    UNDERLYING,
    make_resolution,
)

INDIA = ZoneInfo("Asia/Kolkata")


def _persist(
    path: Path,
    *,
    allowed: bool | None = True,
    provisional: bool = False,
    confirmed_reversal: bool = False,
    replay_suffix: str = "1",
) -> None:
    resolution, parity = make_resolution(
        allowed=allowed,
        provisional=provisional,
        confirmed_reversal=confirmed_reversal,
    )
    resolution = replace(
        resolution,
        source_replay_id=f"REPLAY-PERSISTENCE-{replay_suffix}",
    )
    RedBarV2CanonicalPersistenceService(
        SQLiteRedBarV2CanonicalRepository(path),
        clock=lambda: RESOLVED_AT,
    ).persist(
        resolution=resolution,
        parity=parity,
        instrument_key=UNDERLYING,
    )


def _selected(path: Path):
    repository = SQLiteRedBarV2CanonicalObservabilityRepository(path)
    record = repository.latest_resolution(instrument_key=UNDERLYING)
    assert record is not None
    assert record.envelope.section_3 is not None
    return repository, record


def _service(path: Path) -> RedBarV2CanonicalObservabilityService:
    return RedBarV2CanonicalObservabilityService(
        SQLiteRedBarV2CanonicalObservabilityRepository(path),
        database_path=path,
    )


def _select_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    import red_bar_lab.services.red_bar_v2_canonical.observability_repository as module

    statements: list[str] = []
    original_connect = sqlite3.connect

    def traced_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(
            lambda statement: statements.append(statement)
        )
        return connection

    monkeypatch.setattr(module.sqlite3, "connect", traced_connect)
    return statements


def _selects(statements: list[str]) -> list[str]:
    return [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]


def test_missing_database_is_unavailable_and_not_created(tmp_path: Path):
    path = tmp_path / "missing" / "red_bar_strategy.db"
    repository = SQLiteRedBarV2CanonicalObservabilityRepository(path)
    with pytest.raises(CanonicalPersistenceUnavailableError):
        repository.recent_resolutions(
            instrument_key=UNDERLYING,
            limit=25,
        )
    assert not path.exists()
    assert not path.parent.exists()


def test_missing_resolution_table_returns_empty_without_schema_creation(
    tmp_path: Path,
):
    path = tmp_path / "red_bar_strategy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY)")
    before = path.read_bytes()
    repository = SQLiteRedBarV2CanonicalObservabilityRepository(path)
    assert repository.recent_resolutions(
        instrument_key=UNDERLYING,
        limit=25,
    ) == ()
    assert path.read_bytes() == before
    with sqlite3.connect(path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert names == {"unrelated"}


def test_history_is_newest_first_filtered_bounded_and_read_only(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    for suffix in ("1", "2", "3"):
        _persist(path, replay_suffix=suffix)
    before = path.read_bytes()
    repository = SQLiteRedBarV2CanonicalObservabilityRepository(path)
    records = repository.recent_resolutions(
        instrument_key=UNDERLYING,
        limit=1000,
    )
    assert len(records) == 3
    resolution_ids = [record.envelope.resolution_id for record in records]
    assert resolution_ids == sorted(resolution_ids, reverse=True)
    assert repository.recent_resolutions(
        instrument_key="OTHER",
        limit=25,
    ) == ()
    assert repository.recent_resolutions(
        instrument_key=UNDERLYING,
        trading_date=records[0].envelope.trading_date,
        limit=2,
    ) == records[:2]
    assert path.read_bytes() == before


def test_history_query_count_has_no_per_row_bundle_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    path = tmp_path / "red_bar_strategy.db"
    for index in range(1, 8):
        _persist(path, replay_suffix=str(index))
    statements = _select_trace(monkeypatch)
    repository = SQLiteRedBarV2CanonicalObservabilityRepository(path)

    repository.recent_resolutions(instrument_key=UNDERLYING, limit=1)
    one_selects = _selects(statements)
    statements.clear()
    repository.recent_resolutions(instrument_key=UNDERLYING, limit=25)
    many_selects = _selects(statements)

    assert len(one_selects) == 1
    assert len(many_selects) == 1
    assert "canonical_red_bar_v2_bundles" not in many_selects[0]


def test_service_query_count_is_constant_three_selects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    path = tmp_path / "red_bar_strategy.db"
    for index in range(1, 8):
        _persist(path, replay_suffix=str(index))
    statements = _select_trace(monkeypatch)

    view = _service(path).load(
        instrument_key=UNDERLYING,
        feature_enabled=True,
        limit=25,
        now=EVALUATED_AT + timedelta(seconds=60),
    )
    selects = _selects(statements)
    assert view.status.availability == "CANONICAL_DATA_AVAILABLE"
    assert len(selects) == 3
    assert sum("canonical_red_bar_v2_resolutions" in item for item in selects) == 1
    assert sum("canonical_red_bar_v2_bundles" in item for item in selects) == 1
    assert sum("canonical_red_bar_v2_bundle_events" in item for item in selects) == 1


def test_resolution_digest_and_projection_still_validated_in_history(
    tmp_path: Path,
):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_resolutions "
            "SET payload_sha256='bad'"
        )
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="resolution payload digest mismatch",
    ):
        SQLiteRedBarV2CanonicalObservabilityRepository(
            path
        ).recent_resolutions(
            instrument_key=UNDERLYING,
            limit=25,
        )


def test_exact_embedded_stored_bundle_equality_is_required(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository, record = _selected(path)
    expected = record.envelope.section_3
    assert expected is not None
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM canonical_red_bar_v2_bundles "
            "WHERE bundle_id=?",
            (expected.bundle_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(str(row[0]))
        payload["created_at"] = (
            expected.created_at + timedelta(seconds=1)
        ).isoformat()
        changed_json = canonical_json(payload)
        changed_bundle = red_bar_v2_bundle_from_dict(json.loads(changed_json))
        assert changed_bundle.bundle_id == expected.bundle_id
        assert changed_bundle != expected
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundles "
            "SET payload_json=?,payload_sha256=? WHERE bundle_id=?",
            (
                changed_json,
                payload_sha256(changed_json),
                expected.bundle_id,
            ),
        )
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="resolution embedded bundle does not match stored bundle",
    ):
        repository.selected_bundle_evidence(expected_bundle=expected)
    view = _service(path).load(
        instrument_key=UNDERLYING,
        feature_enabled=True,
        now=EVALUATED_AT + timedelta(seconds=60),
    )
    assert view.status.availability == "CANONICAL_DATA_CORRUPT"
    assert view.section_3 is None


def test_missing_bundle_table_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository, record = _selected(path)
    expected = record.envelope.section_3
    assert expected is not None
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE canonical_red_bar_v2_bundles")
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="resolution references missing bundle table",
    ):
        repository.selected_bundle_evidence(expected_bundle=expected)


def test_missing_stored_bundle_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository, record = _selected(path)
    expected = record.envelope.section_3
    assert expected is not None
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM canonical_red_bar_v2_bundles")
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="resolution references missing bundle$",
    ):
        repository.selected_bundle_evidence(expected_bundle=expected)


def test_missing_lifecycle_table_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository, record = _selected(path)
    expected = record.envelope.section_3
    assert expected is not None
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE canonical_red_bar_v2_bundle_events")
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="bundle references missing lifecycle event table",
    ):
        repository.selected_bundle_evidence(expected_bundle=expected)


def test_no_lifecycle_rows_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository, record = _selected(path)
    expected = record.envelope.section_3
    assert expected is not None
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM canonical_red_bar_v2_bundle_events")
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="bundle has no lifecycle event history",
    ):
        repository.selected_bundle_evidence(expected_bundle=expected)


def test_missing_bundle_available_event_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository, record = _selected(path)
    expected = record.envelope.section_3
    assert expected is not None
    event_type = CanonicalBundleEventType.PERSISTENCE_CONFLICT_OBSERVED
    source = "OBSERVABILITY_TEST"
    reason = "TEST_CONFLICT"
    event = CanonicalBundleLifecycleEvent(
        event_id=build_canonical_bundle_event_id(
            bundle_id=expected.bundle_id,
            event_type=event_type.value,
            event_timestamp=expected.created_at,
            source=source,
            reason_code=reason,
        ),
        bundle_id=expected.bundle_id,
        event_type=event_type,
        event_timestamp=expected.created_at,
        source=source,
        reason_code=reason,
        metadata={},
    )
    encoded = lifecycle_event_to_json(event)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM canonical_red_bar_v2_bundle_events")
        conn.execute(
            """
            INSERT INTO canonical_red_bar_v2_bundle_events(
                event_id,bundle_id,event_type,event_timestamp,source,
                reason_code,metadata_json,metadata_sha256
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                event.event_id,
                event.bundle_id,
                event.event_type.value,
                event.event_timestamp.isoformat(),
                event.source,
                event.reason_code,
                encoded,
                payload_sha256(encoded),
            ),
        )
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="bundle has no BUNDLE_AVAILABLE lifecycle event",
    ):
        repository.selected_bundle_evidence(expected_bundle=expected)


def test_lifecycle_digest_and_projection_are_validated(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository, record = _selected(path)
    expected = record.envelope.section_3
    assert expected is not None
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundle_events "
            "SET metadata_sha256='bad'"
        )
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="lifecycle event digest mismatch",
    ):
        repository.selected_bundle_evidence(expected_bundle=expected)

    path2 = tmp_path / "projection.db"
    _persist(path2)
    repository2, record2 = _selected(path2)
    expected2 = record2.envelope.section_3
    assert expected2 is not None
    with sqlite3.connect(path2) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundle_events SET source='WRONG'"
        )
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="lifecycle event projection mismatch: source",
    ):
        repository2.selected_bundle_evidence(expected_bundle=expected2)


def test_lifecycle_payload_with_wrong_bundle_id_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository, record = _selected(path)
    expected = record.envelope.section_3
    assert expected is not None
    wrong_bundle = "RBV2-BUNDLE-WRONG"
    event_type = CanonicalBundleEventType.BUNDLE_AVAILABLE
    source = "CANONICAL_RESOLVER"
    reason = "CANONICAL_ADMISSION_ALLOWED"
    wrong = CanonicalBundleLifecycleEvent(
        event_id=build_canonical_bundle_event_id(
            bundle_id=wrong_bundle,
            event_type=event_type.value,
            event_timestamp=expected.created_at,
            source=source,
            reason_code=reason,
        ),
        bundle_id=wrong_bundle,
        event_type=event_type,
        event_timestamp=expected.created_at,
        source=source,
        reason_code=reason,
        metadata={},
    )
    encoded = lifecycle_event_to_json(wrong)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundle_events "
            "SET metadata_json=?,metadata_sha256=?",
            (encoded, payload_sha256(encoded)),
        )
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="requested_bundle_id",
    ):
        repository.selected_bundle_evidence(expected_bundle=expected)


def test_valid_selected_evidence_succeeds_and_is_read_only(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository, record = _selected(path)
    expected = record.envelope.section_3
    assert expected is not None
    before = path.read_bytes()
    selected = repository.selected_bundle_evidence(expected_bundle=expected)
    assert selected.bundle == expected
    assert selected.events
    assert selected.events[0].event_type is CanonicalBundleEventType.BUNDLE_AVAILABLE
    assert path.read_bytes() == before


@pytest.mark.parametrize("allowed", [None, False])
def test_waiting_and_rejected_require_no_lifecycle_storage(
    tmp_path: Path,
    allowed: bool | None,
):
    path = tmp_path / f"{allowed}.db"
    _persist(path, allowed=allowed)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE canonical_red_bar_v2_bundle_events")
        conn.execute("DROP TABLE canonical_red_bar_v2_bundles")
    view = _service(path).load(
        instrument_key=UNDERLYING,
        feature_enabled=True,
        now=EVALUATED_AT + timedelta(seconds=60),
    )
    assert view.status.availability == "CANONICAL_DATA_AVAILABLE"
    assert view.section_3 is not None
    assert view.section_3.bundle_available is False
    assert "not ALLOWED" in view.section_3.explanation


def test_bundle_projection_mismatch_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository, record = _selected(path)
    expected = record.envelope.section_3
    assert expected is not None
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_bundles SET option_side='PE'"
        )
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="bundle projection mismatch: option_side",
    ):
        repository.selected_bundle_evidence(expected_bundle=expected)


def test_naive_persisted_at_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE canonical_red_bar_v2_resolutions "
            "SET persisted_at='2026-08-24T10:05:01'"
        )
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="naive persisted_at",
    ):
        SQLiteRedBarV2CanonicalObservabilityRepository(
            path
        ).recent_resolutions(
            instrument_key=UNDERLYING,
            limit=25,
        )


def test_india_market_fresh_stale_and_historical(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    record = SQLiteRedBarV2CanonicalObservabilityRepository(
        path
    ).latest_resolution(instrument_key=UNDERLYING)
    assert record is not None
    assert _freshness(
        record,
        EVALUATED_AT + timedelta(seconds=60),
    )[0] == "FRESH"
    assert _freshness(
        record,
        EVALUATED_AT + timedelta(seconds=121),
    )[0] == "STALE"
    assert _freshness(
        record,
        EVALUATED_AT + timedelta(days=1),
    )[0] == "HISTORICAL"


def test_utc_india_midnight_boundary_uses_market_date(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    record = SQLiteRedBarV2CanonicalObservabilityRepository(
        path
    ).latest_resolution(instrument_key=UNDERLYING)
    assert record is not None
    now_utc = datetime(2026, 8, 24, 4, 36, tzinfo=timezone.utc)
    freshness, _ = _freshness(record, now_utc)
    assert freshness in {"FRESH", "STALE"}


def test_negative_age_beyond_tolerance_is_corruption(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    record = SQLiteRedBarV2CanonicalObservabilityRepository(
        path
    ).latest_resolution(instrument_key=UNDERLYING)
    assert record is not None
    with pytest.raises(
        CanonicalPersistenceCorruptionError,
        match="materially in the future",
    ):
        _freshness(
            record,
            EVALUATED_AT
            - timedelta(seconds=CLOCK_SKEW_TOLERANCE_SECONDS + 1),
        )


def test_complete_section_3_and_lifecycle_status(tmp_path: Path):
    path = tmp_path / "red_bar_strategy.db"
    _persist(path)
    repository, record = _selected(path)
    expected = record.envelope.section_3
    assert expected is not None
    selected = repository.selected_bundle_evidence(expected_bundle=expected)
    section = _section_3(record, selected.events)
    assert section.lifecycle_status == "AVAILABLE"
    assert section.event_history[0].event_type == "BUNDLE_AVAILABLE"
    assert section.underlying_instrument == UNDERLYING
    assert section.direction == "BULLISH"
    assert section.option_side == "CE"
    assert section.entry_type == "INITIAL"
    assert section.evaluation_timeframe == "1m"


def test_provisional_and_confirmed_reversal_views(tmp_path: Path):
    provisional_path = tmp_path / "provisional.db"
    _persist(provisional_path, provisional=True)
    provisional = _service(provisional_path).load(
        instrument_key=UNDERLYING,
        feature_enabled=True,
        now=EVALUATED_AT + timedelta(seconds=60),
    )
    assert provisional.section_2 is not None
    assert provisional.section_2.current_state == "PROVISIONAL_BULLISH"
    assert provisional.section_3 is not None
    assert provisional.section_3.entry_type == "REVERSAL"

    confirmed_path = tmp_path / "confirmed.db"
    _persist(confirmed_path, confirmed_reversal=True)
    confirmed = _service(confirmed_path).load(
        instrument_key=UNDERLYING,
        feature_enabled=True,
        now=EVALUATED_AT + timedelta(seconds=60),
    )
    assert confirmed.section_2 is not None
    assert confirmed.section_2.current_state == "CONFIRMED_BULLISH"
    assert confirmed.section_3 is not None
    assert confirmed.section_3.entry_type == "REVERSAL"


def test_service_disabled_is_true_noop(tmp_path: Path):
    path = tmp_path / "never-created.db"
    view = _service(path).load(
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
    path = tmp_path / "missing.db"
    view = _service(path).load(
        instrument_key=UNDERLYING,
        feature_enabled=True,
        now=datetime(2026, 8, 24, 10, 0),
    )
    assert view.status.availability == "CANONICAL_READ_FAILED"
    assert view.section_1 is None


def test_page_is_observational_arrow_safe_and_has_authority_banner():
    source = Path(
        "red_bar_lab/ui/pages/red_bar_v2_validation.py"
    ).read_text(encoding="utf-8")
    assert "NO — canonical processing is observational only" in source
    assert "Legacy Red Bar V2 remains execution authority" in source
    assert "CANONICAL_READ_FAILED" in source
    assert '.astype("string")' in source
    assert 'dtype="string"' in source
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
