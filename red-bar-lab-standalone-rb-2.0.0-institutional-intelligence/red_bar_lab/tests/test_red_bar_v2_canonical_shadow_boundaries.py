from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from red_bar_lab.services.red_bar_v2_canonical import (
    PersistenceOutcome,
    RedBarV2CanonicalPersistenceService,
    RedBarV2CanonicalShadowCoordinator,
    SQLiteRedBarV2CanonicalRepository,
)
from red_bar_lab.tests.test_red_bar_v2_canonical_shadow_runtime import (
    _real_event_fixture,
)


def _coordinator(path: Path):
    repository = SQLiteRedBarV2CanonicalRepository(path)
    return repository, RedBarV2CanonicalShadowCoordinator(
        RedBarV2CanonicalPersistenceService(repository), enabled=True
    )


def test_enabled_waiting_event_persists_resolution_without_bundle(tmp_path):
    replay, health, event, metadata, source_id = _real_event_fixture()
    waiting = replace(
        event,
        direction=None,
        option_side=None,
        admission_code=None,
        candidate_allowed=None,
        trade_id=None,
        details={
            **event.details,
            "entry_type": None,
            "trend_strength": None,
            "admission_reason": "Waiting for authoritative admission",
        },
    )
    repository, coordinator = _coordinator(tmp_path / "red_bar_strategy.db")
    observation = coordinator.observe(
        replay=replay,
        health=health,
        replay_event=waiting,
        market_metadata=metadata,
        legacy_result=waiting,
        source_replay_id=source_id + "-WAITING",
        event_timestamp=waiting.timestamp,
    )
    assert observation.persisted is True
    assert observation.outcome is PersistenceOutcome.INSERTED
    assert observation.bundle_id is None
    stored = repository.get_resolution(observation.resolution_id)
    assert stored is not None
    assert stored.section_3 is None
    assert stored.section_2.admission_outcome.value == "WAITING"


def test_enabled_rejected_event_persists_resolution_without_bundle(tmp_path):
    replay, health, event, metadata, source_id = _real_event_fixture()
    rejected = replace(
        event,
        direction=None,
        option_side=None,
        candidate_allowed=False,
        trade_id=None,
        details={
            **event.details,
            "entry_type": None,
            "trend_strength": None,
            "admission_reason": "Legacy admission rejected",
        },
    )
    repository, coordinator = _coordinator(tmp_path / "red_bar_strategy.db")
    observation = coordinator.observe(
        replay=replay,
        health=health,
        replay_event=rejected,
        market_metadata=metadata,
        legacy_result=rejected,
        source_replay_id=source_id + "-REJECTED",
        event_timestamp=rejected.timestamp,
    )
    assert observation.persisted is True
    assert observation.bundle_id is None
    stored = repository.get_resolution(observation.resolution_id)
    assert stored is not None
    assert stored.section_3 is None
    assert stored.section_2.admission_outcome.value == "REJECTED"


def test_shadow_modules_have_no_execution_or_bridge_imports():
    root = Path(__file__).parents[1] / "services" / "red_bar_v2_canonical"
    source = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in ("shadow_coordinator.py", "shadow_runtime.py")
    )
    forbidden = (
        "paper_signal_bridge",
        "publish_v2_snapshot_to_paper_signals",
        "paper_execution",
        "portfolio_admission",
        "position_monitor",
        "order_service",
    )
    for value in forbidden:
        assert value not in source


def test_unexpected_shadow_failure_isolated():
    replay, health, event, metadata, source_id = _real_event_fixture()

    class Unexpected:
        def persist(self, **kwargs):
            raise RuntimeError("shadow-only failure")

    observation = RedBarV2CanonicalShadowCoordinator(
        Unexpected(), enabled=True
    ).observe(
        replay=replay,
        health=health,
        replay_event=event,
        market_metadata=metadata,
        legacy_result=event,
        source_replay_id=source_id,
        event_timestamp=event.timestamp,
    )
    assert observation.persisted is False
    assert observation.error_category == "UNEXPECTED_SHADOW_FAILURE"
    assert event.candidate_allowed is True
