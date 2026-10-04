from scripts.research_hilega_wma_gap_t5_exits import (
    maximum_drawdown,
    metrics,
    policy_decision,
    t5_components,
)


def sample(**updates):
    row = {
        "captured_points": -20.0,
        "t5_timestamp": "2026-10-01T10:05:00+05:30",
        "t5_price": "95",
        "t5_points_from_candidate_entry": "-5",
        "t5_wma_strength": "0.4",
        "t5_directional_gap": "1.0",
        "t5_gap_delta_1m": "-0.2",
        "t5_ema_directional_delta_1m": "-0.1",
        "t5_full_alignment": "False",
    }
    row.update(updates)
    return row


def test_t5_components_have_four_independent_health_checks():
    result = t5_components(sample())
    assert result == {
        "wma_weak": True,
        "gap_weak": True,
        "ema_weak": True,
        "alignment_weak": True,
    }


def test_price_only_exits_nonpositive_t5():
    result = policy_decision(sample(), "T5_PRICE_NONPOSITIVE")
    assert result["exit_triggered"] is True
    assert result["policy_points"] == -5
    assert result["delta_vs_control"] == 15


def test_two_of_four_requires_price_failure_and_two_weak_components():
    one_weak = sample(
        t5_wma_strength="1.2",
        t5_directional_gap="2",
        t5_gap_delta_1m="0.2",
        t5_ema_directional_delta_1m="0.1",
        t5_full_alignment="False",
    )
    assert not policy_decision(one_weak, "T5_PRICE_2_OF_4_WEAK")["exit_triggered"]
    two_weak = dict(one_weak, t5_ema_directional_delta_1m="-0.1")
    assert policy_decision(two_weak, "T5_PRICE_2_OF_4_WEAK")["exit_triggered"]
    positive = dict(two_weak, t5_points_from_candidate_entry="2")
    assert not policy_decision(positive, "T5_PRICE_2_OF_4_WEAK")["exit_triggered"]


def test_all_four_is_strict():
    assert policy_decision(sample(), "T5_PRICE_ALL_4_WEAK")["exit_triggered"]
    healthy_alignment = sample(t5_full_alignment="True")
    assert not policy_decision(
        healthy_alignment, "T5_PRICE_ALL_4_WEAK"
    )["exit_triggered"]


def test_missing_t5_never_exits():
    row = sample(t5_timestamp="", t5_points_from_candidate_entry="")
    for policy in (
        "T5_PRICE_NONPOSITIVE", "T5_PRICE_2_OF_4_WEAK",
        "T5_PRICE_ALL_4_WEAK",
    ):
        assert not policy_decision(row, policy)["exit_triggered"]


def test_maximum_drawdown_uses_chronological_policy_points():
    assert maximum_drawdown([10, -4, -9, 5]) == 13


def test_metrics_distinguish_saved_loser_and_harmed_winner():
    rows = [
        {
            "policy_points": -5.0, "control_points": -20.0,
            "delta_vs_control": 15.0, "exit_triggered": True,
            "control_plus20_move": False, "plus20_reached_by_t5": False,
            "control_top_decile_move": False, "top_decile_reached_by_t5": False,
        },
        {
            "policy_points": -2.0, "control_points": 30.0,
            "delta_vs_control": -32.0, "exit_triggered": True,
            "control_plus20_move": True, "plus20_reached_by_t5": False,
            "control_top_decile_move": False, "top_decile_reached_by_t5": False,
        },
    ]
    result = metrics(rows)
    assert result["bad_trades_saved"] == 1
    assert result["control_winners_exited"] == 1
    assert result["points_saved_on_control_losers"] == 15
    assert result["points_lost_on_control_winners"] == 32
    assert result["plus20_moves_destroyed"] == 1
