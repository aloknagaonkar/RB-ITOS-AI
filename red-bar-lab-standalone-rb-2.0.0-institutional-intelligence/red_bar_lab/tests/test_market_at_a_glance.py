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
    assert view["observed_direction"] == "BULLISH"
    assert view["direction_state"] == "CONFIRMED"
    assert view["evidence_readiness"] == "READY"
    assert view["trade_eligibility"] == "ELIGIBLE"
    assert view["market_state"] == "CONFIRMED BULLISH"
    assert view["trade_bias"] == "BUY CE"


def test_market_at_a_glance_hold_pending_is_early_only():
    view = build_market_at_a_glance(
        _summary(),
        _futures(),
        _underlying(state="BREAK_DETECTED_UP", acceptance="HOLD_PENDING"),
        now=NOW,
    )
    assert view["direction_state"] == "EARLY"
    assert view["trade_eligibility"] == "BLOCKED"
    assert view["market_state"] == "EARLY BULLISH TRANSITION"
    assert view["trade_bias"] == "WAIT"


def test_stale_evidence_preserves_observed_direction_but_blocks_trade():
    now = datetime(2026, 8, 21, 6, 8, 56, tzinfo=timezone.utc)
    summary = _summary(ce=55.0, pe=75.0, ce_slope=0.0, pe_slope=3.0)
    summary["observed_at"] = "2026-08-21T06:05:00+00:00"
    futures = _futures(state="LONG_BUILDUP", strength="WEAK")
    futures["observed_at"] = "2026-08-21T06:08:00+00:00"
    futures["latest_timestamp"] = "2026-08-21T06:05:00+00:00"
    underlying = _underlying(direction="BEARISH", state="BEARISH_STRUCTURE", rsi_view="BEARISH")
    underlying["observed_at"] = "2026-08-21T06:05:00+00:00"

    view = build_market_at_a_glance(
        summary,
        futures,
        underlying,
        now=now,
    )

    assert view["observed_direction"] == "BEARISH"
    assert view["direction_state"] == "CONFIRMED_WITH_CAUTION"
    assert view["evidence_readiness"] == "STALE"
    assert view["trade_eligibility"] == "BLOCKED"
    assert view["trade_bias"] == "WAIT"
    assert "OPTION_SNAPSHOT_STALE" in view["blocking_reasons"]
    assert "WEAK_FUTURES_OPPOSITION" in view["caution_reasons"]


def test_strong_futures_opposition_is_conflict():
    view = build_market_at_a_glance(
        _summary(ce=55.0, pe=75.0, ce_slope=0.0, pe_slope=3.0),
        _futures(state="LONG_BUILDUP", strength="STRONG"),
        _underlying(direction="BEARISH", state="BEARISH_STRUCTURE", rsi_view="BEARISH"),
        now=NOW,
    )
    assert view["observed_direction"] == "BEARISH"
    assert view["direction_state"] == "CONFLICTED"
    assert view["trade_eligibility"] == "BLOCKED"


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

    assert view["evidence_readiness"] == "READY"
    assert view["alignment_gap_seconds"] == 214.0
    assert view["market_state"] == "CONFIRMED BULLISH"


def test_completed_candle_beyond_freshness_limit_is_stale_before_alignment():
    now = datetime(2026, 8, 21, 6, 30, tzinfo=timezone.utc)
    summary = _summary()
    summary["observed_at"] = "2026-08-21T06:29:30+00:00"
    futures = _futures()
    futures["observed_at"] = "2026-08-21T06:29:40+00:00"
    futures["latest_timestamp"] = "2026-08-21T06:22:00+00:00"
    underlying = _underlying()
    underlying["observed_at"] = "2026-08-21T06:29:00+00:00"

    view = build_market_at_a_glance(summary, futures, underlying, now=now)

    assert view["observed_direction"] == "BULLISH"
    assert view["evidence_readiness"] == "STALE"
    assert view["trade_eligibility"] == "BLOCKED"
    assert "FUTURES_MARKET_CANDLE_STALE" in view["blocking_reasons"]


def test_option_persistence_can_support_early_transition_but_not_confirm():
    view = build_market_at_a_glance(
        _summary(ce=48.0, pe=42.0, ce_slope=2.0, pe_slope=-0.5),
        _futures(),
        _underlying(acceptance="HOLD_PENDING"),
        now=NOW,
    )
    assert view["option_direction"] == "WAIT"
    assert view["option_momentum"] == "BULLISH"
    assert view["direction_state"] == "EARLY"
    assert view["trade_bias"] == "WAIT"


def test_illiquid_contract_set_blocks_without_erasing_direction():
    summary = _summary()
    summary["eligible_pe"] = 0
    view = build_market_at_a_glance(summary, _futures(), _underlying(), now=NOW)
    assert view["observed_direction"] == "BULLISH"
    assert view["contract_quality"] == "FAIL"
    assert view["trade_eligibility"] == "BLOCKED"
    assert "NO_ELIGIBLE_PE_CONTRACT" in view["blocking_reasons"]


def test_missing_option_timestamp_produces_deterministic_primary_blocker():
    summary = _summary()
    summary["observed_at"] = None
    view = build_market_at_a_glance(summary, _futures(), _underlying(), now=NOW)
    assert view["evidence_readiness"] == "MISSING"
    assert view["primary_blocker"] == "OPTION_TIMESTAMP_MISSING"
    assert view["next_action"] is not None
