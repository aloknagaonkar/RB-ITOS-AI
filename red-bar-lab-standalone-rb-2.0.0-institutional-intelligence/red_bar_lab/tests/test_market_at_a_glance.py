from red_bar_lab.ui.market_at_a_glance import build_market_at_a_glance


def test_market_at_a_glance_marks_confirmed_bullish_ce():
    view = build_market_at_a_glance(
        {
            "ce_score": 74.0,
            "pe_score": 56.0,
            "underlying_rsi": 61.0,
        },
        {
            "positioning_state": "LONG_BUILDUP",
            "strength": "STRONG",
        },
    )

    assert view["market_state"] == "BULLISH"
    assert view["trade_bias"] == "BUY CE"
    assert view["score_gap"] == 18.0
    assert view["confirmation"] == "OPTIONS AND FUTURES CONFIRM"
    assert view["rsi_view"] == "BULLISH"


def test_market_at_a_glance_marks_confirmed_bearish_pe():
    view = build_market_at_a_glance(
        {
            "ce_score": 52.0,
            "pe_score": 71.0,
            "underlying_rsi": 39.0,
        },
        {
            "positioning_state": "SHORT_BUILDUP",
        },
    )

    assert view["market_state"] == "BEARISH"
    assert view["trade_bias"] == "BUY PE"
    assert view["confirmation"] == "OPTIONS AND FUTURES CONFIRM"
    assert view["rsi_view"] == "BEARISH"


def test_market_at_a_glance_waits_when_scores_are_too_close():
    view = build_market_at_a_glance(
        {
            "ce_score": 64.0,
            "pe_score": 60.0,
            "underlying_rsi": 50.0,
        },
        {
            "positioning_state": "LONG_BUILDUP",
        },
    )

    assert view["market_state"] == "WAIT / NO CLEAR EDGE"
    assert view["trade_bias"] == "WAIT"
    assert view["score_gap"] == 4.0


def test_market_at_a_glance_marks_options_futures_conflict():
    view = build_market_at_a_glance(
        {
            "ce_score": 76.0,
            "pe_score": 55.0,
            "underlying_rsi": 58.0,
        },
        {
            "positioning_state": "SHORT_BUILDUP",
        },
    )

    assert view["market_state"] == "CONFLICTED"
    assert view["trade_bias"] == "WAIT"
    assert view["confirmation"] == "OPTIONS AND FUTURES DISAGREE"
