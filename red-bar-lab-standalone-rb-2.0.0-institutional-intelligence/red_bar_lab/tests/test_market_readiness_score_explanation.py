from red_bar_lab.ui.market_readiness_score_explanation import (
    _component_scores,
    _decision_rows,
)


def test_component_breakdown_matches_strike_score_formula():
    components = _component_scores(
        {
            "participation_state": "FRESH_BUYING",
            "current_price": 120.0,
            "vwap": 100.0,
            "volume": 500.0,
            "oi_change": 1000.0,
            "option_rsi": 60.0,
            "delta": 0.50,
        },
        max_side_volume=500.0,
    )

    assert components == {
        "directional": 30.0,
        "vwap": 20.0,
        "volume": 15.0,
        "oi": 15.0,
        "rsi": 10.0,
        "delta": 10.0,
        "total": 100.0,
    }


def test_decision_rows_name_ce_bullish_and_pe_bearish_scores():
    rows = _decision_rows(
        {
            "ce_score": 76.0,
            "pe_score": 59.0,
            "recommended_side": "CE",
            "recommended_direction": "BULLISH",
            "grade": "MODERATE",
        },
        {
            "positioning_state": "LONG_BUILDUP",
        },
    )

    by_check = {row["Decision check"]: row for row in rows}
    assert by_check["Bullish score"]["Live value"] == "76.0"
    assert by_check["Bearish score"]["Live value"] == "59.0"
    assert by_check["Winning score"]["Result"] == "PASS"
    assert by_check["Score separation"]["Result"] == "PASS"
    assert by_check["Higher side"]["Result"] == "BULLISH"
    assert by_check["Futures confirmation"]["Result"] == "CONFIRMS"
    assert by_check["Final independent view"]["Live value"] == "CE"
