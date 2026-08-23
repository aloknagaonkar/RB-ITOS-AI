from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from red_bar_lab.domain.red_bar_v2 import OptionSide
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data import (
    PaperMarketDataCorruptionError,
    PaperMarketQuote,
    PaperOptionInstrument,
    verify_quote_freshness,
)


NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


def _quote(**changes):
    values = {
        "instrument_key": "NFO|123",
        "instrument_token": 123,
        "last_price": 100.0,
        "bid_price": 99.0,
        "ask_price": 101.0,
        "quote_timestamp": NOW,
        "provider": "ZERODHA",
    }
    values.update(changes)
    return PaperMarketQuote(**values)


def test_quote_contract_is_strict_finite_and_immutable():
    quote = _quote()
    with pytest.raises(FrozenInstanceError):
        quote.last_price = 101.0
    with pytest.raises(ValueError):
        _quote(last_price=True)
    with pytest.raises(ValueError):
        _quote(bid_price=102.0, ask_price=101.0)
    with pytest.raises(ValueError):
        _quote(quote_timestamp=datetime(2026, 8, 23))
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            _quote(last_price=value)
        with pytest.raises(ValueError):
            _quote(bid_price=value)
        with pytest.raises(ValueError):
            _quote(ask_price=value)


def test_option_instrument_contract_rejects_non_finite_strike():
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
    for value in (0.0, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            PaperOptionInstrument(
                "K", 1, "S", "U", date(2026, 8, 27), value,
                OptionSide.CE, 1, "X",
            )


def test_quote_freshness_rejects_non_finite_policy_values():
    quote = _quote()
    for value in (float("nan"), float("inf"), float("-inf"), 0.0):
        with pytest.raises(ValueError):
            verify_quote_freshness(
                quote,
                evaluated_at=NOW,
                maximum_age_seconds=value,
            )
    for value in (float("nan"), float("inf"), float("-inf"), -1.0):
        with pytest.raises(ValueError):
            verify_quote_freshness(
                quote,
                evaluated_at=NOW,
                maximum_age_seconds=120.0,
                future_tolerance_seconds=value,
            )


def test_future_quote_beyond_tolerance_is_corruption():
    future = _quote(
        quote_timestamp=datetime(2026, 8, 23, 9, 0, 3, tzinfo=timezone.utc)
    )
    with pytest.raises(PaperMarketDataCorruptionError):
        verify_quote_freshness(
            future,
            evaluated_at=NOW,
            maximum_age_seconds=120.0,
            future_tolerance_seconds=2.0,
        )
