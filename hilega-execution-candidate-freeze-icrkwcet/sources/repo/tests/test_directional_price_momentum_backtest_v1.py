from market_lab.directional_price_momentum_backtest_v1 import (
    pct_return,
    profit_factor,
    target_stop_classification,
)


def candle(high, low, close=None):
    return {
        "high": float(high),
        "low": float(low),
        "close": float(close if close is not None else (high + low) / 2),
    }


def test_pct_return():
    assert pct_return(100.0, 105.0) == 5.000000000000004


def test_target_first():
    result = target_stop_classification(
        entry=100.0,
        candles=[
            candle(103, 98),
            candle(106, 97),
        ],
        target_pct=5,
        stop_pct=10,
    )
    assert result == "TARGET_FIRST"


def test_stop_first():
    result = target_stop_classification(
        entry=100.0,
        candles=[
            candle(103, 96),
            candle(104, 89),
            candle(106, 88),
        ],
        target_pct=5,
        stop_pct=10,
    )
    assert result == "STOP_FIRST"


def test_ambiguous_same_bar():
    result = target_stop_classification(
        entry=100.0,
        candles=[candle(106, 89)],
        target_pct=5,
        stop_pct=10,
    )
    assert result == "AMBIGUOUS_SAME_BAR"


def test_neither():
    result = target_stop_classification(
        entry=100.0,
        candles=[candle(104, 91) for _ in range(15)],
        target_pct=5,
        stop_pct=10,
    )
    assert result == "NEITHER_WITHIN_15M"


def test_profit_factor():
    assert profit_factor([2.0, 1.0, -1.0]) == 3.0
    assert profit_factor([1.0, 2.0]) is None
