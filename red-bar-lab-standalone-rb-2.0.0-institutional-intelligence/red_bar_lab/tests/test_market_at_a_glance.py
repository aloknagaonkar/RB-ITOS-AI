from datetime import datetime, timezone

from red_bar_lab.ui.market_at_a_glance import build_market_at_a_glance

_NOW = datetime(2026, 8, 21, 6, 5, tzinfo=timezone.utc)


def _summary(**overrides):
    value = {
        "ce_score": 74.0,
        "pe_score": 56.0,
        "underlying_rsi": 61.0,
        "observed_at": "2026-08-21T11:34:30+05:30",
    }
    value.update(overrides)
    return value


def _futures(**overrides):
    value = {
        "positioning_state": "LONG_BUILDUP",
        "strength": "STRONG",
        "observed_at": "2026-08-21T11:34:45+05:30",
        "latest_timestamp": "2026-08-21T11:34:00+05:30",
    }
    value.update(overrides)
    return value


def test_market_at_a_glance_marks_confirmed_bullish_ce():
    view = build_market_at_a_glance(_summary(), _futures(), now=_NOW)

    assert view["market_state"] == "CONFIRMED BULLISH"
    assert view["trade_bias"] == "BUY CE"
    assert view["score_gap"] == 18.0
    assert view["confirmation"] == "OPTIONS, FUTURES QUALITY AND RSI CONFIRM"
    assert view["rsi_view"] == "BULLISH"
    assert view["evidence_status"] == "ALIGNED"


def test_market_at_a_glance_marks_confirmed_bearish_pe():
    view = build_market_at_a_glance(
        _summary(ce_score=52.0, pe_score=71.0, underlying_rsi=39.0),
        _futures(positioning_state="SHORT_BUILDUP", strength="MODERATE"),
        now=_NOW,
    )

    assert view["market_state"] == "CONFIRMED BEARISH"
    assert view["trade_bias"] == "BUY PE"
    assert view["rsi_view"] == "BEARISH"


def test_market_at_a_glance_marks_transition_when_futures_and_rsi_conflict():
    view = build_market_at_a_glance(
        _summary(ce_score=45.0, pe_score=39.3, underlying_rsi=38.1),
        _futures(positioning_state="LONG_BUILDUP", strength="STRONG"),
        now=_NOW,
    )

    assert view["market_state"] == "CONFLICTED / TRANSITIONAL"
    assert view["trade_bias"] == "WAIT"
    assert view["confirmation"] == "OPTIONS WEAK; FUTURES AND RSI DISAGREE"


def test_market_at_a_glance_marks_options_futures_conflict():
    view = build_market_at_a_glance(
        _summary(ce_score=76.0, pe_score=55.0, underlying_rsi=58.0),
        _futures(positioning_state="SHORT_BUILDUP"),
        now=_NOW,
    )

    assert view["market_state"] == "CONFLICTED"
    assert view["trade_bias"] == "WAIT"
    assert view["confirmation"] == "OPTIONS AND FUTURES DISAGREE"


def test_market_at_a_glance_does_not_convert_missing_score_to_zero():
    view = build_market_at_a_glance(
        _summary(ce_score=None),
        _futures(),
        now=_NOW,
    )

    assert view["market_state"] == "UNAVAILABLE"
    assert view["bullish_score"] is None
    assert view["winning_side"] == "UNAVAILABLE"


def test_market_at_a_glance_blocks_stale_or_misaligned_evidence():
    view = build_market_at_a_glance(
        _summary(observed_at="2026-08-21T11:20:00+05:30"),
        _futures(),
        now=_NOW,
    )

    assert view["market_state"] == "UNAVAILABLE"
    assert view["trade_bias"] == "WAIT"
    assert view["evidence_status"] == "STALE"


def test_market_at_a_glance_treats_weak_futures_as_early_transition():
    view = build_market_at_a_glance(
        _summary(),
        _futures(strength="WEAK"),
        now=_NOW,
    )

    assert view["market_state"] == "EARLY BULLISH TRANSITION"
    assert view["trade_bias"] == "WAIT"
    assert view["confirmation"] == "FUTURES DIRECTION SUPPORTS BUT STRENGTH IS WEAK"
