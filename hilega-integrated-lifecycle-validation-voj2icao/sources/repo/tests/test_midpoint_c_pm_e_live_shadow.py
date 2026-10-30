import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from market_lab.domain import IST
from market_lab.midpoint_strategy.config import (
    MidpointShadowConfig,
    live_shadow_config_from_env,
)
from market_lab.midpoint_strategy.extended_entry_candidates import (
    PMMidpointBECandidate,
)
from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
from market_lab.midpoint_strategy.family_b_shadow import FamilyBShadowRuntime
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
    _ReferenceRuntime,
)
from market_lab.midpoint_strategy.models import MidpointFamily, MidpointShadowState
from market_lab.midpoint_strategy.runtime import MidpointFamilyBRuntime
from market_lab.midpoint_strategy.structure import ReferenceStructure


def _candle(timestamp, *, high, low, close):
    return SimpleNamespace(
        timestamp=timestamp,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


def test_environment_gates_are_explicit_and_remain_observation_only(monkeypatch):
    monkeypatch.setenv("MIDPOINT_FAMILY_C_SHADOW_ENABLED", "1")
    monkeypatch.setenv("MIDPOINT_PM_E_SHADOW_ENABLED", "true")
    config = live_shadow_config_from_env()
    assert config.family_c_enabled is True
    assert config.pm_e_enabled is True
    assert config.family_d_enabled is False
    assert config.observation_only is True
    assert config.execution_enabled is False
    assert config.paper_order_enabled is False
    assert config.quantity is None


def test_c_requires_touch_terminal_then_later_fresh_boundary_close(tmp_path):
    config = MidpointShadowConfig(family_c_enabled=True)
    audit = tmp_path / "audit.jsonl"
    coordinator = MidpointLiveShadowCoordinatorV1(
        market_sources=None, audit_path=audit, config=config
    )
    entry = datetime(2026, 8, 25, 9, 42, tzinfo=IST)
    coordinator._reset_session(entry.date())
    reference = ReferenceStructure(
        entry.date().isoformat(),
        "RED",
        (entry - timedelta(minutes=22)).isoformat(),
        (entry - timedelta(minutes=18)).isoformat(),
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

    observations = (
        (datetime(2026, 8, 25, 10, 0, tzinfo=IST), 101.0, 70.0, 90.0),
        (datetime(2026, 8, 25, 10, 1, tzinfo=IST), 105.0, 95.0, 101.0),
        (datetime(2026, 8, 25, 10, 2, tzinfo=IST), 101.0, 75.0, 79.0),
    )
    for timestamp, high, low, close in observations:
        coordinator._process_minute(
            ts=timestamp,
            underlying=_candle(timestamp, high=high, low=low, close=close),
            futures_close=90.0,
            futures_vwap=100.0,
            underlying_by_ts={},
        )

    c_runtime = coordinator.state.references["C:RED"].runtime
    assert c_runtime.family is MidpointFamily.C
    assert c_runtime.lifecycle is not None
    assert c_runtime.lifecycle.entry_timestamp == observations[-1][0]
    assert coordinator.state.active_reference_type == "C:RED"
    rows = [json.loads(line) for line in audit.read_text().splitlines()]
    kinds = [row["event_type"] for row in rows]
    assert kinds.index("C_MIDPOINT_TOUCH_ARMED") < kinds.index("STRUCTURAL_TERMINAL")
    assert kinds.index("STRUCTURAL_TERMINAL") < kinds.index("C_ENTRY")
    assert not any(
        row["event_type"] == "C_ENTRY"
        and row["event_timestamp"].endswith("10:01:00+05:30")
        for row in rows
    )


def test_pm_midpoint_boundary_then_e_owner_enters_immediately(
    tmp_path,
):
    config = MidpointShadowConfig(pm_e_enabled=True)
    audit = tmp_path / "audit.jsonl"
    coordinator = MidpointLiveShadowCoordinatorV1(
        market_sources=None, audit_path=audit, config=config
    )
    day = datetime(2026, 8, 25, 12, 45, tzinfo=IST)
    coordinator._reset_session(day.date())
    reference = ReferenceStructure(
        day.date().isoformat(),
        "GREEN",
        day.isoformat(),
        (day + timedelta(minutes=29)).isoformat(),
        120.0,
        80.0,
    )
    coordinator.state.pm_e_candidate = PMMidpointBECandidate(
        session_date=day.date().isoformat(),
        reference_start=day,
        reference_end=day + timedelta(minutes=29),
        high=120.0,
        low=80.0,
    )
    coordinator.state.pm_e_runtime = MidpointFamilyBRuntime(
        reference=reference, family=MidpointFamily.PM_E
    )

    previous = FamilyBObservation(
        (day + timedelta(minutes=29)).isoformat(), 110.0, 90.0, 100.0
    )
    coordinator.state.observations.append(previous)
    for timestamp, close in (
        (day + timedelta(minutes=30), 99.0),
        (day + timedelta(minutes=31), 79.0),
    ):
        current = FamilyBObservation(timestamp.isoformat(), close, 90.0, 100.0)
        coordinator.state.observations.append(current)
        coordinator._process_extended_entries(
            ts=timestamp,
            obs=current,
            prev_obs=previous,
            terminal_this_minute=False,
        )
        previous = current

    runtime = coordinator.state.references["PM_E"].runtime
    assert runtime.family is MidpointFamily.PM_E
    assert runtime.lifecycle is not None
    assert runtime.lifecycle.direction == "BEARISH"
    assert coordinator.state.active_reference_type == "PM_E"
    rows = [json.loads(line) for line in audit.read_text().splitlines()]
    kinds = [row["event_type"] for row in rows]
    assert kinds == [
        "PM_MIDPOINT_BREAK",
        "PM_BOUNDARY_CLASSIFIED",
        "PM_E_ENTRY",
    ]
    assert rows[-1]["evidence"]["qualification_owner"] == "E"
    assert all(row["evidence"].get("order_sent") is False for row in rows)


def test_pm_b_owner_uses_delayed_candidate_a_confirmation(tmp_path):
    config = MidpointShadowConfig(pm_e_enabled=True)
    audit = tmp_path / "audit.jsonl"
    coordinator = MidpointLiveShadowCoordinatorV1(
        market_sources=None, audit_path=audit, config=config
    )
    day = datetime(2026, 8, 25, 12, 45, tzinfo=IST)
    coordinator._reset_session(day.date())
    reference = ReferenceStructure(
        day.date().isoformat(), "GREEN", day.isoformat(),
        (day + timedelta(minutes=29)).isoformat(), 120.0, 80.0,
    )
    coordinator.state.pm_e_candidate = PMMidpointBECandidate(
        session_date=day.date().isoformat(), reference_start=day,
        reference_end=day + timedelta(minutes=29), high=120.0, low=80.0,
    )
    coordinator.state.pm_e_runtime = MidpointFamilyBRuntime(
        reference=reference, family=MidpointFamily.PM_E
    )
    previous = FamilyBObservation(
        (day + timedelta(minutes=29)).isoformat(), 110.0, 98.0, 100.0
    )
    coordinator.state.observations.append(previous)
    observations = (
        (day + timedelta(minutes=30), 99.0, 98.0),
        (day + timedelta(minutes=31), 79.0, 98.0),
        (day + timedelta(minutes=32), 78.0, 90.0),
    )
    for timestamp, close, futures_close in observations:
        current = FamilyBObservation(
            timestamp.isoformat(), close, futures_close, 100.0
        )
        coordinator.state.observations.append(current)
        coordinator._process_extended_entries(
            ts=timestamp, obs=current, prev_obs=previous,
            terminal_this_minute=False,
        )
        previous = current

    runtime = coordinator.state.references["PM_B"].runtime
    assert runtime.family is MidpointFamily.PM_B
    assert runtime.lifecycle is not None
    assert runtime.lifecycle.direction == "BEARISH"
    rows = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [row["event_type"] for row in rows] == [
        "PM_MIDPOINT_BREAK",
        "PM_BOUNDARY_CLASSIFIED",
        "PM_B_WATCH_STARTED",
        "PM_B_CONFIRMATION_CHECK",
        "PM_B_ENTRY",
    ]
