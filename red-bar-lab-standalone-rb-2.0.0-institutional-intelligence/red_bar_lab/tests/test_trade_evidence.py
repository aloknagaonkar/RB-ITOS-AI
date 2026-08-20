from red_bar_lab.services.trade_evidence import build_trade_evidence_recommendation


def _readiness(**overrides):
    base = {
        "overall_status": "READY",
        "option_quote_status": "READY",
        "v2_alignment_status": "ALIGNED",
        "market_hours_status": "OPEN",
        "blocking_reasons": [],
        "advisory_reasons": [],
        "execution_reasons": [],
        "futures_strength": "STRONG",
    }
    base.update(overrides)
    return base


def test_strong_bullish_signal_suggests_ce():
    result = build_trade_evidence_recommendation(
        readiness=_readiness(),
        signal_diagnostic={
            "direction": "BULLISH",
            "best_candidate": "NIFTY 24300 CE",
            "best_score": 78,
        },
        futures_snapshot={"positioning_state": "LONG_BUILDUP", "strength": "STRONG"},
    )
    assert result.suggested_option == "CE"
    assert result.grade == "STRONG"
    assert result.action == "PAPER TRADE ELIGIBLE"
    assert "FUTURES_LONG_BUILDUP_SUPPORTIVE" in result.positive_evidence
    assert result.authority == "OBSERVATIONAL_ONLY"


def test_strong_bearish_signal_suggests_pe():
    result = build_trade_evidence_recommendation(
        readiness=_readiness(),
        signal_diagnostic={"direction": "BEARISH"},
        futures_snapshot={"positioning_state": "SHORT_BUILDUP", "strength": "STRONG"},
    )
    assert result.suggested_option == "PE"
    assert result.grade == "STRONG"


def test_weak_support_is_cautious():
    result = build_trade_evidence_recommendation(
        readiness=_readiness(
            overall_status="DEGRADED",
            advisory_reasons=["FUTURES_STRENGTH_WEAK"],
            futures_strength="WEAK",
        ),
        signal_diagnostic={"direction": "BULLISH"},
        futures_snapshot={"positioning_state": "LONG_BUILDUP", "strength": "WEAK"},
    )
    assert result.grade == "CAUTIOUS"
    assert result.action == "WAIT FOR CONFIRMATION"


def test_strong_contrary_futures_is_conflicted():
    result = build_trade_evidence_recommendation(
        readiness=_readiness(),
        signal_diagnostic={"direction": "BULLISH"},
        futures_snapshot={"positioning_state": "SHORT_BUILDUP", "strength": "STRONG"},
    )
    assert result.grade == "CONFLICTED"
    assert result.action == "WAIT — FUTURES CONTRADICT SIGNAL"


def test_blocking_reason_prevents_trade_suggestion():
    result = build_trade_evidence_recommendation(
        readiness=_readiness(
            overall_status="BLOCKED",
            blocking_reasons=["OPTION_QUOTE_UNAVAILABLE"],
            option_quote_status="UNAVAILABLE",
        ),
        signal_diagnostic={"direction": "BULLISH"},
        futures_snapshot={"positioning_state": "LONG_BUILDUP", "strength": "STRONG"},
    )
    assert result.grade == "BLOCKED"
    assert result.action == "DO NOT TRADE"
    assert result.blocking_evidence == ("OPTION_QUOTE_UNAVAILABLE",)


def test_after_hours_signal_waits_for_entry_hours():
    result = build_trade_evidence_recommendation(
        readiness=_readiness(
            overall_status="DEGRADED",
            market_hours_status="OUTSIDE_ENTRY_HOURS",
            option_quote_status="MARKET_CLOSED",
            execution_reasons=["MARKET_HOURS_OUTSIDE_ENTRY_HOURS"],
        ),
        signal_diagnostic={"direction": "BULLISH"},
        futures_snapshot={"positioning_state": "LONG_BUILDUP", "strength": "STRONG"},
    )
    assert result.grade == "CAUTIOUS"
    assert result.action == "WAIT FOR ENTRY HOURS"


def test_missing_direction_waits_for_signal():
    result = build_trade_evidence_recommendation(
        readiness=_readiness(),
        signal_diagnostic={},
        futures_snapshot={},
    )
    assert result.grade == "NO_SIGNAL"
    assert result.suggested_option == "—"
    assert result.action == "WAIT FOR RED BAR V2 SIGNAL"
