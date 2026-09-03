from datetime import datetime

import pandas as pd
import pytest

from red_bar_lab.intelligence.market_context import (
    MarketIndicatorSnapshot,
    rsi_alignment_state,
)
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
    rsi: float | None,
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
        rsi_state=rsi_alignment_state(rsi),
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


def test_a_first_entry_inside_the_reference_candle_is_provisional():
    """Past the 100.0 midpoint, short of the 104.0 high: admitted, not confirmed.

    This path used to hardcode CONFIRMED for every admitted first entry, so the
    grade said nothing and a setup worth about +0.25R was reported as one worth
    +1R.
    """
    decision = evaluate_initial_direction(
        _reference(),
        _context(timeframe="1M", close=102.0, rsi=62.0, vwap=101.0),
    )
    assert decision.event_type == RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT
    assert decision.state == RedBarV2State.PROVISIONAL_BULLISH
    assert decision.trend_strength == "PROVISIONAL"
    assert decision.option_side == "CE"


@pytest.mark.parametrize(
    ("rsi", "aligned"),
    [
        # Flat, so the reading claims nothing either way.
        (50.0, False),
        # Decisively bearish while the price gates are bullish. It is reported as
        # a reading that means something and it still gets no vote.
        (38.0, True),
        # The Wilder RSI(14) warm-up, which used to discard the whole context and
        # leave this path blind for the first 15 candles of the session.
        (None, False),
    ],
)
def test_rsi_never_gates_a_first_entry(rsi, aligned):
    decision = evaluate_initial_direction(
        _reference(),
        _context(timeframe="1M", close=105.0, rsi=rsi, vwap=102.0),
    )
    assert decision.event_type == RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT
    assert decision.direction == "BULLISH"
    assert decision.trend_strength == "CONFIRMED"
    assert decision.rsi_aligned is aligned


@pytest.mark.parametrize(
    ("rsi", "aligned"), [(50.0, False), (62.0, True), (None, False)]
)
def test_rsi_never_gates_a_reversal(rsi, aligned):
    decision = evaluate_reversal_direction(
        _reference(),
        _context(timeframe="5M", close=95.0, rsi=rsi, vwap=97.0),
        previous_direction="BULLISH",
    )
    assert decision.event_type == RedBarV2EventType.BEARISH_REVERSAL_DETECTED
    assert decision.direction == "BEARISH"
    assert decision.rsi_aligned is aligned


def test_a_reversal_short_of_the_midpoint_is_no_alignment_at_all():
    """The midpoint is a gate on the reversal path too, not a grade.

    A bullish RSI and a close above VWAP used to be enough to admit a reversal and
    call it PROVISIONAL, which let a bullish entry be taken with the index close
    below the level the strategy is named for.
    """
    decision = evaluate_reversal_direction(
        _reference(midpoint=110.0),
        _context(timeframe="5M", close=105.0, rsi=61.0, vwap=102.0),
        previous_direction="BEARISH",
    )
    assert decision.event_type == RedBarV2EventType.NO_DIRECTIONAL_ALIGNMENT
    assert decision.state == RedBarV2State.NEUTRAL
    assert decision.direction is None
    assert decision.option_side is None


def test_bullish_reversal_is_provisional_inside_the_reference_candle():
    """Past the 100.0 midpoint, short of the 104.0 reference high.

    Admitted, because the gate is the midpoint; PROVISIONAL, because the grade is
    the reference candle's own high and this close has not taken it out.
    """
    decision = evaluate_reversal_direction(
        _reference(midpoint=100.0),
        _context(timeframe="5M", close=102.0, rsi=61.0, vwap=101.0),
        previous_direction="BEARISH",
    )
    assert decision.event_type == RedBarV2EventType.BULLISH_REVERSAL_DETECTED
    assert decision.state == RedBarV2State.PROVISIONAL_BULLISH
    assert decision.option_side == "CE"
    assert decision.midpoint_aligned is True


def test_bearish_reversal_is_confirmed_when_it_takes_out_the_reference_low():
    """Below the 100.0 midpoint to clear the gate, below the 96.0 low to be graded."""
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
