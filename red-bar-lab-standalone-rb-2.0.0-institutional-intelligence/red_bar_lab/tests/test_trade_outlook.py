from red_bar_lab.ui.trade_outlook import build_trade_outlook


def test_pe_outlook_strengthens_from_premium_delta_and_spread():
    result = build_trade_outlook(
        {"status": "OPEN", "option_type": "PE"},
        {
            "unrealized_pnl": 1402.5,
            "entry_price": 142.5,
            "current_price": 161.2,
            "delta_change": -0.15,
            "pcr_change": 0.28,
            "spread_pct": 0.72,
            "freshness": {"status": "FRESH"},
        },
    )

    assert result["recommendation"] == "HOLD PE"
    assert result["outlook"] == "PE MOMENTUM STRENGTHENING"
    assert result["trade_health"] == "FAVORABLE"
    assert result["underlying_bias"] == "BEARISH CONTINUATION"
    assert result["authority"] == "OBSERVATIONAL ONLY"
    assert any("Put OI relative" in item for item in result["observations"])


def test_ce_outlook_flags_weakening_without_exit_authority():
    result = build_trade_outlook(
        {"status": "OPEN", "option_type": "CE"},
        {
            "unrealized_pnl": -500.0,
            "delta_change": -0.12,
            "spread_pct": 2.5,
            "freshness": {"status": "FRESH"},
        },
    )

    assert result["recommendation"] == "MOMENTUM WEAKENING"
    assert result["outlook"] == "CE MOMENTUM WEAKENING"
    assert result["trade_health"] == "WEAKENING"
    assert result["authority"] == "OBSERVATIONAL ONLY"
    assert result["score"] < 0


def test_unavailable_telemetry_returns_monitor_not_buy_or_exit():
    result = build_trade_outlook(
        {"status": "OPEN", "option_type": "PE"},
        {"freshness": {"status": "UNAVAILABLE"}},
    )

    assert result["recommendation"] == "MONITOR"
    assert result["outlook"] == "DATA UNAVAILABLE"
    assert result["confidence_pct"] == 0


def test_closed_trade_is_not_recommended_again():
    result = build_trade_outlook(
        {"status": "CLOSED", "option_type": "PE"},
        {"freshness": {"status": "FRESH"}},
    )

    assert result["recommendation"] == "CLOSED"
    assert result["outlook"] == "TRADE COMPLETE"
