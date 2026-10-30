from market_lab.canonical_90_nine_leg_fixed10_trail3_sl10_v1 import (
    replay_fixed_points_policy,
)


def make_bar(ts, o, h, l, c):
    return {
        "timestamp": ts,
        "open": str(o),
        "high": str(h),
        "low": str(l),
        "close": str(c),
    }


def test_initial_stop_is_minus_ten_percent():
    inst = "X"
    bars = {
        inst: {
            "2026-08-25T09:37:00+05:30": make_bar(
                "2026-08-25T09:37:00+05:30", 100, 102, 89, 91
            )
        }
    }
    r = replay_fixed_points_policy(
        entry_timestamp="2026-08-25T09:36:00+05:30",
        entry_price=100.0,
        instrument_key=inst,
        bars_by_instrument=bars,
    )
    assert r is not None
    assert r["exit_reason"] == "STOP_TOUCH"
    assert abs(r["exit_price"] - 90.0) < 1e-9
    assert abs(r["net_return_pct"] - (-10.5)) < 1e-9


def test_plus10_points_arms_trail_but_new_stop_is_next_bar_only():
    inst = "X"
    bars = {
        inst: {
            # Hits 111 high, arming trail at 108, but low is 96 on same bar.
            # Since new trail is next-bar-only, same-bar 96 must NOT stop at 108.
            "2026-08-25T09:37:00+05:30": make_bar(
                "2026-08-25T09:37:00+05:30", 100, 111, 96, 110
            ),
            # Next bar opens above 108, then low touches 108 => trailing stop.
            "2026-08-25T09:38:00+05:30": make_bar(
                "2026-08-25T09:38:00+05:30", 110, 112, 107, 108
            ),
        }
    }
    r = replay_fixed_points_policy(
        entry_timestamp="2026-08-25T09:36:00+05:30",
        entry_price=100.0,
        instrument_key=inst,
        bars_by_instrument=bars,
    )
    assert r is not None
    assert r["trail_armed"] is True
    assert r["trail_arm_timestamp"] == "2026-08-25T09:37:00+05:30"
    assert r["exit_reason"] == "STOP_TOUCH"
    # Bar 1 high 111 -> stop 108. Bar 2 stop checked before high 112 can move it.
    assert abs(r["exit_price"] - 108.0) < 1e-9
    assert abs(r["net_return_pct"] - 7.5) < 1e-9


def test_trail_ratchets_by_three_points():
    inst = "X"
    bars = {
        inst: {
            "2026-08-25T09:37:00+05:30": make_bar(
                "2026-08-25T09:37:00+05:30", 100, 111, 100, 110
            ),
            "2026-08-25T09:38:00+05:30": make_bar(
                "2026-08-25T09:38:00+05:30", 110, 116, 109, 115
            ),
            "2026-08-25T09:39:00+05:30": make_bar(
                "2026-08-25T09:39:00+05:30", 115, 115, 112, 113
            ),
        }
    }
    r = replay_fixed_points_policy(
        entry_timestamp="2026-08-25T09:36:00+05:30",
        entry_price=100.0,
        instrument_key=inst,
        bars_by_instrument=bars,
    )
    assert r is not None
    # 111 -> 108 active on bar2; bar2 high 116 -> 113 active on bar3.
    assert r["exit_reason"] == "STOP_TOUCH"
    assert abs(r["exit_price"] - 113.0) < 1e-9
    assert abs(r["net_return_pct"] - 12.5) < 1e-9


def test_time_exit_if_neither_stop_nor_trail_exit():
    inst = "X"
    bars = {inst: {}}
    for i in range(1, 16):
        minute = 36 + i
        hh = 9 + minute // 60
        mm = minute % 60
        ts = f"2026-08-25T{hh:02d}:{mm:02d}:00+05:30"
        bars[inst][ts] = make_bar(ts, 100, 105, 95, 103 if i == 15 else 100)

    r = replay_fixed_points_policy(
        entry_timestamp="2026-08-25T09:36:00+05:30",
        entry_price=100.0,
        instrument_key=inst,
        bars_by_instrument=bars,
    )
    assert r is not None
    assert r["trail_armed"] is False
    assert r["exit_reason"] == "TIME_EXIT"
    assert abs(r["exit_price"] - 103.0) < 1e-9
    assert abs(r["net_return_pct"] - 2.5) < 1e-9
