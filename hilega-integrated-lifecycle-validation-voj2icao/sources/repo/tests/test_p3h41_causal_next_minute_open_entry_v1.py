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


def signal_position():
    return HistoricalPaperPosition(
        position_id="p1",
        session_date="2026-08-25",
        direction="BULLISH",
        option_type="CE",
        strike=24150.0,
        instrument_key="CE",
        opened_at="2026-08-25T10:10:00+05:30",
        entry_price=999.0,  # must be ignored in P3H.4.1
    )


def test_entry_uses_next_minute_open_not_checkpoint_close():
    p = signal_position()
    trade, events = replay_intrabar_trade(
        p,
        [candle(11, 100, 102, 99, 101)],
    )
    assert trade.entry_time.endswith("10:11:00+05:30")
    assert trade.entry_price == 100.0


def test_initial_hard_stop_can_trigger_inside_entry_minute():
    p = signal_position()
    trade, events = replay_intrabar_trade(
        p,
        [candle(11, 100, 106, 94, 105)],
    )
    assert trade.exit_reason == "HARD_STOP"
    assert trade.exit_price == 95.0


def test_breakeven_stop_raised_from_entry_bar_only_active_next_bar():
    p = signal_position()
    trade, events = replay_intrabar_trade(
        p,
        [
            # hard stop not touched; high arms BE, but low below entry must not
            # trigger the newly raised BE inside the same minute.
            candle(11, 100, 106, 96, 104),
            candle(12, 104, 105, 99, 100),
        ],
    )
    assert trade.exit_reason == "BREAKEVEN_STOP"
    assert trade.exit_price == 100.0
    assert trade.exit_time.endswith("10:12:00+05:30")


def test_gap_through_next_bar_trailing_stop_fills_at_open():
    p = signal_position()
    trade, events = replay_intrabar_trade(
        p,
        [
            candle(11, 100, 112, 99, 110),
            # trailing stop from prior bar = 108.64; next bar opens below it.
            candle(12, 107, 110, 106, 109),
        ],
    )
    assert trade.exit_reason == "TRAIL_STOP"
    assert trade.exit_price == 107.0
