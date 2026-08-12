from datetime import date

import pandas as pd

from red_bar_lab.brokers.zerodha_client import ZerodhaKiteClient
from red_bar_lab.config import RedBarSettings
from red_bar_lab.execution.paper_engine import (
    PaperContract,
    RedBarPaperExecutionEngine,
)
from red_bar_lab.storage.database import RedBarDatabase


class FakeZerodha:
    def __init__(self):
        self.price = 100.0

    def nfo_options(self, underlying_name, as_of=None):
        return pd.DataFrame(
            [
                {
                    "instrument_token": 1,
                    "tradingsymbol": "NIFTY26AUG25000CE",
                    "name": "NIFTY",
                    "expiry": date(2026, 8, 13),
                    "strike": 25000.0,
                    "lot_size": 75,
                    "instrument_type": "CE",
                    "exchange": "NFO",
                },
                {
                    "instrument_token": 2,
                    "tradingsymbol": "NIFTY26AUG25100CE",
                    "name": "NIFTY",
                    "expiry": date(2026, 8, 13),
                    "strike": 25100.0,
                    "lot_size": 75,
                    "instrument_type": "CE",
                    "exchange": "NFO",
                },
                {
                    "instrument_token": 3,
                    "tradingsymbol": "NIFTY26AUG25000PE",
                    "name": "NIFTY",
                    "expiry": date(2026, 8, 13),
                    "strike": 25000.0,
                    "lot_size": 75,
                    "instrument_type": "PE",
                    "exchange": "NFO",
                },
            ]
        )

    def quote(self, instruments):
        return {
            key: {
                "last_price": self.price,
                "volume": 10000,
                "oi": 5000,
                "depth": {
                    "buy": [{"price": self.price - 0.5}],
                    "sell": [{"price": self.price + 0.5}],
                },
            }
            for key in instruments
        }

    def historical_candles(
        self,
        instrument_token,
        interval,
        date_from,
        date_to,
        include_oi=True,
    ):
        ts = pd.date_range(
            "2026-08-10 09:15",
            periods=30,
            freq="1min",
            tz="Asia/Kolkata",
        )
        return pd.DataFrame(
            {
                "timestamp": ts,
                "open": range(100, 130),
                "high": range(101, 131),
                "low": range(99, 129),
                "close": range(100, 130),
                "volume": [1000] * 30,
                "oi": [5000] * 30,
            }
        )


def _engine(tmp_path):
    settings = RedBarSettings(
        artifacts_root=tmp_path / "artifacts"
    )
    db = RedBarDatabase(settings.database_path)
    db.initialize()
    return (
        RedBarPaperExecutionEngine(
            db,
            settings,
            initial_capital=100000.0,
        ),
        db,
    )


def test_zerodha_client_has_no_live_order_api():
    assert not hasattr(ZerodhaKiteClient, "place_order")
    assert not hasattr(ZerodhaKiteClient, "modify_order")
    assert not hasattr(ZerodhaKiteClient, "cancel_order")


def test_candidate_contracts_follow_direction(tmp_path):
    engine, _ = _engine(tmp_path)
    fake = FakeZerodha()

    bullish = engine.candidate_contracts(
        zerodha=fake,
        underlying_name="NIFTY 50",
        direction="BULLISH",
        spot_price=25020.0,
    )
    bearish = engine.candidate_contracts(
        zerodha=fake,
        underlying_name="NIFTY 50",
        direction="BEARISH",
        spot_price=25020.0,
    )

    assert bullish
    assert all(item.option_type == "CE" for item in bullish)
    assert bearish
    assert all(item.option_type == "PE" for item in bearish)


def test_paper_order_lifecycle_uses_virtual_fills(tmp_path):
    engine, db = _engine(tmp_path)
    fake = FakeZerodha()
    contract = PaperContract(
        instrument_token=1,
        tradingsymbol="NIFTY26AUG25000CE",
        exchange="NFO",
        option_type="CE",
        strike=25000.0,
        expiry=date(2026, 8, 13),
        lot_size=75,
    )

    opened = engine.open_long_option(
        zerodha=fake,
        contract=contract,
        quantity=75,
        signal_id="SIG-1",
        underlying_name="NIFTY 50",
        underlying_price=25020.0,
    )
    assert opened["status"] == "OPEN"
    assert opened["entry_price"] == 100.5

    fake.price = 110.0
    refreshed = engine.refresh_open_positions(zerodha=fake)
    assert len(refreshed) == 1
    assert refreshed[0]["current_price"] == 110.0
    assert refreshed[0]["unrealized_pnl"] > 0

    closed = engine.close_position(
        zerodha=fake,
        order_id=opened["order_id"],
    )
    assert closed["status"] == "CLOSED"
    assert closed["exit_price"] == 109.5
    assert closed["realized_pnl"] > 0

    marks = db.read_paper_execution_marks(opened["order_id"])
    assert [row["event_type"] for row in marks] == [
        "ENTRY", "MARK", "EXIT"
    ]


def test_option_candles_add_ema_and_vwap(tmp_path):
    engine, _ = _engine(tmp_path)
    frame = engine.option_candles(
        zerodha=FakeZerodha(),
        instrument_token=1,
        date_from="2026-08-10",
        date_to="2026-08-10",
    )
    assert not frame.empty
    assert "ema9" in frame.columns
    assert "ema21" in frame.columns
    assert "vwap" in frame.columns
