from datetime import datetime, timezone

import pytest

from red_bar_lab.services.red_bar_v2_canonical.paper_market_data import (
    PaperMarketDataCorruptionError,
)
from red_bar_lab.services.red_bar_v2_canonical.upstox_paper_market_data import (
    UpstoxPaperCanaryMarketData,
)


NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


class _Response:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *args, **kwargs):
        return _Response(self.payload)


class _Client:
    BASE_URL_V2 = "https://example/v2"
    timeout = 1

    def __init__(self, payload):
        self.session = _Session(payload)

    def _headers(self):
        return {"Authorization": "Bearer hidden"}

    def _raise_for_api_error(self, response):
        return None

    def get_option_contracts(self, underlying_key):
        return [
            {
                "instrument_key": "NSE_FO|987654",
                "trading_symbol": "NIFTY26AUG25000CE",
                "instrument_type": "CE",
                "expiry": "2026-08-27",
                "strike_price": 25000.0,
                "lot_size": 75,
            },
            {
                "instrument_key": "NSE_FO|987655",
                "trading_symbol": "NIFTY26AUG25000PE",
                "instrument_type": "PE",
                "expiry": "2026-08-27",
                "strike_price": 25000.0,
                "lot_size": 75,
            },
        ]


def _provider(payload):
    return UpstoxPaperCanaryMarketData(
        _Client(payload),
        underlying_keys={"NIFTY 50": "NSE_INDEX|Nifty 50"},
        maximum_quote_age_seconds=120,
    )


def test_upstox_contract_and_quote_normalization():
    provider = _provider({
        "data": {
            "NSE_FO|987654": {
                "instrument_token": "987654",
                "last_price": 110.0,
                "bid_price": 109.0,
                "ask_price": 111.0,
                "timestamp": NOW.isoformat(),
            }
        }
    })
    instruments = provider.option_instruments(underlying="NIFTY 50", evaluated_at=NOW)
    assert [item.option_side.value for item in instruments] == ["CE", "PE"]
    assert instruments[0].instrument_key == "NSE_FO|987654"
    assert instruments[0].instrument_token == 987654
    quotes = provider.quotes(instrument_keys=("NSE_FO|987654",), evaluated_at=NOW)
    assert quotes[0].last_price == 110.0
    assert quotes[0].quote_timestamp == NOW


def test_upstox_missing_timestamp_is_corruption():
    provider = _provider({"data": {"NSE_FO|987654": {"last_price": 110.0}}})
    with pytest.raises(PaperMarketDataCorruptionError):
        provider.quotes(instrument_keys=("NSE_FO|987654",), evaluated_at=NOW)
