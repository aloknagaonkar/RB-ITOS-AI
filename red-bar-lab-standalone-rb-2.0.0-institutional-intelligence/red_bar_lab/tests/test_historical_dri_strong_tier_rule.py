import pandas as pd

from red_bar_lab.services.historical_dri_quality_refinement import (
    evaluate_reset_override_quality,
)


MOMENT = pd.Timestamp("2026-08-14 10:00:00", tz="Asia/Kolkata")


def _candles(*, open_price, high, low, close, latest_volume, prior_volume=100.0):
    timestamps = pd.date_range(
        end=MOMENT,
        periods=20,
        freq="min",
        tz="Asia/Kolkata",
    )
    rows = []
    for timestamp in timestamps[:-1]:
        rows.append(
            {
                "timestamp": timestamp,
                "open": 100.0,
                "high": 100.5,
                "low": 99.5,
                "close": 100.1,
                "volume": prior_volume,
            }
        )
    rows.append(
        {
            "timestamp": timestamps[-1],
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": latest_volume,
        }
    )
    return pd.DataFrame(rows)


def _evaluate(candles, *, break_level, candidate_score=50.0, health=50.0,
              ema10=False, ema30=False, reversal=False):
    return evaluate_reset_override_quality(
        candles,
        moment=MOMENT,
        direction="BULLISH",
        reset_classification="RESET_WINDOW_CONFIRMED",
        reset_rebreak_reason="RESET_MOMENTUM_REEXPANSION",
        break_level=break_level,
        candidate_score=candidate_score,
        opportunity_health=health,
        ema10_ok=ema10,
        ema30_ok=ema30,
        reversal_confirmed=reversal,
    )


def test_one_strong_condition_does_not_create_strong_tier():
    result = _evaluate(
        _candles(
            open_price=100.0,
            high=102.0,
            low=99.5,
            close=101.8,
            latest_volume=100.0,
        ),
        break_level=102.0,
    )

    assert result["body_quality_ok"] is True
    assert result["break_distance_ok"] is False
    assert result["relative_volume_ok"] is False
    assert result["market_action_tier"] == "NONE"
    assert result["market_action_passed"] is False
    assert result["passed"] is False


def test_two_strong_conditions_do_not_create_strong_tier():
    result = _evaluate(
        _candles(
            open_price=100.0,
            high=102.0,
            low=99.5,
            close=101.8,
            latest_volume=100.0,
        ),
        break_level=101.7,
    )

    assert result["body_quality_ok"] is True
    assert result["break_distance_ok"] is True
    assert result["relative_volume_ok"] is False
    assert result["market_action_count"] == 2
    assert result["market_action_tier"] == "NONE"
    assert result["passed"] is False


def test_all_three_conditions_create_strong_tier():
    result = _evaluate(
        _candles(
            open_price=100.0,
            high=102.0,
            low=99.5,
            close=101.8,
            latest_volume=300.0,
        ),
        break_level=101.7,
    )

    assert result["body_quality_ok"] is True
    assert result["break_distance_ok"] is True
    assert result["relative_volume_ok"] is True
    assert result["market_action_count"] == 3
    assert result["market_action_tier"] == "STRONG"
    assert result["market_action_passed"] is True
    assert result["passed"] is True


def test_moderate_tier_remains_available_when_strong_is_not_met():
    result = _evaluate(
        _candles(
            open_price=100.0,
            high=101.5,
            low=99.5,
            close=101.3,
            latest_volume=100.0,
        ),
        break_level=101.2,
        candidate_score=90.0,
        health=90.0,
        ema10=True,
        ema30=True,
        reversal=True,
    )

    assert result["body_quality_ok"] is False
    assert result["break_distance_ok"] is True
    assert result["relative_volume_ok"] is False
    assert result["moderate_market_action_passed"] is True
    assert result["market_action_tier"] == "MODERATE"
    assert result["market_action_passed"] is True
    assert result["passed"] is True
