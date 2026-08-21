from datetime import datetime, timezone

from red_bar_lab.ui.market_at_a_glance import build_market_at_a_glance

NOW = datetime(2026, 8, 21, 6, 5, tzinfo=timezone.utc)
STAMP = "2026-08-21T06:04:00+00:00"


def _summary(ce=74.0, pe=56.0, ce_slope=3.0, pe_slope=0.5):
    return {
        "ce_score": ce,
        "pe_score": pe,
        "ce_score_slope": ce_slope,
        "pe_score_slope": pe_slope,
        "eligible_ce": 4,
        "eligible_pe": 4,
        "rejected": 0,
        "observed_at": STAMP,
    }


def _futures(state="LONG_BUILDUP", strength="STRONG"):
    return {
        "positioning_state": state,
        "strength": strength,
        "observed_at": STAMP,
        "latest_timestamp": STAMP,
    }


def _underlying(
    direction="BULLISH",
    state="BULLISH_STRUCTURE",
    rsi_view="BULLISH",
    acceptance="HOLD_CONFIRMED",
):
    return {
        "direction": direction,
        "state": state,
        "momentum": "EXPANDING",
        "acceptance_state": acceptance,
        "rsi_view": rsi_view,
        "rsi": 61.0,
        "rsi_slope": 3.0,
        "observed_at": STAMP,
        "reason": "test",
    }


def test_market_at_a_glance_confirms_only_after_hold_and_derivatives_agree():
    view = build_market_at_a_glance(_summary(), _futures(), _underlying(), now=NOW)
    assert view["market_state"] == "CONFIRMED BULLISH"
    assert view["trade_bias"] == "BUY CE"
    assert view["evidence_status"] == "ALIGNED_TO_COMPLETED_5M"


def test_market_at_a_glance_hold_pending_is_early_only():
    view = build_market_at_a_glance(
        _summary(),
        _futures(),
        _underlying(state="BREAK_DETECTED_UP", acceptance="HOLD_PENDING"),
        now=NOW,
    )
    assert view["market_state"] == "EARLY BULLISH TRANSITION"
    assert view["trade_bias"] == "WAIT"


def test_market_at_a_glance_underlying_direction_owns_conflict():
    view = build_market_at_a_glance(
        _summary(ce=55.0, pe=75.0, ce_slope=0.0, pe_slope=3.0),
        _futures(state="LONG_BUILDUP"),
        _underlying(direction="BEARISH", state="BEARISH_STRUCTURE", rsi_view="BEARISH"),
        now=NOW,
    )
    assert view["market_state"] == "CONFLICTED"
    assert view["trade_bias"] == "WAIT"


def test_market_at_a_glance_uses_futures_market_candle_for_alignment():
    now = datetime(2026, 8, 21, 6, 23, 58, tzinfo=timezone.utc)
    summary = _summary()
    summary["observed_at"] = "2026-08-21T06:23:34+00:00"
    futures = _futures()
    futures["observed_at"] = "2026-08-21T06:23:40+00:00"
    futures["latest_timestamp"] = "2026-08-21T06:20:00+00:00"
    underlying = _underlying()
    underlying["observed_at"] = "2026-08-21T06:20:00+00:00"

    view = build_market_at_a_glance(summary, futures, underlying, now=now)

    assert view["evidence_status"] == "ALIGNED_TO_COMPLETED_5M"
    assert view["alignment_gap_seconds"] == 214.0
    assert view["market_state"] == "CONFIRMED BULLISH"


def test_market_at_a_glance_rejects_stale_futures_collection_even_with_recent_candle():
    now = datetime(2026, 8, 21, 6, 30, tzinfo=timezone.utc)
    summary = _summary()
    summary["observed_at"] = "2026-08-21T06:29:30+00:00"
    futures = _futures()
    futures["observed_at"] = "2026-08-21T06:20:00+00:00"
    futures["latest_timestamp"] = "2026-08-21T06:25:00+00:00"
    underlying = _underlying()
    underlying["observed_at"] = "2026-08-21T06:25:00+00:00"

    view = build_market_at_a_glance(summary, futures, underlying, now=now)

    assert view["evidence_status"] == "STALE"
    assert view["market_state"] == "UNAVAILABLE"


def test_option_persistence_can_support_early_transition_but_not_confirm():
    view = build_market_at_a_glance(
        _summary(ce=48.0, pe=42.0, ce_slope=2.0, pe_slope=-0.5),
        _futures(),
        _underlying(),
        now=NOW,
    )
    assert view["option_direction"] == "WAIT"
    assert view["option_momentum"] == "BULLISH"
    assert view["market_state"] == "EARLY BULLISH TRANSITION"
    assert view["trade_bias"] == "WAIT"


def test_market_at_a_glance_rejects_illiquid_contract_set():
    summary = _summary()
    summary["eligible_pe"] = 0
    view = build_market_at_a_glance(summary, _futures(), _underlying(), now=NOW)
    assert view["market_state"] == "UNAVAILABLE"
