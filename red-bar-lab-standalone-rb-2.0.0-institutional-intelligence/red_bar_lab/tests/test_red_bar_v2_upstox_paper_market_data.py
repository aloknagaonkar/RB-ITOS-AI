from datetime import datetime, timezone

import pytest

from red_bar_lab.services.red_bar_v2_canonical.paper_market_data import (
    PaperMarketDataCorruptionError,
    PaperMarketDataDiagnosticError,
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

    def __init__(self, payload, contracts=None):
        self.session = _Session(payload)
        self.contracts = contracts if contracts is not None else [
            {
                "instrument_key": "NSE_FO|987654",
                "instrument_token": "987654",
                "trading_symbol": "NIFTY26AUG25000CE",
                "instrument_type": "CE",
                "expiry": "2026-08-27",
                "strike_price": 25000.0,
                "lot_size": 75,
            },
            {
                "instrument_key": "NSE_FO|987655",
                "instrument_token": "987655",
                "trading_symbol": "NIFTY26AUG25000PE",
                "instrument_type": "PE",
                "expiry": "2026-08-27",
                "strike_price": 25000.0,
                "lot_size": 75,
            },
        ]

    def _headers(self):
        return {"Authorization": "Bearer hidden"}

    def _raise_for_api_error(self, response):
        return None

    def get_option_contracts(self, underlying_key):
        return self.contracts


def _provider(payload, contracts=None):
    return UpstoxPaperCanaryMarketData(
        _Client(payload, contracts=contracts),
        underlying_keys={"NIFTY 50": "NSE_INDEX|Nifty 50"},
        maximum_quote_age_seconds=120,
    )


def _prime(provider):
    return provider.option_instruments(
        underlying="NIFTY 50",
        evaluated_at=NOW,
    )


def _row(*, key="NSE_FO|987654", token="987654", price=110.0):
    return {
        "instrument_key": key,
        "instrument_token": token,
        "last_price": price,
        "bid_price": 109.0,
        "ask_price": 111.0,
        "timestamp": NOW.isoformat(),
    }


def test_upstox_contract_and_quote_normalization():
    provider = _provider({
        "data": {
            "NSE_FO|987654": _row(),
        }
    })
    instruments = _prime(provider)
    assert [item.option_side.value for item in instruments] == ["CE", "PE"]
    assert instruments[0].instrument_key == "NSE_FO|987654"
    assert instruments[0].instrument_token == 987654
    quotes = provider.quotes(
        instrument_keys=("NSE_FO|987654",),
        evaluated_at=NOW,
    )
    assert quotes[0].instrument_key == "NSE_FO|987654"
    assert quotes[0].instrument_token == 987654
    assert quotes[0].last_price == 110.0
    assert quotes[0].quote_timestamp == NOW


def test_upstox_documented_response_key_variation_is_normalized():
    provider = _provider({
        "data": {
            "NSE_FO:NIFTY26AUG25000CE": _row(
                key="NSE_FO|987654",
                token="NSE_FO|987654",
            ),
        }
    })
    _prime(provider)
    quotes = provider.quotes(
        instrument_keys=("NSE_FO|987654",),
        evaluated_at=NOW,
    )
    assert len(quotes) == 1
    assert quotes[0].instrument_key == "NSE_FO|987654"

    provider = _provider({
        "data": {
            "NSE_FO:987654": _row(),
        }
    })
    _prime(provider)
    quotes = provider.quotes(
        instrument_keys=("NSE_FO|987654",),
        evaluated_at=NOW,
    )
    assert len(quotes) == 1


def test_upstox_missing_timestamp_is_corruption():
    provider = _provider({
        "data": {
            "NSE_FO|987654": {
                "instrument_key": "NSE_FO|987654",
                "instrument_token": "987654",
                "last_price": 110.0,
            }
        }
    })
    _prime(provider)
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        provider.quotes(
            instrument_keys=("NSE_FO|987654",),
            evaluated_at=NOW,
        )
    assert captured.value.diagnostic.reason_code == "OPTION_QUOTE_TIMESTAMP_INVALID"


def test_upstox_swapped_rows_are_rejected():
    provider = _provider({
        "data": {
            "NSE_FO|987654": _row(
                key="NSE_FO|987655",
                token="987655",
            ),
            "NSE_FO|987655": _row(
                key="NSE_FO|987654",
                token="987654",
            ),
        }
    })
    _prime(provider)
    with pytest.raises(PaperMarketDataCorruptionError):
        provider.quotes(
            instrument_keys=("NSE_FO|987654", "NSE_FO|987655"),
            evaluated_at=NOW,
        )


def test_upstox_mismatched_token_is_rejected():
    provider = _provider({
        "data": {
            "NSE_FO|987654": _row(token="987655"),
        }
    })
    _prime(provider)
    with pytest.raises(PaperMarketDataCorruptionError):
        provider.quotes(
            instrument_keys=("NSE_FO|987654",),
            evaluated_at=NOW,
        )


def test_upstox_duplicate_response_identity_is_rejected():
    provider = _provider({
        "data": {
            "NSE_FO|987654": _row(),
            "NSE_FO:987654": _row(),
        }
    })
    _prime(provider)
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        provider.quotes(
            instrument_keys=("NSE_FO|987654",),
            evaluated_at=NOW,
        )
    assert captured.value.diagnostic.reason_code == "OPTION_QUOTE_DUPLICATE"


def test_upstox_unrequested_or_malformed_rows_are_corruption():
    provider = _provider({
        "data": {
            "NSE_FO|999999": _row(
                key="NSE_FO|999999",
                token="999999",
            ),
        }
    })
    _prime(provider)
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        provider.quotes(
            instrument_keys=("NSE_FO|987654",),
            evaluated_at=NOW,
        )
    assert captured.value.diagnostic.reason_code == "OPTION_QUOTE_IDENTITY_UNREQUESTED"


def test_upstox_empty_quote_result_is_count_incomplete():
    provider = _provider({"data": {}}, contracts=[])
    assert _prime(provider) == ()
    with pytest.raises(PaperMarketDataDiagnosticError) as captured:
        provider.quotes(
            instrument_keys=("NSE_FO|987654",),
            evaluated_at=NOW,
        )
    assert captured.value.diagnostic.reason_code == "OPTION_QUOTE_COUNT_INCOMPLETE"


def test_upstox_non_finite_contract_or_quote_is_corruption():
    provider = _provider(
        {"data": {}},
        contracts=[
            {
                "instrument_key": "NSE_FO|987654",
                "instrument_token": "987654",
                "trading_symbol": "NIFTY26AUG25000CE",
                "instrument_type": "CE",
                "expiry": "2026-08-27",
                "strike_price": float("nan"),
                "lot_size": 75,
            }
        ],
    )
    with pytest.raises(PaperMarketDataCorruptionError):
        _prime(provider)

    provider = _provider({
        "data": {
            "NSE_FO|987654": _row(price=float("inf")),
        }
    })
    _prime(provider)
    with pytest.raises(PaperMarketDataCorruptionError):
        provider.quotes(
            instrument_keys=("NSE_FO|987654",),
            evaluated_at=NOW,
        )
