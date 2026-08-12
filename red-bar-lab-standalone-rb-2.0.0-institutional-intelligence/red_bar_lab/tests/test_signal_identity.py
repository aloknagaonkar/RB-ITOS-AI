from datetime import datetime
from zoneinfo import ZoneInfo

from red_bar_lab.storage.database import deterministic_signal_id as db_id
from red_bar_lab.strategy.identity import canonical_signal_id
from red_bar_lab.strategy.models import (
    Direction,
    SignalAttempt,
    SignalState,
)
from red_bar_lab.strategy.trade_engine import deterministic_signal_id as trade_id


IST = ZoneInfo("Asia/Kolkata")


def attempt():
    return SignalAttempt(
        state=SignalState.ACTIVE,
        direction=Direction.BEARISH,
        level_type="NEXT_RED_CANDLE",
        level_value=100,
        cross_timestamp=datetime(2026,8,7,10,5,tzinfo=IST),
        confirmation_timestamp=datetime(2026,8,7,10,15,tzinfo=IST),
        underlying_entry=99,
        cross_high=101,
        cross_low=98,
    )


def test_database_and_trade_engine_use_same_signal_id():
    item = attempt()
    expected = canonical_signal_id(
        "NIFTY",
        "2026-08-07",
        item.level_type,
        item.direction.value,
        item.cross_timestamp.isoformat(),
        item.confirmation_timestamp.isoformat(),
    )
    assert db_id(
        "NIFTY",
        "2026-08-07",
        item.level_type,
        item.direction.value,
        item.cross_timestamp.isoformat(),
        item.confirmation_timestamp.isoformat(),
    ) == expected
    assert trade_id(
        "NIFTY",
        "2026-08-07",
        item,
    ) == expected
