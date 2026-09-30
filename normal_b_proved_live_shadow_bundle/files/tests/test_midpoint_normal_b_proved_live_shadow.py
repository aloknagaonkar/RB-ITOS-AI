import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from market_lab.domain import IST
from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
from market_lab.midpoint_strategy.family_b_shadow import FamilyBShadowRuntime
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1, _ReferenceRuntime,
)
from market_lab.midpoint_strategy.models import MidpointFamily, MidpointShadowState
from market_lab.midpoint_strategy.runtime import MidpointFamilyBRuntime
from market_lab.midpoint_strategy.structure import ReferenceStructure


def test_normal_b_proved_live_candidate_does_not_close_baseline(tmp_path):
    start = datetime(2026, 8, 25, 9, 0, tzinfo=IST)
    audit = tmp_path / "audit.jsonl"
    coordinator = MidpointLiveShadowCoordinatorV1(
        market_sources=None, audit_path=audit,
    )
    coordinator._reset_session(start.date())
    reference = ReferenceStructure(
        start.date().isoformat(), "RED", start.isoformat(), start.isoformat(),
        120.0, 80.0,
    )
    runtime = MidpointFamilyBRuntime(
        reference=reference,
        family=MidpointFamily.B,
        lifecycle=FamilyBShadowRuntime(
            direction="BEARISH",
            entry_timestamp=start,
            entry_underlying_close=100.0,
            family=MidpointFamily.B,
            state=MidpointShadowState.ACTIVE,
        ),
    )
    rr = _ReferenceRuntime(reference=reference, runtime=runtime)

    def process(minute, *, low, close, directional_vwap):
        ts = start + timedelta(minutes=minute)
        obs = FamilyBObservation(
            ts.isoformat(), close, 100.0 - directional_vwap, 100.0,
        )
        candle = SimpleNamespace(
            timestamp=ts, open=close, high=max(close, 100.0), low=low,
            close=close, volume=100.0,
        )
        coordinator._process_management(rr, obs, None, candle)

    # +20 proof at minute 1, NORMAL_B classification exactly ten minutes later.
    process(1, low=75.0, close=76.0, directional_vwap=10.0)
    for minute in range(2, 11):
        process(minute, low=74.0, close=76.0, directional_vwap=10.0)
    process(11, low=74.0, close=76.0, directional_vwap=8.0)
    process(12, low=69.0, close=72.0, directional_vwap=8.0)
    process(13, low=54.0, close=60.0, directional_vwap=8.0)
    process(14, low=55.0, close=71.0, directional_vwap=8.0)

    rows = [json.loads(line) for line in audit.read_text().splitlines()]
    kinds = [row["event_type"] for row in rows]
    assert "NORMAL_B_PROVED_STARTED" in kinds
    assert "NORMAL_B_PROVED_TIER2" in kinds
    assert "NORMAL_B_PROVED_TIER3" in kinds
    exit_row = next(
        row for row in rows
        if row["event_type"] == "NORMAL_B_PROVED_EXIT_CANDIDATE"
    )
    assert exit_row["reason"] == "TIER3_RATCHET_FLOOR_CLOSE"
    assert exit_row["directional_points"] == 29.0
    assert exit_row["evidence"]["candidate_only"] is True
    assert exit_row["evidence"]["baseline_lifecycle_unchanged"] is True
    assert exit_row["evidence"]["order_sent"] is False
    assert exit_row["execution_enabled"] is False
    assert exit_row["paper_order_enabled"] is False
    assert exit_row["quantity"] is None

    # The candidate is parallel: it cannot mutate or close the baseline trade.
    assert rr.closed is False
    assert runtime.lifecycle.state == MidpointShadowState.ACTIVE
    assert runtime.lifecycle.runner_strengthening is False
