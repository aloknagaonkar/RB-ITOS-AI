from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from red_bar_lab.services.red_bar_v2_canonical import (
    CanonicalPersistenceUnavailableError,
    PersistenceOutcome,
    RedBarV2CanonicalPersistenceService,
    RedBarV2CanonicalShadowCoordinator,
    SQLiteRedBarV2CanonicalRepository,
    build_runtime_market_metadata,
    build_runtime_source_replay_id,
    get_red_bar_v2_shadow_runtime,
)
from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
    replay_red_bar_v2_day_with_futures_vwap,
)
from red_bar_lab.services.red_bar_v2_historical_replay import ReplayEvent

IST = timezone(timedelta(hours=5, minutes=30))
UNDERLYING = "NSE_INDEX|Nifty 50"
FUTURES = "NSE_FO|NIFTY-FUT"


def _candles(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    timestamps = pd.date_range(
        datetime(2026, 8, 24, 9, 15, tzinfo=IST),
        periods=len(closes),
        freq="1min",
    )
    opens = [closes[0] - 0.2, *closes[:-1]]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) + 0.4 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 0.4 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": volumes,
        },
        index=timestamps,
    )


def _real_event_fixture():
    index_closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    index_closes += [103.0, 101.0, 99.0, 97.0, 95.0]
    index_closes += [96.0 + index * 0.9 for index in range(40)]
    futures_closes = [200.0 + index * 0.6 for index in range(50)]
    replay, health = replay_red_bar_v2_day_with_futures_vwap(
        _candles(index_closes, [10.0 + index for index in range(50)]),
        _candles(futures_closes, [1000.0 + index * 10.0 for index in range(50)]),
        instrument_key=UNDERLYING,
        vwap_instrument_key=FUTURES,
    )
    event = next(
        item for item in replay.events
        if item.event_type == "CANDIDATE_ADMISSION" and item.candidate_allowed is True
    )
    metadata = build_runtime_market_metadata(
        replay=replay,
        health=health,
        event=event,
        instrument_key=UNDERLYING,
        futures_instrument_key=FUTURES,
        futures_expiry="2026-08-27",
    )
    source_id = build_runtime_source_replay_id(
        instrument_key=UNDERLYING,
        trading_date=replay.trading_date,
        event=event,
    )
    return replay, health, event, metadata, source_id


class _FailIfCalled:
    def persist(self, **kwargs):
        raise AssertionError("disabled shadow must not persist")


def test_feature_flag_disabled_does_not_resolve_or_persist(monkeypatch):
    import red_bar_lab.services.red_bar_v2_canonical.shadow_coordinator as module

    monkeypatch.setattr(
        module,
        "resolve_red_bar_v2_canonical",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("resolver called")),
    )
    coordinator = RedBarV2CanonicalShadowCoordinator(_FailIfCalled(), enabled=False)
    observation = coordinator.observe(
        replay=object(), health=object(), replay_event=None,
        market_metadata=object(), legacy_result=object(),
        source_replay_id="IGNORED",
        event_timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
    )
    assert observation.attempted is False
    assert observation.reason_code == "SHADOW_DISABLED"


def test_enabled_real_futures_event_persists_bundle_and_event(tmp_path):
    replay, health, event, metadata, source_id = _real_event_fixture()
    repository = SQLiteRedBarV2CanonicalRepository(tmp_path / "red_bar_strategy.db")
    coordinator = RedBarV2CanonicalShadowCoordinator(
        RedBarV2CanonicalPersistenceService(repository), enabled=True
    )

    observation = coordinator.observe(
        replay=replay, health=health, replay_event=event,
        market_metadata=metadata, legacy_result=event,
        source_replay_id=source_id, event_timestamp=event.timestamp,
    )

    assert observation.persisted is True
    assert observation.outcome is PersistenceOutcome.INSERTED
    assert observation.resolution_id is not None
    assert observation.bundle_id is not None
    persisted = repository.get_resolution(observation.resolution_id)
    assert persisted is not None
    assert persisted.resolved_at == event.timestamp
    assert persisted.section_3 is not None
    assert persisted.section_3.created_at == event.timestamp
    assert len(repository.list_bundle_events(observation.bundle_id)) == 1


def test_identical_retry_and_restart_are_idempotent(tmp_path):
    replay, health, event, metadata, source_id = _real_event_fixture()
    path = tmp_path / "red_bar_strategy.db"

    first_repository = SQLiteRedBarV2CanonicalRepository(path)
    first = RedBarV2CanonicalShadowCoordinator(
        RedBarV2CanonicalPersistenceService(first_repository), enabled=True
    ).observe(
        replay=replay, health=health, replay_event=event,
        market_metadata=metadata, legacy_result=event,
        source_replay_id=source_id, event_timestamp=event.timestamp,
    )

    restarted_repository = SQLiteRedBarV2CanonicalRepository(path)
    second = RedBarV2CanonicalShadowCoordinator(
        RedBarV2CanonicalPersistenceService(restarted_repository), enabled=True
    ).observe(
        replay=replay, health=health, replay_event=event,
        market_metadata=metadata, legacy_result=event,
        source_replay_id=source_id, event_timestamp=event.timestamp,
    )

    assert first.resolution_id == second.resolution_id
    assert second.outcome is PersistenceOutcome.IDEMPOTENT_REPLAY
    assert len(restarted_repository.list_bundle_events(first.bundle_id)) == 1


def test_naive_timestamp_is_isolated_from_legacy_flow(tmp_path):
    replay, health, event, metadata, source_id = _real_event_fixture()
    coordinator = RedBarV2CanonicalShadowCoordinator(
        RedBarV2CanonicalPersistenceService(
            SQLiteRedBarV2CanonicalRepository(tmp_path / "red_bar_strategy.db")
        ),
        enabled=True,
    )
    observation = coordinator.observe(
        replay=replay, health=health, replay_event=event,
        market_metadata=metadata, legacy_result=event,
        source_replay_id=source_id,
        event_timestamp=event.timestamp.replace(tzinfo=None),
    )
    assert observation.persisted is False
    assert observation.error_category == "INPUT_UNAVAILABLE"
    assert event.candidate_allowed is True


def test_parity_mismatch_is_persisted_and_reported(tmp_path):
    replay, health, event, metadata, source_id = _real_event_fixture()
    mismatched = replace(event, option_side="PE")
    coordinator = RedBarV2CanonicalShadowCoordinator(
        RedBarV2CanonicalPersistenceService(
            SQLiteRedBarV2CanonicalRepository(tmp_path / "red_bar_strategy.db")
        ),
        enabled=True,
    )
    observation = coordinator.observe(
        replay=replay, health=health, replay_event=event,
        market_metadata=metadata, legacy_result=mismatched,
        source_replay_id=source_id, event_timestamp=event.timestamp,
    )
    assert observation.persisted is True
    assert observation.parity_matches is False
    assert observation.reason_code == "PARITY_MISMATCH"
    assert "option_side" in observation.mismatch_fields


def test_conflicting_retry_is_reported_and_first_evidence_survives(tmp_path):
    replay, health, event, metadata, source_id = _real_event_fixture()
    repository = SQLiteRedBarV2CanonicalRepository(tmp_path / "red_bar_strategy.db")
    coordinator = RedBarV2CanonicalShadowCoordinator(
        RedBarV2CanonicalPersistenceService(repository), enabled=True
    )
    first = coordinator.observe(
        replay=replay, health=health, replay_event=event,
        market_metadata=metadata, legacy_result=event,
        source_replay_id=source_id, event_timestamp=event.timestamp,
    )
    conflict = coordinator.observe(
        replay=replay, health=health, replay_event=event,
        market_metadata=metadata, legacy_result=replace(event, option_side="PE"),
        source_replay_id=source_id, event_timestamp=event.timestamp,
    )
    assert conflict.persisted is False
    assert conflict.error_category == "PERSISTENCE_CONFLICT"
    stored = repository.get_resolution(first.resolution_id)
    assert stored is not None and stored.parity is not None
    assert stored.parity.matches is True


def test_persistence_unavailable_is_isolated():
    replay, health, event, metadata, source_id = _real_event_fixture()

    class Unavailable:
        def persist(self, **kwargs):
            raise CanonicalPersistenceUnavailableError("locked")

    observation = RedBarV2CanonicalShadowCoordinator(
        Unavailable(), enabled=True
    ).observe(
        replay=replay, health=health, replay_event=event,
        market_metadata=metadata, legacy_result=event,
        source_replay_id=source_id, event_timestamp=event.timestamp,
    )
    assert observation.persisted is False
    assert observation.error_category == "PERSISTENCE_UNAVAILABLE"
    assert event.candidate_allowed is True


def test_runtime_factory_is_disabled_without_database_and_singleton_when_enabled(tmp_path):
    disabled_path = tmp_path / "disabled" / "red_bar_strategy.db"
    assert get_red_bar_v2_shadow_runtime(enabled=False, database_path=disabled_path) is None
    assert not disabled_path.exists()

    enabled_path = tmp_path / "enabled" / "red_bar_strategy.db"
    first = get_red_bar_v2_shadow_runtime(enabled=True, database_path=enabled_path)
    second = get_red_bar_v2_shadow_runtime(enabled=True, database_path=enabled_path)
    assert first is second
    assert enabled_path.exists()


def test_source_replay_id_is_timezone_normalized_and_stable():
    replay, _, event, _, _ = _real_event_fixture()
    same_in_utc = replace(event, timestamp=event.timestamp.astimezone(timezone.utc))
    first = build_runtime_source_replay_id(
        instrument_key=UNDERLYING, trading_date=replay.trading_date, event=event
    )
    second = build_runtime_source_replay_id(
        instrument_key=UNDERLYING, trading_date=replay.trading_date, event=same_in_utc
    )
    assert first == second
    assert first.startswith("RBV2-RUNTIME-")
