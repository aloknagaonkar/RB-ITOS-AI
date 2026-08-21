from red_bar_lab.services.independent_market_recommendation import (
    build_independent_market_recommendation,
)


def _ready(**overrides):
    row = {
        "overall_status": "READY",
        "market_hours_status": "OPEN",
        "option_chain_status": "READY",
        "option_quote_status": "READY",
        "blocking_reasons": [],
        "advisory_reasons": [],
        "execution_reasons": [],
    }
    row.update(overrides)
    return row


def test_bullish_futures_independently_suggest_ce_with_call_delta():
    recommendation = build_independent_market_recommendation(
        readiness=_ready(),
        futures_snapshot={"positioning_state": "LONG_BUILDUP", "strength": "STRONG"},
        option_context={"atm_call_delta": 0.54, "atm_put_delta": -0.46, "pcr_oi": 1.08},
    )
    assert recommendation.direction == "BULLISH"
    assert recommendation.suggested_option == "CE"
    assert recommendation.grade == "STRONG"
    assert recommendation.option_delta == 0.54
    assert recommendation.delta_source == "LATEST_ATM_SIDE"
    assert recommendation.authority == "OBSERVATIONAL_ONLY"


def test_bearish_futures_independently_suggest_pe_with_put_delta():
    recommendation = build_independent_market_recommendation(
        readiness=_ready(),
        futures_snapshot={"positioning_state": "SHORT_BUILDUP", "strength": "STRONG"},
        option_context={"atm_call_delta": 0.49, "atm_put_delta": -0.51},
    )
    assert recommendation.direction == "BEARISH"
    assert recommendation.suggested_option == "PE"
    assert recommendation.option_delta == -0.51
    assert recommendation.action == "BUY PE — PAPER OBSERVATION"


def test_neutral_futures_produce_no_trade_without_red_bar_input():
    recommendation = build_independent_market_recommendation(
        readiness=_ready(),
        futures_snapshot={"positioning_state": "NEUTRAL", "strength": "WEAK"},
    )
    assert recommendation.direction == "NEUTRAL"
    assert recommendation.suggested_option == "—"
    assert recommendation.grade == "NO_TRADE"


def test_blocking_readiness_prevents_independent_trade_suggestion():
    recommendation = build_independent_market_recommendation(
        readiness=_ready(
            overall_status="BLOCKED",
            blocking_reasons=["OPTION_QUOTE_UNAVAILABLE"],
            option_quote_status="UNAVAILABLE",
        ),
        futures_snapshot={"positioning_state": "LONG_BUILDUP", "strength": "STRONG"},
    )
    assert recommendation.suggested_option == "CE"
    assert recommendation.grade == "BLOCKED"
    assert recommendation.action == "DO NOT TRADE"


def test_after_hours_keeps_direction_but_waits_for_entry_hours():
    recommendation = build_independent_market_recommendation(
        readiness=_ready(
            overall_status="DEGRADED",
            market_hours_status="OUTSIDE_ENTRY_HOURS",
            execution_reasons=["MARKET_HOURS_OUTSIDE_ENTRY_HOURS"],
        ),
        futures_snapshot={"positioning_state": "SHORT_COVERING", "strength": "MODERATE"},
        option_context={"candidate_delta": 0.61},
    )
    assert recommendation.direction == "BULLISH"
    assert recommendation.suggested_option == "CE"
    assert recommendation.grade == "CAUTIOUS"
    assert recommendation.action == "WAIT FOR ENTRY HOURS"
    assert recommendation.delta_source == "EXACT_CANDIDATE"


def test_six_strike_ce_lead_becomes_directional_authority_when_available():
    recommendation = build_independent_market_recommendation(
        readiness=_ready(),
        futures_snapshot={"positioning_state": "LONG_BUILDUP", "strength": "STRONG"},
        option_context={"atm_call_delta": 0.52},
        participation={
            "recommended_side": "CE",
            "grade": "STRONG",
            "ce_score": 86.0,
            "pe_score": 42.0,
            "pcr_oi": 0.91,
        },
    )
    assert recommendation.direction == "BULLISH"
    assert recommendation.suggested_option == "CE"
    assert recommendation.grade == "STRONG"
    assert "SIX_STRIKE_CE_LEAD" in recommendation.positive_evidence


def test_six_strike_options_futures_conflict_returns_conflicted_not_forced_trade():
    recommendation = build_independent_market_recommendation(
        readiness=_ready(),
        futures_snapshot={"positioning_state": "SHORT_BUILDUP", "strength": "STRONG"},
        option_context={"atm_call_delta": 0.52},
        participation={
            "recommended_side": "CE",
            "grade": "STRONG",
            "ce_score": 84.0,
            "pe_score": 48.0,
            "pcr_oi": 0.88,
        },
    )
    assert recommendation.suggested_option == "CE"
    assert recommendation.grade == "CONFLICTED"
    assert recommendation.action == "WAIT FOR FUTURES / OPTIONS ALIGNMENT"


def test_six_strike_wait_overrides_directional_futures_for_observational_view():
    recommendation = build_independent_market_recommendation(
        readiness=_ready(),
        futures_snapshot={"positioning_state": "LONG_BUILDUP", "strength": "STRONG"},
        participation={
            "recommended_side": "WAIT",
            "grade": "CONFLICTED",
            "ce_score": 68.0,
            "pe_score": 64.0,
        },
    )
    assert recommendation.direction == "NEUTRAL"
    assert recommendation.suggested_option == "—"
    assert recommendation.grade == "NO_TRADE"
