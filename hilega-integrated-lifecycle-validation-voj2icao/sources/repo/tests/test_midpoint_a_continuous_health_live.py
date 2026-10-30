import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from market_lab.midpoint_strategy.config import MidpointShadowConfig
from market_lab.midpoint_strategy.continuous_health_exit_v1 import (
    ContinuousHealthExitV1,
)
from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
    _ReferenceRuntime,
)
from market_lab.midpoint_strategy.models import MidpointFamily
from market_lab.midpoint_strategy.runtime import MidpointFamilyBRuntime
from market_lab.midpoint_strategy.structure import ReferenceStructure


def test_continuous_health_paths_use_one_and_two_completed_closes():
    start = datetime.fromisoformat("2026-10-01T10:00:00+05:30")
    overlay = ContinuousHealthExitV1()
    overlay.observe_close(timestamp=start, directional_points=50, health="HEALTHY")
    assert overlay.arm_soft_exit(
        timestamp=start, reason="PRIMARY_TARGET_TOUCH", directional_points=50
    ) == []

    first = overlay.observe_close(
        timestamp=start + timedelta(minutes=1),
        directional_points=58,
        health="UNHEALTHY",
    )
    assert [row.policy for row in first] == ["HEALTH_IMMEDIATE_CONFIRMATION"]
    assert overlay.two_close.closed is False

    second = overlay.observe_close(
        timestamp=start + timedelta(minutes=2),
        directional_points=55,
        health="UNHEALTHY",
    )
    assert [row.policy for row in second] == ["HEALTH_TWO_CLOSE_CONFIRMATION"]
    assert second[0].directional_points == 55


def test_healthy_close_resets_two_close_streak_without_lookahead():
    start = datetime.fromisoformat("2026-10-01T10:00:00+05:30")
    overlay = ContinuousHealthExitV1()
    overlay.observe_close(timestamp=start, directional_points=50, health="UNHEALTHY")
    exits = overlay.arm_soft_exit(
        timestamp=start, reason="DEGRADED_STARTED", directional_points=50
    )
    assert [row.policy for row in exits] == ["HEALTH_IMMEDIATE_CONFIRMATION"]
    overlay.observe_close(
        timestamp=start + timedelta(minutes=1), directional_points=52,
        health="HEALTHY",
    )
    assert overlay.two_close.unhealthy_streak == 0
    assert overlay.two_close.closed is False


def test_structural_fallback_preserves_actual_close_points():
    start = datetime.fromisoformat("2026-10-01T10:00:00+05:30")
    overlay = ContinuousHealthExitV1()
    overlay.observe_close(timestamp=start, directional_points=-18.5,
                          health="UNAVAILABLE")
    records = overlay.structural_fallback(
        timestamp=start, directional_points=-18.5
    )
    assert {row.directional_points for row in records} == {-18.5}
    assert all(row.reason.startswith("STRUCTURAL_FALLBACK") for row in records)


def _obs(timestamp: str, close: float, raw_diff: float) -> FamilyBObservation:
    return FamilyBObservation(
        timestamp=timestamp, close=close,
        futures_price=23000 + raw_diff, futures_vwap=23000,
    )


def test_fresh_a_enters_parallel_without_owning_canonical_lane(tmp_path: Path):
    audit_path = tmp_path / "audit.jsonl"
    coordinator = MidpointLiveShadowCoordinatorV1(
        market_sources=object(), audit_path=audit_path,
        config=MidpointShadowConfig(family_a_enabled=True),
    )
    coordinator._reset_session(date(2026, 10, 1))
    ref = ReferenceStructure(
        session_date="2026-10-01", reference_type="RED",
        start_timestamp="2026-10-01T09:20:00+05:30",
        end_timestamp="2026-10-01T09:24:00+05:30",
        high=22951.8, low=22914.1,
    )
    rr = _ReferenceRuntime(
        reference=ref, runtime=MidpointFamilyBRuntime(reference=ref),
        midpoint_seen=True,
    )
    coordinator.state.references["RED"] = rr
    coordinator.state.observations.extend([
        _obs("2026-10-01T09:22:00+05:30", 22930, 2),
        _obs("2026-10-01T09:23:00+05:30", 22925, 0),
        _obs("2026-10-01T09:24:00+05:30", 22920, -2),
        _obs("2026-10-01T09:25:00+05:30", 22914.2, -4),
    ])
    timestamp = datetime.fromisoformat("2026-10-01T09:26:00+05:30")
    candle = SimpleNamespace(
        timestamp=timestamp, open=22914, high=22915, low=22910,
        close=22912.95, volume=100,
    )
    coordinator._process_minute(
        ts=timestamp, underlying=candle, futures_close=22992,
        futures_vwap=23000, underlying_by_ts={}, futures_open=22996,
        futures_volume=100,
    )

    assert rr.runtime.family is MidpointFamily.A
    assert rr.runtime.lifecycle is not None
    assert coordinator.state.active_reference_type is None
    assert coordinator.state.a_reference_types == {"RED"}
    rows = [json.loads(line) for line in audit_path.read_text().splitlines()]
    entry = next(row for row in rows if row["event_type"] == "A_ENTRY")
    assert entry["evidence"]["parallel_lane"] is True
    assert entry["evidence"]["order_sent"] is False


def test_workspace_defaults_are_observation_only():
    config = MidpointShadowConfig()
    config.assert_safe()
    assert config.family_a_enabled is False
    assert config.continuous_health_exit_candidate_enabled is False
    assert config.execution_enabled is False
    assert config.paper_order_enabled is False
    assert config.quantity is None
