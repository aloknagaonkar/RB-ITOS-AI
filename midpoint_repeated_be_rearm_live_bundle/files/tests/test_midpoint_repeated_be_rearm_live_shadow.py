import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from market_lab.domain import IST
from market_lab.midpoint_strategy.config import (
    MidpointShadowConfig,
    live_shadow_config_from_env,
)
from market_lab.midpoint_strategy.family_b_shadow import FamilyBShadowRuntime
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
    _ReferenceRuntime,
)
from market_lab.midpoint_strategy.models import MidpointFamily, MidpointShadowState
from market_lab.midpoint_strategy.runtime import MidpointFamilyBRuntime
from market_lab.midpoint_strategy.structure import ReferenceStructure


def candle(timestamp, high, low, close):
    return SimpleNamespace(
        timestamp=timestamp,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


def test_repeated_be_rearm_environment_gate(monkeypatch):
    monkeypatch.setenv("MIDPOINT_FAMILY_C_SHADOW_ENABLED", "0")
    monkeypatch.setenv("MIDPOINT_BE_REARM_SHADOW_ENABLED", "1")
    config = live_shadow_config_from_env()
    assert config.family_c_enabled is False
    assert config.be_rearm_enabled is True
    config.assert_safe()


def test_c_and_repeated_rearm_are_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        MidpointShadowConfig(
            family_c_enabled=True, be_rearm_enabled=True
        ).assert_safe()


def test_every_entered_generation_can_arm_the_next_generation(tmp_path):
    config = MidpointShadowConfig(be_rearm_enabled=True)
    audit = tmp_path / "audit.jsonl"
    coordinator = MidpointLiveShadowCoordinatorV1(
        market_sources=None, audit_path=audit, config=config
    )
    entry = datetime(2026, 9, 30, 9, 30, tzinfo=IST)
    coordinator._reset_session(entry.date())
    reference = ReferenceStructure(
        entry.date().isoformat(),
        "RED",
        (entry - timedelta(minutes=10)).isoformat(),
        (entry - timedelta(minutes=6)).isoformat(),
        120.0,
        80.0,
    )
    runtime = MidpointFamilyBRuntime(
        reference=reference,
        family=MidpointFamily.E,
        lifecycle=FamilyBShadowRuntime(
            direction="BEARISH",
            entry_timestamp=entry,
            entry_underlying_close=75.0,
            family=MidpointFamily.E,
            state=MidpointShadowState.ACTIVE,
        ),
    )
    coordinator.state.references["RED"] = _ReferenceRuntime(
        reference=reference,
        runtime=runtime,
        midpoint_seen=True,
        boundary_seen=True,
    )
    coordinator.state.active_reference_type = "RED"

    bars = (
        (entry + timedelta(minutes=1), 92.0, 70.0, 89.0),
        (entry + timedelta(minutes=2), 105.0, 95.0, 101.0),
        (entry + timedelta(minutes=3), 81.0, 75.0, 79.0),
        (entry + timedelta(minutes=4), 92.0, 75.0, 89.0),
        (entry + timedelta(minutes=5), 105.0, 95.0, 101.0),
        (entry + timedelta(minutes=6), 81.0, 75.0, 79.0),
    )
    for timestamp, high, low, close in bars:
        coordinator._process_minute(
            ts=timestamp,
            underlying=candle(timestamp, high, low, close),
            futures_close=90.0,
            futures_vwap=100.0,
            underlying_by_ts={},
        )

    rows = [json.loads(line) for line in audit.read_text().splitlines()]
    entries = [row for row in rows if row["event_type"] == "E_REARM_ENTRY"]
    assert [row["evidence"]["generation"] for row in entries] == [1, 2]
    assert all(row["evidence"]["order_sent"] is False for row in entries)
    assert coordinator.state.active_reference_type.startswith("BE_REARM:")
    active = coordinator.state.references[coordinator.state.active_reference_type]
    assert active.generation == 2
    assert active.runtime.family is MidpointFamily.E
    assert active.runtime.lifecycle is not None
