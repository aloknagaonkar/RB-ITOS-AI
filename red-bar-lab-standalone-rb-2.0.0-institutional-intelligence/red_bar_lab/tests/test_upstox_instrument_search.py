import pytest

from red_bar_lab.brokers.upstox_client import UpstoxAPIError
from red_bar_lab.services.upstox_instrument_search import (
    UpstoxInstrumentSearchTransport,
)


class _Response:
    def __init__(self, payload, *, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.response


def test_search_transport_calls_official_endpoint_with_filters():
    session = _Session(
        _Response(
            {
                "status": "success",
                "data": [
                    {
                        "instrument_key": "NSE_FO|58072",
                        "trading_symbol": "NIFTY FUT 25 AUG 26",
                        "underlying_symbol": "NIFTY",
                        "segment": "NSE_FO",
                        "instrument_type": "FUT",
                        "expiry": "2026-08-25",
                    }
                ],
            }
        )
    )
    transport = UpstoxInstrumentSearchTransport(
        "TOKEN",
        timeout=11,
        session=session,
    )

    rows = transport.search_instruments(
        query="NIFTY",
        exchanges="NSE",
        segments="FO",
        instrument_types="FUT",
        expiry="current_month",
        page_number=1,
        records=30,
    )

    assert rows[0]["instrument_key"] == "NSE_FO|58072"
    assert session.calls == [
        {
            "url": "https://api.upstox.com/v2/instruments/search",
            "params": {
                "query": "NIFTY",
                "exchanges": "NSE",
                "segments": "FO",
                "instrument_types": "FUT",
                "expiry": "current_month",
                "page_number": 1,
                "records": 30,
            },
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "Bearer TOKEN",
            },
            "timeout": 11,
        }
    ]


def test_search_transport_supports_optional_atm_offset():
    session = _Session(_Response({"status": "success", "data": []}))
    transport = UpstoxInstrumentSearchTransport("TOKEN", session=session)

    transport.search_instruments(
        query="NIFTY",
        atm_offset=0,
    )

    assert session.calls[0]["params"]["atm_offset"] == 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"query": ""}, "query is required"),
        ({"query": "X" * 51}, "at most 50"),
        ({"query": "NIFTY", "page_number": 0}, "at least 1"),
        ({"query": "NIFTY", "records": 31}, "between 1 and 30"),
    ],
)
def test_search_transport_validates_request(kwargs, message):
    transport = UpstoxInstrumentSearchTransport(
        "TOKEN",
        session=_Session(_Response({"data": []})),
    )

    with pytest.raises(ValueError, match=message):
        transport.search_instruments(**kwargs)


def test_search_transport_raises_api_error_for_malformed_payload():
    transport = UpstoxInstrumentSearchTransport(
        "TOKEN",
        session=_Session(_Response({"status": "success", "data": {}})),
    )

    with pytest.raises(UpstoxAPIError, match="Malformed instrument-search"):
        transport.search_instruments(query="NIFTY")


def test_search_transport_surfaces_provider_error_message():
    transport = UpstoxInstrumentSearchTransport(
        "TOKEN",
        session=_Session(
            _Response(
                {"errors": [{"message": "rate limit exceeded"}]},
                status_code=429,
            )
        ),
    )

    with pytest.raises(UpstoxAPIError, match="rate limit exceeded"):
        transport.search_instruments(query="NIFTY")
