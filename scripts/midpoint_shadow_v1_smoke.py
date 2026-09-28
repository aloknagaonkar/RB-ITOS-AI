#!/usr/bin/env python3
from datetime import datetime, timedelta, timezone

from market_lab.midpoint_strategy.config import MidpointShadowConfig
from market_lab.midpoint_strategy.family_b_shadow import (
    FamilyBShadowManager,
    FamilyBShadowRuntime,
)
from market_lab.midpoint_strategy.workspace_contract import midpoint_workspace_status


def main():
    cfg = MidpointShadowConfig()
    cfg.assert_safe()

    print("MIDPOINT STRATEGY — SHADOW V1 SMOKE")
    print("=" * 80)
    print(midpoint_workspace_status(cfg))

    manager = FamilyBShadowManager(cfg)
    t0 = datetime(2026, 9, 29, 9, 42, tzinfo=timezone.utc)

    rt = FamilyBShadowRuntime(
        direction="BULLISH",
        entry_timestamp=t0,
        entry_underlying_close=25000.0,
    )

    manager.mark_plus20(rt, t0 + timedelta(minutes=6))
    manager.classify_runner(
        rt,
        t0 + timedelta(minutes=16),
        net_directional_progress_from_plus20=5.0,
        directional_futures_vwap_change=2.0,
    )
    manager.mark_degraded(
        rt,
        t0 + timedelta(minutes=25),
        degraded_target_move=18.0,
    )
    manager.mark_recovery(rt, t0 + timedelta(minutes=27))

    rescue = manager.maybe_cap20_rescue(
        rt,
        t0 + timedelta(minutes=38),
        current_directional_points=15.0,
        current_directional_move=15.0,
    )
    assert rescue is not None
    assert rescue.reason == "CAP20_RESCUE"

    reentry = manager.maybe_post_rescue_reentry(
        rt,
        t0 + timedelta(minutes=40),
        current_directional_move=19.0,
        directional_futures_vwap_now=4.0,
        directional_futures_vwap_at_rescue=2.0,
    )
    assert reentry is not None
    assert reentry.reason == "POST_CAP20_REENTRY"
    assert rt.reentry_count == 1

    blocked_second = manager.maybe_post_rescue_reentry(
        rt,
        t0 + timedelta(minutes=41),
        current_directional_move=20.0,
        directional_futures_vwap_now=5.0,
        directional_futures_vwap_at_rescue=2.0,
    )
    assert blocked_second is None

    print("PASS: safety contract")
    print("PASS: Family B only")
    print("PASS: CAP20 rescue")
    print("PASS: one post-rescue re-entry")
    print("PASS: second re-entry blocked")


if __name__ == "__main__":
    main()
