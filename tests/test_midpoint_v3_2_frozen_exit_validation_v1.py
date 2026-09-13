from market_lab.midpoint_v3_2_frozen_exit_validation_v1 import (
    max_consecutive_losses,
    max_drawdown,
    largest_winner_contribution,
    summarize,
)

def test_max_consecutive_losses():
    assert max_consecutive_losses([1, -1, -2, 3, -1, -1, -1, 2]) == 3

def test_max_drawdown():
    # equity: 2, 1, -2, 2 => max DD = -4 from peak 2 to -2
    assert max_drawdown([2, -1, -3, 4]) == -4

def test_largest_winner_contribution():
    out = largest_winner_contribution([10, 5, 1, -2], 1)
    assert out["top_n_sum_pct_points"] == 10
    assert round(out["share_of_all_positive_pnl_pct"], 6) == round(10/16*100, 6)

def test_summarize_payoff():
    rows = [
        {"session_date": "2026-01-01", "direction": "BULLISH", "net_return_pct": 10},
        {"session_date": "2026-01-02", "direction": "BULLISH", "net_return_pct": -5},
        {"session_date": "2026-01-03", "direction": "BULLISH", "net_return_pct": -5},
    ]
    out = summarize(rows)
    assert out["win_rate_pct"] == 100/3
    assert out["average_winner_pct"] == 10
    assert out["average_loser_pct"] == -5
    assert out["payoff_ratio_avg_win_to_avg_loss"] == 2
