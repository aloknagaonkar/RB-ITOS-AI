from datetime import date, datetime, timezone

import pandas as pd

from red_bar_lab.services.red_bar_v2_canonical.zerodha_paper_market_data import (
    ZerodhaPaperCanaryMarketData,
)


NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


class _Client:
    def nfo_options(self, *, underlying_name, as_of):
        return pd.DataFrame([
            {
                "instrument_type": "CE",
                "instrument_token": 123,
                "tradingsymbol": "NIFTY26AUG25000CE",
                "exchange": "NFO",
                "expiry": date(2026, 8, 27),
                "strike": 25000.0,
                "lot_size": 75,
            }
        ])

    def quote(self, keys):
        return {
            "NFO:NIFTY26AUG25000CE": {
                "instrument_token": 123,
                "last_price": 100.0,
                "timestamp": NOW.isoformat(),
                "depth": {
                    "buy": [{"price": 99.0}],
                    "sell": [{"price": 101.0}],
                },
            }
        }


def test_zerodha_identity_and_quote_normalization_are_preserved():
    provider = ZerodhaPaperCanaryMarketData(_Client(), maximum_quote_age_seconds=120)
    instruments = provider.option_instruments(underlying="NIFTY 50", evaluated_at=NOW)
    assert instruments[0].instrument_key == "NFO|123"
    assert instruments[0].instrument_token == 123
    quotes = provider.quotes(instrument_keys=("NFO|123",), evaluated_at=NOW)
    assert quotes[0].last_price == 100.0
    assert quotes[0].bid_price == 99.0
    assert quotes[0].ask_price == 101.0
    assert quotes[0].quote_timestamp == NOW
