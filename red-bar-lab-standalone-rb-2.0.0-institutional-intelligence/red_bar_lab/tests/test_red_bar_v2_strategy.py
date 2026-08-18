from datetime import datetime

import pandas as pd

from red_bar_lab.intelligence.market_context import MarketIndicatorSnapshot
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2EventType,
    RedBarV2Reference,
    RedBarV2State,
    build_red_bar_v2_reference,
    evaluate_initial_direction,
    evaluate_midpoint_upgrade,
    evaluate_reversal_direction,
)


IST = "Asia/Kolkata"


def _candles() -> pd.DataFrame:
    timestamps = pd.date_range("2026-08-21 09:15", periods=20, freq="1min", tz=IST)
    rows = []
    for index, timestamp in enumerate(timestamps):
        if index < 5:
            open_price = 100.0 + index
            close_price = open_price + 0.5
        elif index < 10:
            # Keep the 09:20-09:25 aggregate non-red so it is intentionally
            # skipped. The following completed 09:25-09:30 candle is the first
            # eligible red five-minute reference.
            open_price = 105.0 + (index - 5) * 0.2
            close_price = open_price + 0.1
        elif index < 15:
            open_price = 106.0 - (index - 10) * 0.5
            close_price = open_price - 0.4
        else:
            open_price = 103.0 + (index - 15) * 0.1
            close_price = open_price - 0.1
        rows.append(
            {
                "timestamp": timestamp,
                "open": open_price,
                "high": max(open_price, close_price) + 0.2,
                "low": min(open_price, close_price) - 0.2,
                "close": close_price,
                "volume": 1000.0,
            }
        )
    return pd.DataFrame(rows)


def _reference(midpoint: float = 100.0) -> RedBarV2Reference:
    return RedBarV2Reference(
        instrument_key="NIFTY",
        trading_date="2026-08-21",
        reference_timestamp=pd.Timestamp("2026-08-21 09:25", tz=IST).to_pydatetime(),
        reference_open=102.0,
        reference_high=104.0,
        reference_low=96.0,
        reference_close=98.0,
        midpoint=midpoint,
    )


def _context(
    *,
    timeframe: str,
    close: float,
    rsi: float,
    vwap: float,
    timestamp: str = "2026-08-21 10:00",
    data_quality: str = "VALID",
    fresh: bool = True,
) -> MarketIndicatorSnapshot:
    stamp = pd.Timestamp(timestamp, tz=IST).to_pydatetime()
    return MarketIndicatorSnapshot(
        instrument_key="NIFTY",
        trading_date="2026-08-21",
        timeframe=timeframe,
        candle_timestamp=stamp,
        candle_open=close - 0.5,
        candle_high=close + 0.5,
        candle_low=close - 1.0,
        candle_close=close,
        candle_volume=1000.0,
        rsi_period=14,
        rsi_value=rsi,
        vwap_value=vwap,
        price_vs_vwap="ABOVE" if close > vwap else "BELOW" if close < vwap else "AT",
        bullish_context=data_quality == "VALID" and fresh and rsi > 55 and close > vwap,
        bearish_context=data_quality == "VALID" and fresh and rsi < 45 and close < vwap,
        source="TEST",
        data_quality=data_quality,
        fresh=fresh,
    )


def test_reference_ignores_first_5m_candle_and_selects_first_later_red_candle():
    reference = build_red_bar_v2_reference(
        _candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:30", tz=IST),
    )

    assert reference is not None
    assert reference.reference_timestamp == pd.Timestamp("2026-08-21 09:25", tz=IST).to_pydatetime()
    assert reference.reference_close < reference.reference_open
    assert reference.midpoint == (reference.reference_high + reference.reference_low) / 2.0


def test_reference_is_unavailable_until_red_5m_candle_is_complete():
    reference = build_red_bar_v2_reference(
        _candles(),
        instrument_key="NIFTY",
        evaluation_time=pd.Timestamp("2026-08-21 09:29", tz=IST),
    )
    assert reference is None


def test_initial_bullish_alignment_creates_confirmed_ce_direction():
    decision = evaluate_initial_direction(
        _reference(),
        _context(timeframe="1M", close=105.0, rsi=62.0, vwap=102.0),
    )
    assert decision.event_type == RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT
    assert decision.state == RedBarV2State.CONFIRMED_BULLISH
    assert decision.option_side == "CE"
    assert decision.trend_strength == "CONFIRMED"


def test_initial_bearish_alignment_creates_confirmed_pe_direction():
    decision = evaluate_initial_direction(
        _reference(),
        _context(timeframe="1M", close=95.0, rsi=38.0, vwap=97.0),
    )
    assert decision.event_type == RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT
    assert decision.state == RedBarV2State.CONFIRMED_BEARISH
    assert decision.option_side == "PE"


def test_initial_direction_requires_midpoint_alignment():
    decision = evaluate_initial_direction(
        _reference(midpoint=110.0),
        _context(timeframe="1M", close=105.0, rsi=62.0, vwap=102.0),
    )
    assert decision.event_type == RedBarV2EventType.NO_DIRECTIONAL_ALIGNMENT
    assert decision.state == RedBarV2State.NEUTRAL


def test_bullish_reversal_can_be_provisional_before_midpoint():
    decision = evaluate_reversal_direction(
        _reference(midpoint=110.0),
        _context(timeframe="5M", close=105.0, rsi=61.0, vwap=102.0),
        previous_direction="BEARISH",
    )
    assert decision.event_type == RedBarV2EventType.BULLISH_REVERSAL_DETECTED
    assert decision.state == RedBarV2State.PROVISIONAL_BULLISH
    assert decision.option_side == "CE"
    assert decision.midpoint_aligned is False


def test_bearish_reversal_is_confirmed_when_midpoint_is_aligned():
    decision = evaluate_reversal_direction(
        _reference(midpoint=100.0),
        _context(timeframe="5M", close=95.0, rsi=39.0, vwap=97.0),
        previous_direction="BULLISH",
    )
    assert decision.event_type == RedBarV2EventType.BEARISH_REVERSAL_DETECTED
    assert decision.state == RedBarV2State.CONFIRMED_BEARISH
    assert decision.option_side == "PE"
    assert decision.midpoint_aligned is True


def test_midpoint_upgrade_confirms_provisional_state_without_new_entry_type():
    decision = evaluate_midpoint_upgrade(
        _reference(midpoint=100.0),
        _context(timeframe="1M", close=102.0, rsi=58.0, vwap=101.0),
        current_state=RedBarV2State.PROVISIONAL_BULLISH,
    )
    assert decision.event_type == RedBarV2EventType.FULL_DIRECTIONAL_ALIGNMENT
    assert decision.state == RedBarV2State.CONFIRMED_BULLISH
    assert decision.entry_type == "STATE_UPGRADE"


def test_stale_context_is_rejected():
    decision = evaluate_initial_direction(
        _reference(),
        _context(
            timeframe="1M",
            close=105.0,
            rsi=62.0,
            vwap=102.0,
            data_quality="STALE_CONTEXT",
            fresh=False,
        ),
    )
    assert decision.event_type == RedBarV2EventType.CONTEXT_INVALID
    assert decision.context_fresh is False
