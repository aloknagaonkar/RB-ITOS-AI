from datetime import datetime
from zoneinfo import ZoneInfo

from market_lab.historical_option_ohlc_adapter_v1 import OptionMinuteCandle
from market_lab.historical_option_paper_replay_v1 import HistoricalPaperPosition
from market_lab.historical_option_intrabar_replay_v1 import replay_intrabar_trade

IST = ZoneInfo("Asia/Kolkata")


def candle(minute, o, h, l, c):
    return OptionMinuteCandle(
        session_date="2026-08-25",
        expiry="2026-08-25",
        underlying="NSE_INDEX|Nifty 50",
        instrument_key="CE",
        strike=24150.0,
        side="CE",
        timestamp=datetime(2026, 8, 25, 10, minute, tzinfo=IST),
        open=o, high=h, low=l, close=c,
        volume=100, open_interest=1000,
        provenance="TEST",
    )


def position():
    return HistoricalPaperPosition(
        position_id="p1",
        session_date="2026-08-25",
        direction="BULLISH",
        option_type="CE",
        strike=24150.0,
        instrument_key="CE",
        opened_at="2026-08-25T10:10:00+05:30",
        entry_price=100.0,
    )


def test_intrabar_hard_stop_fills_at_stop():
    p = position()
    trade, events = replay_intrabar_trade(
        p,
        [candle(11, 100, 101, 94, 96)],
    )
    assert trade.exit_reason == "HARD_STOP"
    assert trade.exit_price == 95.0


def test_gap_through_active_stop_fills_at_open():
    p = position()
    trade, events = replay_intrabar_trade(
        p,
        [candle(11, 93, 96, 92, 95)],
    )
    assert trade.exit_reason == "HARD_STOP"
    assert trade.exit_price == 93.0


def test_new_breakeven_stop_activates_next_bar_not_same_bar():
    p = position()
    trade, events = replay_intrabar_trade(
        p,
        [
            # High reaches +6%, but low is below entry. New BE must NOT stop
            # inside this same candle.
            candle(11, 101, 106, 98, 104),
            # Pending BE becomes active here and low touches it.
            candle(12, 104, 105, 99, 100),
        ],
    )
    assert trade.exit_reason == "BREAKEVEN_STOP"
    assert trade.exit_price == 100.0
    assert trade.exit_time.endswith("10:12:00+05:30")


def test_trailing_stop_staged_then_active_next_bar():
    p = position()
    trade, events = replay_intrabar_trade(
        p,
        [
            candle(11, 102, 112, 101, 110),
            # stop from 112 high = 108.64 becomes active at start of this bar.
            candle(12, 110, 111, 108, 109),
        ],
    )
    assert trade.exit_reason == "TRAIL_STOP"
    assert round(trade.exit_price, 2) == 108.64
