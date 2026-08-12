from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.strategy.models import (
    Direction,
    SignalAttempt,
    SignalState,
)
from red_bar_lab.strategy.trade_engine import evaluate_active_signals
from red_bar_lab.strategy.trade_models import (
    ExitReason,
    TradeStatus,
)


IST = ZoneInfo("Asia/Kolkata")


def attempt():
    return SignalAttempt(
        state=SignalState.ACTIVE,
        direction=Direction.BULLISH,
        level_type="FIRST_CANDLE",
        level_value=100,
        cross_timestamp=datetime(2026,8,7,9,20,tzinfo=IST),
        confirmation_timestamp=datetime(2026,8,7,9,26,tzinfo=IST),
        underlying_entry=103,
        cross_high=102,
        cross_low=98,
    )


def frame():
    return pd.DataFrame([
        {
            "timestamp": pd.Timestamp(
                "2026-08-07 09:27",
                tz=IST,
            ),
            "open": 103,
            "high": 110,
            "low": 102,
            "close": 108,
            "volume": 0,
        },
        {
            "timestamp": pd.Timestamp(
                "2026-08-07 10:00",
                tz=IST,
            ),
            "open": 108,
            "high": 112,
            "low": 106,
            "close": 110,
            "volume": 0,
        },
    ])


def test_unresolved_live_models_remain_open():
    results = evaluate_active_signals(
        frame(),
        [attempt()],
        instrument_key="NIFTY",
        trading_date="2026-08-07",
        session_complete=False,
    )
    eod = next(
        r for r in results if r.exit_model.value == "EOD_HOLD"
    )
    fixed_50 = next(
        r
        for r in results
        if r.exit_model.value == "FIXED_TARGET"
        and r.model_parameter == "50pt"
    )
    assert eod.status is TradeStatus.OPEN
    assert eod.exit_reason is ExitReason.OPEN
    assert fixed_50.status is TradeStatus.OPEN
    assert fixed_50.exit_reason is ExitReason.OPEN


def test_historical_mode_still_finalizes_at_eod():
    results = evaluate_active_signals(
        frame(),
        [attempt()],
        instrument_key="NIFTY",
        trading_date="2026-08-07",
        session_complete=True,
    )
    eod = next(
        r for r in results if r.exit_model.value == "EOD_HOLD"
    )
    assert eod.status is TradeStatus.CLOSED
    assert eod.exit_reason is ExitReason.EOD
