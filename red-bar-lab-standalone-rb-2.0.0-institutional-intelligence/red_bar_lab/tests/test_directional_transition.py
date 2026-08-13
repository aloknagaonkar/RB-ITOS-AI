import pandas as pd

from red_bar_lab.intelligence.directional_features import latest_directional_features
from red_bar_lab.intelligence.directional_transition import (
    ShadowDecision,
    ShadowDirection,
    evaluate_shadow_directional_transition,
)
from red_bar_lab.intelligence.shadow_directional_service import ShadowDirectionalService


def candles(count=80, step=1.0):
    rows = []
    price = 100.0
    for index, timestamp in enumerate(
        pd.date_range("2026-08-13 09:15", periods=count, freq="5min")
    ):
        open_price = price
        close = price + step
        rows.append(
            {
                "timestamp": timestamp,
                "open": open_price,
                "high": max(open_price, close) + 0.5,
                "low": min(open_price, close) - 0.2,
                "close": close,
                "volume": 1000 + index * 20,
            }
        )
        price = close
    return pd.DataFrame(rows)


def test_bullish_trend_creates_observation_only_shadow_opinion():
    transition = ShadowDirectionalService().evaluate(
        candles(),
        red_bar_context={"direction": "BULLISH"},
    )
    assert transition.direction is ShadowDirection.BULLISH
    assert transition.decision in {
        ShadowDecision.TRANSITION_FORMING,
        ShadowDecision.SHADOW_SIGNAL,
        ShadowDecision.STRONG_SHADOW_SIGNAL,
    }
    assert transition.red_bar_support == "ALIGNED"
    assert transition.execution_allowed is False


def test_red_bar_does_not_change_directional_score():
    snapshot = latest_directional_features(candles())
    without_red_bar = evaluate_shadow_directional_transition(snapshot)
    with_conflicting_red_bar = evaluate_shadow_directional_transition(
        snapshot,
        red_bar_context={"direction": "BEARISH"},
    )
    assert without_red_bar.confidence == with_conflicting_red_bar.confidence
    assert without_red_bar.direction == with_conflicting_red_bar.direction
    assert with_conflicting_red_bar.red_bar_support == "CONFLICTING"


def test_bearish_market_is_classified_bearish():
    transition = ShadowDirectionalService().evaluate(candles(step=-1.0))
    assert transition.direction is ShadowDirection.BEARISH
    assert transition.execution_allowed is False


def test_persistence_record_explicitly_blocks_execution():
    record = ShadowDirectionalService().evaluate(candles()).as_record()
    assert record["execution_allowed"] is False
    assert "bullish_score" in record
    assert "bearish_score" in record
    assert "regime" in record
