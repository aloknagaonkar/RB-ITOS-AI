from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from red_bar_lab.domain.red_bar_v2 import OptionSide
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data import (
    PaperMarketQuote,
    PaperOptionInstrument,
)


NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


def test_quote_contract_is_strict_and_immutable():
    quote = PaperMarketQuote(
        instrument_key="NFO|123",
        instrument_token=123,
        last_price=100.0,
        bid_price=99.0,
        ask_price=101.0,
        quote_timestamp=NOW,
        provider="ZERODHA",
    )
    with pytest.raises(FrozenInstanceError):
        quote.last_price = 101.0
    with pytest.raises(ValueError):
        PaperMarketQuote("NFO|1", 1, True, None, None, NOW, "X")
    with pytest.raises(ValueError):
        PaperMarketQuote("NFO|1", 1, 100.0, 102.0, 101.0, NOW, "X")
    with pytest.raises(ValueError):
        PaperMarketQuote("NFO|1", 1, 100.0, None, None, datetime(2026, 8, 23), "X")


def test_option_instrument_contract_is_strict_and_unique_by_key():
    item = PaperOptionInstrument(
        instrument_key="NSE_FO|456",
        instrument_token=456,
        trading_symbol="NIFTY26AUG25000CE",
        underlying="NIFTY 50",
        expiry=date(2026, 8, 27),
        strike=25000.0,
        option_side=OptionSide.CE,
        lot_size=75,
        provider="UPSTOX",
    )
    assert item.instrument_key == "NSE_FO|456"
    with pytest.raises(ValueError):
        PaperOptionInstrument("K", 1, "S", "U", date(2026, 8, 27), 1.0, "CE", 1, "X")
    with pytest.raises(ValueError):
        PaperOptionInstrument("K", 1, "S", "U", date(2026, 8, 27), 0.0, OptionSide.CE, 1, "X")
