from datetime import datetime, timedelta

from market_lab.midpoint_strategy.config import MidpointShadowConfig
from market_lab.midpoint_strategy.family_b_shadow import (
    FamilyBShadowManager,
    FamilyBShadowRuntime,
)
from market_lab.midpoint_strategy.models import MidpointShadowState
from market_lab.midpoint_strategy.structure import (
    ReferenceStructure,
    structure_still_valid,
)


def ref(kind="RED"):
    return ReferenceStructure(
        session_date="2026-08-25",
        reference_type=kind,
        start_timestamp="2026-08-25T09:20:00+05:30",
        end_timestamp="2026-08-25T09:24:00+05:30",
        high=24198.25,
        low=24173.70,
    )


def test_family_b_structure_validity_is_midpoint_based():
    r = ref("RED")
    assert structure_still_valid(r, r.midpoint) is True
    assert structure_still_valid(r, r.midpoint + 0.01) is False

    g = ref("GREEN")
    assert structure_still_valid(g, g.midpoint) is True
    assert structure_still_valid(g, g.midpoint - 0.01) is False


def test_cap20_only_first_eligible_rebreak_can_rescue():
    cfg = MidpointShadowConfig()
    m = FamilyBShadowManager(cfg)
    t0 = datetime.fromisoformat("2026-08-25T10:00:00+05:30")
    rt = FamilyBShadowRuntime(
        direction="BULLISH",
        entry_timestamp=t0,
        entry_underlying_close=100.0,
        plus20_timestamp=t0 + timedelta(minutes=5),
        classifier_timestamp=t0 + timedelta(minutes=15),
        runner_strengthening=True,
        degraded_timestamp=t0 + timedelta(minutes=20),
        degraded_target_move=25.0,
        recovery_timestamp=t0 + timedelta(minutes=25),
        state=MidpointShadowState.DEGRADED,
    )

    assert m.maybe_cap20_rescue(
        rt,
        t0 + timedelta(minutes=34),
        current_directional_points=24.0,
        current_directional_move=24.0,
    ) is None
    assert rt.cap20_rebreak_evaluated is False

    assert m.maybe_cap20_rescue(
        rt,
        t0 + timedelta(minutes=35),
        current_directional_points=24.0,
        current_directional_move=24.0,
    ) is None
    assert rt.cap20_rebreak_evaluated is True
    assert rt.rescue_timestamp is None

    assert m.maybe_cap20_rescue(
        rt,
        t0 + timedelta(minutes=36),
        current_directional_points=18.0,
        current_directional_move=18.0,
    ) is None
    assert rt.rescue_timestamp is None
