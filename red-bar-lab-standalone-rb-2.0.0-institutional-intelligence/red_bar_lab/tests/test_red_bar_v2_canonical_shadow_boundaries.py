from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from red_bar_lab.services.red_bar_v2_canonical import (
    PersistenceOutcome,
    RedBarV2CanonicalPersistenceService,
    RedBarV2CanonicalShadowCoordinator,
    SQLiteRedBarV2CanonicalRepository,
    build_runtime_market_metadata,
    build_runtime_source_replay_id,
)
from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
    replay_red_bar_v2_day_with_futures_vwap,
)

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
        item
        for item in replay.events
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
