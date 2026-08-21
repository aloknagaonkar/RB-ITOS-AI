from datetime import datetime, timezone

from red_bar_lab.ui.market_at_a_glance import build_market_at_a_glance

NOW = datetime(2026, 8, 21, 6, 5, tzinfo=timezone.utc)
STAMP = "2026-08-21T06:04:00+00:00"


def _summary(ce=74.0, pe=56.0):
    return {
        "ce_score": ce,
        "pe_score": pe,
        "ce_score_slope": 3.0,
        "pe_score_slope": 0.5,
        "eligible_ce": 4,
        "eligible_pe": 4,
        "rejected": 0,
        "observed_at": STAMP,
    }


def _futures(state="LONG_BUILDUP", strength="STRONG"):
    return {"positioning_state": state, "strength": strength, "observed_at": STAMP}


def _underlying(direction="BULLISH", state="BULLISH_STRUCTURE", rsi_view="BULLISH"):
    return {
        "direction": direction,
        "state": state,
        "momentum": "EXPANDING",
        "rsi_view": rsi_view,
        "rsi": 61.0,
        "rsi_slope": 3.0,
        "observed_at": STAMP,
        "reason": "test",
    }


def test_market_at_a_glance_confirms_only_when_underlying_and_derivatives_agree():
    view = build_market_at_a_glance(_summary(), _futures(), _underlying(), now=NOW)
    assert view["market_state"] == "CONFIRMED BULLISH"
    assert view["trade_bias"] == "BUY CE"


def test_market_at_a_glance_underlying_direction_owns_conflict():
    view = build_market_at_a_glance(
        _summary(ce=55.0, pe=75.0),
        _futures(state="LONG_BUILDUP"),
        _underlying(direction="BEARISH", state="BEARISH_STRUCTURE", rsi_view="BEARISH"),
        now=NOW,
    )
    assert view["market_state"] == "CONFLICTED"
    assert view["trade_bias"] == "WAIT"


def test_market_at_a_glance_transition_never_approves_trade():
    underlying = _underlying(state="TRANSITION_UP")
    underlying["momentum"] = "EARLY"
    view = build_market_at_a_glance(_summary(), _futures(), underlying, now=NOW)
    assert view["market_state"] == "EARLY BULLISH TRANSITION"
    assert view["trade_bias"] == "WAIT"


def test_market_at_a_glance_rejects_stale_evidence():
    summary = _summary()
    summary["observed_at"] = "2026-08-21T05:00:00+00:00"
    view = build_market_at_a_glance(summary, _futures(), _underlying(), now=NOW)
    assert view["market_state"] == "UNAVAILABLE"
    assert view["trade_bias"] == "WAIT"


def test_market_at_a_glance_rejects_illiquid_contract_set():
    summary = _summary()
    summary["eligible_pe"] = 0
    view = build_market_at_a_glance(summary, _futures(), _underlying(), now=NOW)
    assert view["market_state"] == "UNAVAILABLE"
