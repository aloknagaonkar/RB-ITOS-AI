from red_bar_lab.services.market_trend_research.contract_selection import (
    _activity_interpretation,
    pcr_research_preference,
    research_direction,
    select_best_contracts,
    two_page_preference,
)


def test_option_activity_interpretation_is_side_aware():
    assert _activity_interpretation("PE", "SHORT_BUILDUP") == "Put writing — bullish/support"
    assert _activity_interpretation("PE", "LONG_BUILDUP") == "Put buying/hedging — bearish concern"
    assert _activity_interpretation("CE", "SHORT_COVERING") == "Call short covering — bullish"
    assert _activity_interpretation("CE", "SHORT_BUILDUP") == "Call writing — bearish/resistance"


def test_pcr_preference_does_not_require_direction_validation():
    assert pcr_research_preference("BULLISH")[:2] == ("CE", "PASSED")
    assert pcr_research_preference("BEARISH")[:2] == ("PE", "PASSED")
    assert pcr_research_preference("CONFLICT")[:2] == ("NONE", "WAIT")


def _row(strike: float, side: str, *, premium: float = 4.0, oi_change: float = 200.0):
    return {
        "option_type": side,
        "strike": strike,
        "expiry": "2026-08-25",
        "tradingsymbol": f"NIFTY{strike:.0f}{side}",
        "current_price": 100.0,
        "delta": 0.5 if side == "CE" else -0.5,
        "vwap": 95.0,
        "iv": 15.0,
        "oi": 10_000.0 + strike,
        "volume": 20_000.0 + strike,
        "bid": 99.5,
        "ask": 100.5,
        "premium_change_from_previous_refresh_pct": premium,
        "oi_change_from_previous_refresh": oi_change,
        "previous_refresh_oi": 10_000.0,
        "oi_change_pct": 12.0,
    }


def test_two_pages_must_agree_before_side_is_selected():
    assert two_page_preference(
        trend_direction="BULLISH",
        validation_direction="BULLISH",
        validation_ready=True,
    )[:2] == ("CE", "PASSED")
    assert two_page_preference(
        trend_direction="BEARISH",
        validation_direction="BULLISH",
        validation_ready=True,
    )[:2] == ("NONE", "CONFLICT")


def test_morning_opposition_blocks_trend_research_direction():
    direction, _ = research_direction(
        combined_direction="BEARISH",
        combined_ready=True,
        current_direction="BEARISH",
        current_ready=True,
        morning_direction="BULLISH",
    )
    assert direction == "CONFLICT"


def test_selects_only_four_eligible_contracts_on_approved_side():
    rows = [_row(24_000 + 50 * index, "PE") for index in range(6)]
    rows.extend(_row(24_000 + 50 * index, "CE") for index in range(6))
    selected = select_best_contracts(
        rows,
        preferred_side="PE",
        selected_expiry="2026-08-25",
        selected_strikes=frozenset(24_000 + 50 * index for index in range(6)),
    )
    assert len(selected) == 4
    assert all(candidate.side == "PE" for candidate in selected)
    assert [candidate.rank for candidate in selected] == [1, 2, 3, 4]


def test_rejects_noise_stale_identity_and_poor_spread():
    noisy = _row(24_000, "CE", premium=0.2, oi_change=10.0)
    wrong_expiry = {**_row(24_050, "CE"), "expiry": "2026-09-01"}
    wide = {**_row(24_100, "CE"), "bid": 90.0, "ask": 110.0}
    selected = select_best_contracts(
        [noisy, wrong_expiry, wide],
        preferred_side="CE",
        selected_expiry="2026-08-25",
        selected_strikes=frozenset({24_000.0, 24_050.0, 24_100.0}),
    )
    assert selected == ()
