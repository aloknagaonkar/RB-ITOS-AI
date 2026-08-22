from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from red_bar_lab.config import RedBarSettings
from red_bar_lab.execution.signal_execution_limits import (
    evaluate_signal_execution_limits,
)
from red_bar_lab.storage import RedBarDatabase
from red_bar_lab.strategy.models import Direction, SignalAttempt, SignalState


IST = ZoneInfo("Asia/Kolkata")


def _attempt(stamp: datetime) -> SignalAttempt:
    return SignalAttempt(
        state=SignalState.ACTIVE,
        direction=Direction.BULLISH,
        level_type="NEXT_RED_CANDLE",
        level_value=24631.6,
        cross_timestamp=stamp,
        confirmation_timestamp=stamp,
        underlying_entry=24647.95,
    )


def _order(signal_id: str, token: int, timestamp: datetime) -> dict[str, object]:
    return {
        "order_id": f"ORDER-{token}",
        "account_id": "PAPER-STD",
        "signal_id": signal_id,
        "market_data_provider": "TEST",
        "execution_provider": "TEST",
        "execution_mode": "PAPER",
        "underlying_name": "NIFTY 50",
        "instrument_token": token,
        "exchange": "NFO",
        "tradingsymbol": f"NIFTY-{token}",
        "option_type": "CE",
        "strike": 24600.0,
        "expiry": "2026-08-27",
        "lot_size": 75,
        "side": "BUY",
        "quantity": 75,
        "entry_timestamp": timestamp.isoformat(),
        "entry_price": 100.0,
        "current_price": 100.0,
        "status": "OPEN",
    }


def test_signal_age_gate_fails_closed(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    database = RedBarDatabase(settings.database_path)
    confirmation = datetime.now(IST) - timedelta(minutes=10)
    database.replace_signal_attempts(
        "LIVE_MONITOR", "NIFTY", confirmation.date().isoformat(), [_attempt(confirmation)]
    )
    signal_id = database.read_signal_attempts("NIFTY", confirmation.date().isoformat())[0][
        "signal_id"
    ]

    decision = evaluate_signal_execution_limits(
        settings.database_path,
        account_id="PAPER-STD",
        signal_id=str(signal_id),
        instrument_token=101,
        now=datetime.now(IST),
        max_signal_age_seconds=180,
    )

    assert decision.allowed is False
    assert decision.reason == "MAX_SIGNAL_AGE_EXCEEDED"


def test_persistence_boundary_caps_entries_and_contracts(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    database = RedBarDatabase(settings.database_path)
    confirmation = datetime.now(IST) - timedelta(seconds=30)
    database.replace_signal_attempts(
        "LIVE_MONITOR", "NIFTY", confirmation.date().isoformat(), [_attempt(confirmation)]
    )
    signal_id = str(
        database.read_signal_attempts("NIFTY", confirmation.date().isoformat())[0][
            "signal_id"
        ]
    )

    first = _order(signal_id, 101, datetime.now(IST) - timedelta(minutes=10))
    first["reentry_cooldown_seconds"] = 0
    database.insert_paper_execution_order(first)

    second = _order(signal_id, 102, datetime.now(IST) - timedelta(minutes=5))
    second["order_id"] = "ORDER-102"
    second["reentry_cooldown_seconds"] = 0
    database.insert_paper_execution_order(second)

    third = _order(signal_id, 103, datetime.now(IST))
    third["order_id"] = "ORDER-103"
    third["reentry_cooldown_seconds"] = 0
    with pytest.raises(ValueError, match="MAX_ENTRIES_PER_SIGNAL_REACHED"):
        database.insert_paper_execution_order(third)


def test_reentry_cooldown_blocks_second_contract(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    database = RedBarDatabase(settings.database_path)
    confirmation = datetime.now(IST) - timedelta(seconds=30)
    database.replace_signal_attempts(
        "LIVE_MONITOR", "NIFTY", confirmation.date().isoformat(), [_attempt(confirmation)]
    )
    signal_id = str(
        database.read_signal_attempts("NIFTY", confirmation.date().isoformat())[0][
            "signal_id"
        ]
    )

    first = _order(signal_id, 201, datetime.now(IST))
    database.insert_paper_execution_order(first)

    second = _order(signal_id, 202, datetime.now(IST))
    second["order_id"] = "ORDER-202"
    with pytest.raises(ValueError, match="SIGNAL_REENTRY_COOLDOWN_ACTIVE"):
        database.insert_paper_execution_order(second)
