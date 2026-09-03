from datetime import datetime, timedelta, timezone

import pytest

from red_bar_lab.execution.execution_policy import (
    DIRECTIONAL_REGIME_STRATEGY_SOURCE,
    RED_BAR_V2_STRATEGY_SOURCE,
    RSI_EXIT_MODE,
)
from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.services.red_bar_v2_structural_exit import (
    STRUCTURAL_EXIT_REASON,
    RedBarV2StructuralExit,
)


def _position(
    *,
    entry=100.0,
    current=100.0,
    stop=85.0,
    target=125.0,
    target2=140.0,
    mfe=0.0,
):
    return {
        "entry_price": entry,
        "current_price": current,
        "stop_price": stop,
        "initial_stop_price": stop,
        "target1_price": target,
        "target2_price": target2,
        "mfe_points": mfe,
    }


def _healthy_candle():
    return {
        "close": 110.0,
        "vwap": 105.0,
        "ema9": 108.0,
        "ema21": 106.0,
        "momentum_pct": 1.0,
        "relative_volume": 1.2,
    }


def _ema_signal(direction, close, ema10):
    return {
        "direction": direction,
        "confirmation_high": 24600.0,
        "confirmation_low": 24500.0,
        "_ema10_5m_ready": True,
        "_ema10_5m_close": close,
        "_ema10_5m_value": ema10,
    }


def test_hard_stop_has_exit_authority():
    result = PaperExitEngine().evaluate(
        position=_position(current=84.0),
        option_candle=_healthy_candle(),
    )
    assert result.action == "EXIT"
    assert result.hard_exit_reason == "HARD_STOP"


def test_fixed_target_is_informational_only_and_does_not_exit():
    result = PaperExitEngine().evaluate(
        position=_position(current=126.0, mfe=26.0),
        option_candle=_healthy_candle(),
    )
    assert result.target1 == 125.0
    assert result.hard_exit_reason is None
    assert result.action == "HOLD / TRAIL"


def test_bullish_completed_5m_close_below_ema10_exits():
    result = PaperExitEngine().evaluate(
        position=_position(current=108.0),
        option_candle=_healthy_candle(),
        signal=_ema_signal("BULLISH", 24540.0, 24550.0),
        current_underlying=24540.0,
    )
    assert result.ema10_trend == "LOST"
    assert result.hard_exit_reason == "BULLISH_EMA10_EXIT"
    assert result.action == "EXIT"


def test_bearish_completed_5m_close_above_ema10_exits():
    result = PaperExitEngine().evaluate(
        position=_position(current=108.0),
        option_candle=_healthy_candle(),
        signal=_ema_signal("BEARISH", 24560.0, 24550.0),
        current_underlying=24560.0,
    )
    assert result.ema10_trend == "LOST"
    assert result.hard_exit_reason == "BEARISH_EMA10_EXIT"
    assert result.action == "EXIT"


def test_ema10_touch_does_not_exit_completed_trend():
    bullish = PaperExitEngine().evaluate(
        position=_position(current=108.0),
        option_candle=_healthy_candle(),
        signal=_ema_signal("BULLISH", 24550.0, 24550.0),
        current_underlying=24550.0,
    )
    bearish = PaperExitEngine().evaluate(
        position=_position(current=108.0),
        option_candle=_healthy_candle(),
        signal=_ema_signal("BEARISH", 24550.0, 24550.0),
        current_underlying=24550.0,
    )
    assert bullish.ema10_trend == "VALID"
    assert bearish.ema10_trend == "VALID"
    assert bullish.hard_exit_reason is None
    assert bearish.hard_exit_reason is None


def test_breakeven_arms_after_current_five_percent_policy():
    result = PaperExitEngine().evaluate(
        position=_position(current=106.0, mfe=6.0),
        option_candle=_healthy_candle(),
    )
    assert result.breakeven_armed is True
    assert result.breakeven_price == 100.0
    assert result.effective_stop >= 100.0


def test_trailing_uses_peak_and_current_five_percent_distance():
    result = PaperExitEngine().evaluate(
        position=_position(current=118.0, mfe=25.0),
        option_candle=_healthy_candle(),
    )
    assert result.trailing_active is True
    assert result.peak_price == 125.0
    assert result.trailing_stop == 118.75
    assert result.effective_stop == 118.75


def test_profit_lock_wins_when_trailing_is_active_but_lower():
    result = PaperExitEngine(trailing_distance_pct=25.0).evaluate(
        position=_position(current=99.0, stop=85.0, mfe=21.0),
        option_candle=_healthy_candle(),
    )
    assert result.trailing_active is True
    assert result.trailing_stop == 90.75
    assert result.breakeven_price == 100.0
    assert result.profit_lock_price == 102.0
    assert result.effective_stop == 102.0
    assert result.hard_exit_reason == "PROFIT_LOCK_STOP"
    assert result.action == "EXIT"


def test_bearish_nifty_thesis_invalidates_above_confirmation_high():
    result = PaperExitEngine().evaluate(
        position=_position(current=105.0),
        option_candle=_healthy_candle(),
        signal={
            "direction": "BEARISH",
            "confirmation_high": 24600.0,
            "confirmation_low": 24550.0,
        },
        current_underlying=24610.0,
    )
    assert result.nifty_thesis == "INVALID"
    assert result.hard_exit_reason == "NIFTY_INVALIDATION"


def test_opposite_red_bar_exits():
    result = PaperExitEngine().evaluate(
        position=_position(current=104.0),
        option_candle=_healthy_candle(),
        opposite_red_bar_confirmed=True,
    )
    assert result.hard_exit_reason == "OPPOSITE_RED_BAR"


def test_two_option_technical_failures_exit():
    result = PaperExitEngine().evaluate(
        position=_position(current=96.0),
        option_candle={
            "close": 96.0,
            "vwap": 100.0,
            "ema9": 97.0,
            "ema21": 99.0,
            "momentum_pct": 0.1,
            "relative_volume": 0.8,
        },
    )
    assert result.technical_failures == 2
    assert result.hard_exit_reason == "OPTION_TECHNICAL_BREAKDOWN"


def test_oi_pcr_and_greeks_are_shadow_only():
    result = PaperExitEngine().evaluate(
        position=_position(current=103.0),
        option_candle=_healthy_candle(),
        pcr_supportive=False,
        oi_supportive=False,
        greeks_supportive=False,
    )
    assert result.shadow_oi_pcr == "WARNING"
    assert result.shadow_greeks == "WARNING"
    assert result.hard_exit_reason is None


def test_rsi_dynamic_protection_is_delayed_for_first_five_minutes():
    position = _position(current=99.5, stop=93.0, mfe=6.0)
    position["entry_timestamp"] = (
        datetime.now(timezone.utc) - timedelta(minutes=2)
    ).isoformat()

    result = PaperExitEngine().evaluate(
        position=position,
        option_candle=_healthy_candle(),
        exit_mode=RSI_EXIT_MODE,
    )

    assert result.breakeven_armed is False
    assert result.profit_lock_active is False
    assert result.trailing_active is False
    assert result.effective_stop == 93.0
    assert result.hard_exit_reason is None
    assert "RSI_DYNAMIC_PROTECTION_DELAY_ACTIVE=300s" in result.reasons


def test_rsi_hard_stop_remains_active_during_protection_delay():
    position = _position(current=92.0, stop=93.0, mfe=6.0)
    position["entry_timestamp"] = (
        datetime.now(timezone.utc) - timedelta(minutes=2)
    ).isoformat()

    result = PaperExitEngine().evaluate(
        position=position,
        option_candle=_healthy_candle(),
        exit_mode=RSI_EXIT_MODE,
    )

    assert result.breakeven_armed is False
    assert result.hard_exit_reason == "HARD_STOP"
    assert result.action == "EXIT"


def test_rsi_breakeven_arms_after_five_minute_delay():
    position = _position(current=99.5, stop=93.0, mfe=6.0)
    position["entry_timestamp"] = (
        datetime.now(timezone.utc) - timedelta(minutes=6)
    ).isoformat()

    result = PaperExitEngine().evaluate(
        position=position,
        option_candle=_healthy_candle(),
        exit_mode=RSI_EXIT_MODE,
    )

    assert result.breakeven_armed is True
    assert result.effective_stop == 100.0
    assert result.hard_exit_reason == "BREAKEVEN_STOP"


# ---------------------------------------------------------------------------
# A Red Bar V2 row has exactly three exits: earned premium protection, EOD, and
# a completed 1-minute close against the governing level. Everything else this
# engine computes about a V2 row is evidence and cannot close it.
#
# The gate keys on strategy identity, not on ``exit_mode``. Live already passes
# the premium-protection mode for every source, so the proxies were shadowed
# there by accident; research and the read-only panels pass no mode at all.
# ---------------------------------------------------------------------------


def _v2_position(**overrides):
    position = _position(**overrides)
    position["execution_strategy_source"] = RED_BAR_V2_STRATEGY_SOURCE
    return position


def _broken_option_candle():
    """Option VWAP and EMA both lost -- two technical failures, weak volume."""
    return {
        "close": 96.0,
        "vwap": 100.0,
        "ema9": 97.0,
        "ema21": 99.0,
        "momentum_pct": 0.1,
        "relative_volume": 0.8,
    }


def _invalidating_signal():
    return {
        "direction": "BEARISH",
        "confirmation_high": 24600.0,
        "confirmation_low": 24550.0,
    }


# Each case is a set of ``evaluate`` arguments under which a row with no
# strategy identity exits on exactly one option-premium or correlation proxy.
PROXY_CASES = {
    "BULLISH_EMA10_EXIT": dict(
        option_candle=_healthy_candle(),
        signal=_ema_signal("BULLISH", 24540.0, 24550.0),
        current_underlying=24540.0,
    ),
    "NIFTY_INVALIDATION": dict(
        option_candle=_healthy_candle(),
        signal=_invalidating_signal(),
        current_underlying=24610.0,
    ),
    "OPPOSITE_RED_BAR": dict(
        option_candle=_healthy_candle(),
        opposite_red_bar_confirmed=True,
    ),
    "OPTION_TECHNICAL_BREAKDOWN": dict(
        option_candle=_broken_option_candle(),
    ),
}


@pytest.mark.parametrize("expected", sorted(PROXY_CASES))
def test_a_proxy_that_closes_an_ordinary_row_cannot_close_a_red_bar_v2_row(expected):
    arguments = PROXY_CASES[expected]

    ordinary = PaperExitEngine().evaluate(
        position=_position(current=104.0),
        **arguments,
    )
    v2 = PaperExitEngine().evaluate(
        position=_v2_position(current=104.0),
        **arguments,
    )

    assert ordinary.hard_exit_reason == expected
    assert ordinary.action == "EXIT"

    assert v2.hard_exit_reason is None
    assert v2.action == "HOLD"
    # The proxy is not silenced, only disarmed: it still says its name.
    shadowed = [
        reason for reason in v2.reasons
        if reason.startswith("SHADOW_EXIT_WARNINGS=")
    ]
    assert shadowed, v2.reasons
    assert expected in shadowed[0]


def test_every_proxy_is_reported_together_on_a_red_bar_v2_row():
    """One cycle, all four proxies broken: one warning line, nothing closed."""
    result = PaperExitEngine().evaluate(
        position=_v2_position(current=96.0),
        option_candle=_broken_option_candle(),
        signal={
            **_ema_signal("BULLISH", 24540.0, 24550.0),
            "confirmation_low": 24600.0,
        },
        current_underlying=24540.0,
        opposite_red_bar_confirmed=True,
    )

    assert result.hard_exit_reason is None
    assert result.action == "HOLD"
    assert (
        "Structural and premium-protection exits remain authoritative."
        in result.reasons
    )
    warning = next(
        reason for reason in result.reasons
        if reason.startswith("SHADOW_EXIT_WARNINGS=")
    )
    for name in (
        "BULLISH_EMA10_EXIT",
        "NIFTY_INVALIDATION",
        "OPPOSITE_RED_BAR",
        "OPTION_TECHNICAL_BREAKDOWN",
    ):
        assert name in warning
    # The evidence still scores, which is the whole point of keeping it.
    assert result.health_score < 50
    assert result.nifty_thesis == "INVALID"
    assert result.ema10_trend == "LOST"
    assert result.technical_failures == 2


def test_weak_evidence_advises_a_tighten_on_an_ordinary_row_and_a_hold_on_v2():
    """No panel should advise an action the engine would refuse to take."""
    candle = {
        "close": 99.0,
        "vwap": 100.0,
        "ema9": 108.0,
        "ema21": 106.0,
        "momentum_pct": 1.0,
        "relative_volume": 0.8,
    }

    ordinary = PaperExitEngine().evaluate(
        position=_position(current=99.0),
        option_candle=candle,
    )
    v2 = PaperExitEngine().evaluate(
        position=_v2_position(current=99.0),
        option_candle=candle,
    )

    assert ordinary.technical_failures == 1
    assert ordinary.hard_exit_reason is None
    assert ordinary.action == "TIGHTEN"

    assert v2.health_score == ordinary.health_score
    assert v2.hard_exit_reason is None
    assert v2.action == "HOLD"


def test_a_red_bar_v2_row_keeps_its_earned_premium_stop():
    result = PaperExitEngine().evaluate(
        position=_v2_position(current=118.0, mfe=25.0),
        option_candle=_healthy_candle(),
    )

    assert result.trailing_active is True
    assert result.trailing_stop == 118.75
    assert result.hard_exit_reason == "TRAILING_STOP"
    assert result.action == "EXIT"


def test_a_red_bar_v2_row_keeps_eod():
    result = PaperExitEngine().evaluate(
        position=_v2_position(current=104.0),
        option_candle=_healthy_candle(),
        eod_due=True,
    )

    assert result.effective_stop is None
    assert result.hard_exit_reason == "EOD_EXIT"
    assert result.action == "EXIT"


def test_a_red_bar_v2_row_keeps_the_structural_exit():
    result = PaperExitEngine().evaluate(
        position=_v2_position(current=104.0),
        option_candle=_healthy_candle(),
        structural_exit=RedBarV2StructuralExit(
            breached=True,
            status="STRUCTURE_BREACHED",
            governing_reference="WORKING",
            governing_midpoint=23_897.5,
            level_source="ENTRY",
            direction="BULLISH",
            close=23_890.0,
            distance_points=-7.5,
        ),
    )

    assert result.hard_exit_reason == STRUCTURAL_EXIT_REASON
    assert result.action == "EXIT"
    assert result.governing_midpoint == 23_897.5


def test_the_three_surviving_exits_keep_their_order_of_authority():
    """Stop, then EOD, then structure -- with all three due at once."""
    breached = RedBarV2StructuralExit(
        breached=True,
        status="STRUCTURE_BREACHED",
        governing_reference="RED_BAR",
        governing_midpoint=23_997.0,
        close=23_990.0,
    )

    everything = PaperExitEngine().evaluate(
        position=_v2_position(current=118.0, mfe=25.0),
        option_candle=_broken_option_candle(),
        eod_due=True,
        structural_exit=breached,
    )
    without_the_stop = PaperExitEngine().evaluate(
        position=_v2_position(current=104.0),
        option_candle=_broken_option_candle(),
        eod_due=True,
        structural_exit=breached,
    )
    structure_alone = PaperExitEngine().evaluate(
        position=_v2_position(current=104.0),
        option_candle=_broken_option_candle(),
        structural_exit=breached,
    )

    assert everything.hard_exit_reason == "TRAILING_STOP"
    assert without_the_stop.hard_exit_reason == "EOD_EXIT"
    assert structure_alone.hard_exit_reason == STRUCTURAL_EXIT_REASON


@pytest.mark.parametrize(
    "position_extra,signal",
    [
        ({"execution_strategy_source": RED_BAR_V2_STRATEGY_SOURCE}, None),
        ({}, {"level_type": "RED_BAR_V2"}),
        ({}, {"signal_id": "RBV2-ABCDEF0123456789"}),
        ({"signal_id": "RBV2-ABCDEF0123456789"}, None),
    ],
)
def test_v2_identity_disarms_the_proxies_however_it_arrives(position_extra, signal):
    """The gate is only as good as the identity resolution behind it."""
    position = _position(current=104.0)
    position.update(position_extra)

    result = PaperExitEngine().evaluate(
        position=position,
        option_candle=_healthy_candle(),
        signal=signal,
        opposite_red_bar_confirmed=True,
    )

    assert result.opposite_red_bar == "YES"
    assert result.hard_exit_reason is None
    assert result.action == "HOLD"


def test_a_directional_regime_row_keeps_every_proxy():
    """This engine is shared. Trimming V2's exits must not trim anyone else's."""
    position = _position(current=104.0)
    position["execution_strategy_source"] = DIRECTIONAL_REGIME_STRATEGY_SOURCE

    result = PaperExitEngine().evaluate(
        position=position,
        option_candle=_healthy_candle(),
        opposite_red_bar_confirmed=True,
    )

    assert result.hard_exit_reason == "OPPOSITE_RED_BAR"
    assert result.action == "EXIT"


def test_a_red_bar_v2_row_is_not_told_to_watch_a_trigger_that_cannot_fire():
    result = PaperExitEngine().evaluate(
        position=_v2_position(current=104.0),
        option_candle=_healthy_candle(),
        signal=_ema_signal("BULLISH", 24560.0, 24550.0),
        current_underlying=24560.0,
    )

    assert result.ema10_trend == "VALID"
    assert "EMA10" not in result.next_trigger
    assert result.next_trigger == "EOD session flat"
