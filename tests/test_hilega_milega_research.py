from datetime import datetime, timedelta

import pytest

from market_lab.hilega_milega_research import IST, indicators, metrics, signals, simulate


def test_indicator_warmup_and_weighting():
    values = indicators(list(range(1, 50)))
    assert values[8] is None
    assert values[9] == (100, 100, None)
    assert values[29] == (100, 100, 100)
    down = indicators(list(range(50, 1, -1)))
    assert down[29] == (0, 0, 0)
    reversal = indicators(list(range(1, 11)) + [9])
    assert reversal[-1][0] == pytest.approx(100 * 8 / 9)


def test_filter_blocks_entry_but_not_opposite_exit():
    assert signals((45, 44, 45), (48, 47, 46), "ema_wma_rsi50") == (1, 0)
    assert signals((49, 44, 45), (51, 47, 46), "ema_wma_rsi50") == (1, 1)
    assert signals((49, 48, 45), (51, 49, 46), "rsi50") == (1, 1)


def test_signal_fills_next_open_and_square_off():
    start = datetime(2026, 9, 17, 15, 0, tzinfo=IST)
    bars = [dict(timestamp=start + timedelta(minutes=5 * i), open=p)
            for i, p in enumerate([100, 101, 105, 103, 110])]
    values = [(48, 44, 45), (52, 47, 46), (53, 48, 46), (54, 49, 46), (55, 50, 46)]
    trades = simulate(bars, values, "ema_wma", {start.date()})
    assert len(trades) == 1
    assert trades[0]["entry_price"] == 105
    assert trades[0]["exit_price"] == 110
    assert trades[0]["gross_points"] == 5


def test_costs_and_closed_trade_drawdown():
    result = metrics([{"gross_points": x} for x in [10, -5, 3]], 2)
    assert result["net_points"] == 2
    assert result["closed_trade_max_drawdown_points"] == 7
    assert result["profit_factor"] == pytest.approx(9 / 7, abs=0.001)


def test_short_reversal_uses_same_next_open():
    start = datetime(2026, 9, 17, 14, 55, tzinfo=IST)
    bars = [dict(timestamp=start + timedelta(minutes=5 * i), open=p)
            for i, p in enumerate([100, 101, 105, 103, 99, 95])]
    values = [(48, 44, 45), (52, 47, 46), (48, 44, 46),
              (47, 43, 46), (46, 42, 46), (45, 41, 46)]
    trades = simulate(bars, values, "ema_wma", {start.date()})
    assert [t["side"] for t in trades] == ["long", "short"]
    assert [t["gross_points"] for t in trades] == [-2, 8]
    assert trades[0]["exit"] == trades[1]["entry"]


def test_future_prices_do_not_change_past_indicators():
    closes = [100 + (i % 7) * 3 - (i % 5) for i in range(100)]
    assert indicators(closes) == indicators(closes + [500, 1, 800])[:100]
