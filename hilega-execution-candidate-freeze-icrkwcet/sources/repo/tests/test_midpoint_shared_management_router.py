import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from market_lab.domain import IST
from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
from market_lab.midpoint_strategy.family_b_shadow import FamilyBShadowRuntime
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
    _ReferenceRuntime,
)
from market_lab.midpoint_strategy.models import MidpointFamily, MidpointShadowState
from market_lab.midpoint_strategy.runtime import MidpointFamilyBRuntime
from market_lab.midpoint_strategy.structure import ReferenceStructure


def _runner(tmp_path, family=MidpointFamily.E):
    entry = datetime(2026, 9, 29, 9, 26, tzinfo=IST)
    audit = tmp_path / "audit.jsonl"
    coordinator = MidpointLiveShadowCoordinatorV1(
        market_sources=None, audit_path=audit
    )
    coordinator._reset_session(entry.date())
    reference = ReferenceStructure(
        entry.date().isoformat(),
        "RED",
        (entry - timedelta(minutes=6)).isoformat(),
        (entry - timedelta(minutes=2)).isoformat(),
        120.0,
        80.0,
    )
    runtime = MidpointFamilyBRuntime(
        reference=reference,
        family=family,
        lifecycle=FamilyBShadowRuntime(
            direction="BEARISH",
            entry_timestamp=entry,
            entry_underlying_close=75.0,
            family=family,
            state=MidpointShadowState.ACTIVE,
        ),
    )
    return coordinator, _ReferenceRuntime(reference, runtime), audit, entry


def _bar(coordinator, rr, timestamp, *, low, close, directional_vwap, previous):
    observation = FamilyBObservation(
        timestamp.isoformat(), close, 100.0 - directional_vwap, 100.0
    )
    candle = SimpleNamespace(
        timestamp=timestamp,
        open=close,
        high=max(close, low),
        low=low,
        close=close,
        volume=100.0,
    )
    coordinator._process_management(rr, observation, previous, candle)
    return observation


def test_strengthening_route_emits_one_degraded_exit_candidate(tmp_path):
    coordinator, rr, audit, entry = _runner(tmp_path)
    previous = None
    for minute in range(1, 13):
        timestamp = entry + timedelta(minutes=minute)
        if minute == 1:
            low, close, directional_vwap = 56.0, 57.0, 10.0
        elif minute == 2:
            low, close, directional_vwap = 54.0, 57.0, 10.0
        elif minute == 12:
            low, close, directional_vwap = 40.0, 42.0, 20.0
        else:
            low, close, directional_vwap = 55.0, 57.0, 10.0
        previous = _bar(
            coordinator,
            rr,
            timestamp,
            low=low,
            close=close,
            directional_vwap=directional_vwap,
            previous=previous,
        )

    previous = _bar(
        coordinator,
        rr,
        entry + timedelta(minutes=13),
        low=40.0,
        close=44.0,
        directional_vwap=20.0,
        previous=previous,
    )
    _bar(
        coordinator,
        rr,
        entry + timedelta(minutes=14),
        low=47.0,
        close=50.0,
        directional_vwap=15.0,
        previous=previous,
    )

    rows = [json.loads(line) for line in audit.read_text().splitlines()]
    route = next(r for r in rows if r["event_type"] == "MANAGEMENT_ROUTE_SELECTED")
    candidates = [
        r for r in rows
        if r["event_type"] == "DEGRADED_EXIT_CANDIDATE_TRIGGERED"
    ]
    assert route["result"] == "RUNNER_DEGRADED_EXIT"
    assert len(candidates) == 1
    assert candidates[0]["evidence"]["option_valuation_timestamp"].endswith(
        "09:41:00+05:30"
    )
    assert candidates[0]["evidence"]["baseline_lifecycle_unchanged"] is True
    assert candidates[0]["evidence"]["order_sent"] is False
    assert rr.runtime.lifecycle.state is MidpointShadowState.DEGRADED
    assert rr.closed is False


def test_normal_b_route_does_not_emit_degraded_candidate(tmp_path):
    coordinator, rr, audit, entry = _runner(tmp_path, MidpointFamily.B)
    previous = None
    for minute in range(1, 13):
        timestamp = entry + timedelta(minutes=minute)
        previous = _bar(
            coordinator,
            rr,
            timestamp,
            low=54.0,
            close=57.0,
            directional_vwap=10.0 if minute < 12 else 8.0,
            previous=previous,
        )
    rows = [json.loads(line) for line in audit.read_text().splitlines()]
    route = next(r for r in rows if r["event_type"] == "MANAGEMENT_ROUTE_SELECTED")
    assert route["result"] == "NORMAL_B_PROVED_THREE_TIER"
    assert any(r["event_type"] == "NORMAL_B_PROVED_STARTED" for r in rows)
    assert not any(
        r["event_type"] == "DEGRADED_EXIT_CANDIDATE_TRIGGERED" for r in rows
    )
    assert rr.runtime.lifecycle.runner_strengthening is False
    assert rr.closed is False
