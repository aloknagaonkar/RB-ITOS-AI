from red_bar_lab.services.market_trend_research.volume_confirmation import (
    calculate_volume_confirmation,
    compare_volume_confirmation,
)


def _row(side: str, **overrides):
    row = {
        "option_type": side,
        "expiry": "2026-09-01",
        "strike": 24200.0,
        "tradingsymbol": f"NIFTY 24200 {side}",
        "option_relative_volume": 1.8,
        "interval_volume": 18000.0,
        "premium_change_from_previous_refresh_pct": 4.2,
        "oi_change_from_previous_refresh": 3500.0,
        "current_price": 105.0,
        "vwap": 100.0,
    }
    row.update(overrides)
    return row


def test_ce_volume_confirmation_is_observational_and_confirmed():
    result = calculate_volume_confirmation(
        (
            _row("CE"),
            _row(
                "PE",
                premium_change_from_previous_refresh_pct=-2.0,
                oi_change_from_previous_refresh=1200.0,
            ),
        ),
        preferred_side="CE",
        selected_expiry="2026-09-01",
        selected_strikes=frozenset({24200.0}),
        futures_relative_volume=1.3,
    )

    assert result.status == "CONFIRMED"
    assert result.score == 20.0
    assert result.authority == "OBSERVATIONAL_ONLY"


def test_missing_interval_history_is_incomplete_not_blocking():
    result = calculate_volume_confirmation(
        (_row("PE", option_relative_volume=None),),
        preferred_side="PE",
        selected_expiry="2026-09-01",
        selected_strikes=frozenset({24200.0}),
        futures_relative_volume=1.4,
    )

    assert result.status == "INCOMPLETE"
    assert result.side == "PE"


def test_wait_preference_does_not_select_a_contract():
    result = calculate_volume_confirmation(
        (_row("CE"),),
        preferred_side="WAIT",
        selected_expiry="2026-09-01",
        selected_strikes=frozenset({24200.0}),
        futures_relative_volume=1.4,
    )

    assert result.status == "WAIT"
    assert result.checks == ()


def test_neutral_pcr_can_still_observe_a_ce_volume_lean():
    result = compare_volume_confirmation(
        (
            _row("CE"),
            _row(
                "PE",
                option_relative_volume=0.8,
                premium_change_from_previous_refresh_pct=-2.0,
                oi_change_from_previous_refresh=-1200.0,
                current_price=95.0,
            ),
        ),
        selected_expiry="2026-09-01",
        selected_strikes=frozenset({24200.0}),
        futures_relative_volume=1.3,
    )

    assert result.direction == "LEAN_CE"
    assert result.status == "OBSERVATIONAL"
    assert result.ce.score > result.pe.score
    assert result.authority == "OBSERVATIONAL_ONLY"


def test_volume_comparison_waits_when_one_side_is_missing():
    result = compare_volume_confirmation(
        (_row("CE"),),
        selected_expiry="2026-09-01",
        selected_strikes=frozenset({24200.0}),
        futures_relative_volume=1.3,
    )

    assert result.direction == "WAIT"
    assert result.status == "INCOMPLETE"
