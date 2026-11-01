from scripts.validate_hilega_milega_same_candle_cross_v2_4 import (
    IndicatorPoint,
    evaluate_transition,
)


def test_same_candle_rsi_and_ema_cross_wma_becomes_strong_immediately():
    prev = IndicatorPoint(rsi=48.0, ema3=46.0, wma21=50.0)
    curr = IndicatorPoint(rsi=56.0, ema3=52.0, wma21=51.0)

    r = evaluate_transition(prev, curr, armed=True)

    assert r.rsi_up_wma is True
    assert r.ema_up_wma is True
    assert r.active_setup is True
    assert r.bullish is True
    assert r.strong_bullish is True


def test_rsi_crosses_wma_first_but_ema_still_below_wma_is_not_strong():
    prev = IndicatorPoint(rsi=48.0, ema3=47.0, wma21=50.0)
    curr = IndicatorPoint(rsi=55.0, ema3=49.0, wma21=51.0)

    r = evaluate_transition(prev, curr, armed=True)

    assert r.rsi_up_wma is True
    assert r.active_setup is True
    assert r.bullish is True
    assert r.strong_bullish is False


def test_ema_already_above_wma_when_rsi_crosses_still_becomes_strong():
    prev = IndicatorPoint(rsi=48.0, ema3=52.0, wma21=50.0)
    curr = IndicatorPoint(rsi=56.0, ema3=53.0, wma21=51.0)

    r = evaluate_transition(prev, curr, armed=True)

    assert r.rsi_up_wma is True
    assert r.ema_up_wma is False
    assert r.active_setup is True
    assert r.bullish is True
    assert r.strong_bullish is True


def test_unarmed_same_candle_cross_does_not_create_active_setup():
    prev = IndicatorPoint(rsi=48.0, ema3=46.0, wma21=50.0)
    curr = IndicatorPoint(rsi=56.0, ema3=52.0, wma21=51.0)

    r = evaluate_transition(prev, curr, armed=False)

    assert r.rsi_up_wma is True
    assert r.ema_up_wma is True
    assert r.active_setup is False
    assert r.bullish is False
    assert r.strong_bullish is False
