import math

from red_bar_lab.execution.market_data_values import (
    MarketDataQuality,
    normalize_market_number,
)


def test_genuine_zero_remains_available():
    result = normalize_market_number(0)

    assert result.value == 0.0
    assert result.available is True
    assert result.quality is MarketDataQuality.AVAILABLE
    assert result.score_input() == 0.0


def test_none_remains_missing_instead_of_becoming_zero():
    result = normalize_market_number(None)

    assert result.value is None
    assert result.available is False
    assert result.quality is MarketDataQuality.MISSING
    assert result.score_input() == 0.0


def test_nan_and_infinity_are_invalid_not_zero():
    for raw_value in (math.nan, math.inf, -math.inf):
        result = normalize_market_number(raw_value)

        assert result.value is None
        assert result.available is False
        assert result.quality is MarketDataQuality.INVALID


def test_non_numeric_text_is_invalid_and_preserves_raw_value():
    result = normalize_market_number("not-available")

    assert result.value is None
    assert result.quality is MarketDataQuality.INVALID
    assert result.raw_value == "not-available"


def test_numeric_text_is_available():
    result = normalize_market_number("125.75")

    assert result.value == 125.75
    assert result.quality is MarketDataQuality.AVAILABLE


def test_compatibility_score_fallback_does_not_change_stored_value():
    result = normalize_market_number(None)

    assert result.score_input(unavailable=-1.0) == -1.0
    assert result.value is None
    assert result.quality is MarketDataQuality.MISSING
