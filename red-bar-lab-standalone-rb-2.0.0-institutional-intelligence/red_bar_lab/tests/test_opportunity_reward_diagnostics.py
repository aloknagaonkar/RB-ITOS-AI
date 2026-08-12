from red_bar_lab.services.opportunity_reward_diagnostics import build_opportunity_reward_trace


def _signal(direction="BEARISH"):
    return {
        "signal_id": "SIG-1",
        "direction": direction,
        "confirmation_high": 24450.0,
        "confirmation_low": 24440.0,
        "confirmation_close": 24442.0,
    }


def test_reward_consumed_block_is_explained():
    row = {
        "signal_id": "SIG-1",
        "direction": "BEARISH",
        "candidate_symbol": "NIFTY PE",
        "reward_remaining_pct": 25.0,
        "move_consumed_pct": 75.0,
        "opportunity_score": 85.0,
        "reward_score": 5.0,
        "eligible": 0,
        "decision": "SKIP",
        "reason": "REWARD_CONSUMED",
    }
    trace = build_opportunity_reward_trace(row, _signal())
    assert trace["reward_gate_status"] == "BLOCK"
    assert trace["minimum_reward_remaining_pct"] == 40.0
    assert trace["confirmation_range"] == 12.221
    assert trace["persisted_move_consumed_pct"] == 75.0


def test_reward_gate_pass_is_explained():
    row = {
        "signal_id": "SIG-1",
        "direction": "BEARISH",
        "reward_remaining_pct": 55.0,
        "move_consumed_pct": 45.0,
        "opportunity_score": 90.0,
        "eligible": 1,
        "decision": "BUY PE",
        "reason": "OPPORTUNITY_HEALTH_PASS",
    }
    trace = build_opportunity_reward_trace(row, _signal())
    assert trace["reward_gate_status"] == "PASS"
    assert trace["persisted_reward_remaining_pct"] == 55.0


def test_threshold_spot_uses_same_two_range_model():
    row = {
        "signal_id": "SIG-1",
        "direction": "BEARISH",
        "reward_remaining_pct": 40.0,
        "move_consumed_pct": 60.0,
        "reason": "OPPORTUNITY_HEALTH_PASS",
    }
    trace = build_opportunity_reward_trace(row, _signal())
    # confirmation range floor is 0.05% of 24442 = 12.221, larger than OHLC range 10.
    assert trace["confirmation_range"] == 12.221
    assert trace["full_consumption_distance_2x_range"] == 24.442
    assert trace["inferred_progress_points"] == 14.6652
    assert trace["reward_consumed_threshold_spot"] == 24427.3348
