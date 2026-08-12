from red_bar_lab.execution.exit_engine import PaperExitEngine


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


def test_hard_stop_has_exit_authority():
    result = PaperExitEngine().evaluate(
        position=_position(current=84.0),
        option_candle=_healthy_candle(),
    )
    assert result.action == "EXIT"
    assert result.hard_exit_reason == "HARD_STOP"


def test_target_one_exits():
    result = PaperExitEngine().evaluate(
        position=_position(current=126.0, mfe=26.0),
        option_candle=_healthy_candle(),
    )
    assert result.action == "EXIT"
    assert result.hard_exit_reason == "TARGET_1"


def test_breakeven_arms_after_fifteen_percent_peak():
    result = PaperExitEngine().evaluate(
        position=_position(current=112.0, mfe=16.0),
        option_candle=_healthy_candle(),
    )
    assert result.breakeven_armed is True
    assert result.breakeven_price == 100.0
    assert result.effective_stop >= 100.0


def test_trailing_activates_after_twenty_percent_peak():
    result = PaperExitEngine().evaluate(
        position=_position(current=118.0, mfe=25.0),
        option_candle=_healthy_candle(),
    )
    assert result.trailing_active is True
    assert result.trailing_stop == 112.5
    assert result.effective_stop >= 112.5


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
