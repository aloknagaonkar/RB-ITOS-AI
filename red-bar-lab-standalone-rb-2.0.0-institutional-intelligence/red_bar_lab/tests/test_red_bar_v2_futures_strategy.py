import pandas as pd

from red_bar_lab.intelligence.market_context import rsi_alignment_state
from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    RedBarV2FuturesSnapshot,
)
from red_bar_lab.strategy.red_bar_v2 import RedBarV2EventType, RedBarV2Reference
from red_bar_lab.strategy.red_bar_v2_futures import (
    evaluate_initial_direction_futures,
)


IST = "Asia/Kolkata"


def _reference():
    stamp = pd.Timestamp("2026-08-18 09:20", tz=IST).to_pydatetime()
    return RedBarV2Reference(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-18",
        reference_timestamp=stamp,
        reference_open=101.0,
        reference_high=105.0,
        reference_low=95.0,
        reference_close=99.0,
        midpoint=100.0,
    )


def _snapshot(*, index_close, futures_close, vwap, rsi):
    stamp = pd.Timestamp("2026-08-18 09:30", tz=IST).to_pydatetime()
    return RedBarV2FuturesSnapshot(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-18",
        timeframe="1M",
        candle_timestamp=stamp,
        candle_open=index_close,
        candle_high=index_close + 1.0,
        candle_low=index_close - 1.0,
        candle_close=index_close,
        candle_volume=0.0,
        rsi_period=14,
        rsi_value=rsi,
        vwap_value=vwap,
        price_vs_vwap="ABOVE" if futures_close > vwap else "BELOW",
        rsi_state=rsi_alignment_state(rsi),
        source="TEST",
        data_quality="VALID",
        fresh=True,
        vwap_comparison_price=futures_close,
        vwap_source_instrument_key="NSE_FO|58072",
        vwap_source_timestamp=stamp,
        vwap_source_volume=1000.0,
    )


def test_bullish_requires_index_midpoint_and_futures_vwap_alignment():
    decision = evaluate_initial_direction_futures(
        _reference(),
        _snapshot(index_close=101.0, futures_close=201.0, vwap=200.0, rsi=60.0),
    )
    assert decision.event_type == RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT
    assert decision.option_side == "CE"


def test_futures_below_vwap_blocks_bullish_even_when_index_is_above_midpoint():
    decision = evaluate_initial_direction_futures(
        _reference(),
        _snapshot(index_close=101.0, futures_close=199.0, vwap=200.0, rsi=60.0),
    )
    assert decision.event_type == RedBarV2EventType.NO_DIRECTIONAL_ALIGNMENT
    assert decision.direction is None
