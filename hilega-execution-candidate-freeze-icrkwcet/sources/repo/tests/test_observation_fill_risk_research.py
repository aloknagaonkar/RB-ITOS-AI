import pytest
from market_lab.observation_fill_risk_research import RiskBudget, OptionQuoteScenario, project_option_scenario, capital_weighted_equity


def test_spread_gap_charges_and_combined_capital_limit():
    b = RiskBudget(100000, .01, .02, .10, .05, existing_premium_exposure=4000)
    q = OptionQuoteScenario(100, 98, 90, 70, 50, 1, 1, 25)
    result = project_option_scenario(b, q)
    assert result["entry_cost_per_contract"] == 5050
    assert result["net_mark_to_exit_per_contract"] == -225
    assert result["gap_adjusted_worst_loss_per_contract"] == 1625
    assert result["informational_max_lots"] == 0  # combined exposure has only 1000 left
    assert result["quantity"] is None and result["order_created"] is False


def test_partial_fill_and_nonfinite_input_fail_closed():
    b = RiskBudget(100000, .02, .02, .5, .5)
    q = OptionQuoteScenario(100, 98, 90, 70, 50, 0, 0, 0, fill_fraction=.5)
    assert project_option_scenario(b, q)["blocked_reason"] == "PARTIAL_OR_REJECTED_FILL"
    with pytest.raises(ValueError, match="finite"):
        project_option_scenario(b, OptionQuoteScenario(float('nan'), 98, 90, 70, 50, 0, 0, 0))


def test_equity_drawdown_uses_cash_marks_in_order():
    result = capital_weighted_equity(100000, [("2026-09-29T10:00", 1000),
                                              ("2026-09-29T10:01", -3000)])
    assert result["latest_equity"] == 98000
    assert result["max_drawdown_fraction"] == pytest.approx(3000/101000)
