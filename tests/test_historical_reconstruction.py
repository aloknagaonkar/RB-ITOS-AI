from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from market_lab.domain import HistoricalCandle, IST
from market_lab.gateways import (
    GatewayError,
    UpstoxGateway,
    normalize_upstox_historical_candles,
)
from market_lab.historical import resolve_historical_atm


SESSION = date(2026, 9, 11)
UNDERLYING = "NSE_INDEX|Nifty 50"
FIRST = "2026-09-11T09:15:00+05:30"
SECOND = "2026-09-11T09:16:00+05:30"


def body(candles):
    return {"status": "success", "data": {"candles": candles}}


def candle(timestamp=FIRST, close=23435.1):
    return HistoricalCandle(
        provider="upstox",
        instrument_key=UNDERLYING,
        session_date=SESSION,
        timestamp=datetime.fromisoformat(timestamp),
        open=close,
        high=close + 5,
        low=close - 5,
        close=close,
    )


def test_valid_upstox_candles_are_normalized_and_ordered():
    values = normalize_upstox_historical_candles(
        UNDERLYING,
        SESSION,
        body([
            [SECOND, 23440, 23450, 23430, 23445, 1200, 40],
            [FIRST, 23430, 23440, 23420, 23435.1, 1000, 25],
        ]),
    )

    assert [value.timestamp.isoformat() for value in values] == [FIRST, SECOND]
    assert values[0].model_dump() == {
        "provider": "upstox",
        "instrument_key": UNDERLYING,
        "session_date": SESSION,
        "interval_seconds": 60,
        "timestamp": datetime.fromisoformat(FIRST),
        "open": 23430.0,
        "high": 23440.0,
        "low": 23420.0,
        "close": 23435.1,
        "volume": 1000,
        "open_interest": 25,
    }


def test_empty_historical_response_is_an_empty_series():
    assert normalize_upstox_historical_candles(UNDERLYING, SESSION, body([])) == []


@pytest.mark.parametrize(
    "value",
    [
        [FIRST, 23430, 23440, 23420],
        [FIRST, "23430", 23440, 23420, 23435],
        [FIRST, 23430, 23420, 23425, 23435],
        ["not-a-time", 23430, 23440, 23420, 23435],
        [FIRST, 23430, 23440, 23420, 23435, -1],
        [FIRST, 23430, 23440, 23420, 23435, 100, 1.5],
    ],
)
def test_malformed_historical_candle_is_rejected(value):
    with pytest.raises((ValueError, ValidationError)):
        normalize_upstox_historical_candles(UNDERLYING, SESSION, body([value]))


def test_missing_optional_volume_and_open_interest_remain_unavailable():
    value = normalize_upstox_historical_candles(
        UNDERLYING, SESSION, body([[FIRST, 23430, 23440, 23420, 23435.1]])
    )[0]

    assert value.volume is None
    assert value.open_interest is None


def test_timestamp_timezone_is_preserved_and_session_is_ist():
    value = normalize_upstox_historical_candles(
        UNDERLYING, SESSION, body([[FIRST, 23430, 23440, 23420, 23435.1]])
    )[0]

    assert value.timestamp.utcoffset() == timedelta(hours=5, minutes=30)
    assert value.timestamp.astimezone(IST).date() == SESSION


def test_timestamp_outside_requested_ist_session_is_rejected():
    with pytest.raises(ValidationError, match="requested IST session"):
        normalize_upstox_historical_candles(
            UNDERLYING,
            SESSION,
            body([["2026-09-10T23:59:00+05:30", 23430, 23440, 23420, 23435.1]]),
        )


def test_upstox_gateway_requests_explicit_one_minute_session_date():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=body([[FIRST, 23430, 23440, 23420, 23435.1]]))

    with httpx.Client(
        base_url="https://api.upstox.com", transport=httpx.MockTransport(handler)
    ) as client:
        values = UpstoxGateway("test-token", client).historical_candles(UNDERLYING, SESSION)

    assert len(values) == 1
    assert seen[0].method == "GET"
    assert seen[0].url.path.endswith("/minutes/1/2026-09-11/2026-09-11")
    assert "NSE_INDEX" in seen[0].url.path and "Nifty 50" in seen[0].url.path


def test_gateway_rejects_malformed_provider_history():
    with httpx.Client(
        base_url="https://api.upstox.com",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"status": "success", "data": {"candles": [[FIRST]]}})
        ),
    ) as client:
        with pytest.raises(GatewayError, match="schema validation"):
            UpstoxGateway("test-token", client).historical_candles(UNDERLYING, SESSION)


@pytest.mark.parametrize(
    "spot,expected",
    [
        (23424.9, 23400),
        (23425.0, 23450),
        (23435.1, 23450),
        (23449.9, 23450),
        (23450.0, 23450),
        (23474.9, 23450),
        (23475.0, 23500),
        (23475.1, 23500),
    ],
)
def test_historical_atm_boundaries_use_round_half_up(spot, expected):
    result = resolve_historical_atm([candle(close=spot)])

    assert result[0].spot == spot
    assert result[0].atm == expected
    assert result[0].timestamp == datetime.fromisoformat(FIRST)


def test_historical_atm_is_provider_independent_and_timestamp_ordered():
    later = candle(timestamp=SECOND, close=23475.1)
    earlier = candle(timestamp=FIRST, close=23424.9)

    results = resolve_historical_atm([later, earlier])

    assert [(value.timestamp.isoformat(), value.atm) for value in results] == [
        (FIRST, 23400),
        (SECOND, 23500),
    ]


def test_historical_atm_rejects_invalid_interval():
    with pytest.raises(ValueError, match="positive"):
        resolve_historical_atm([candle()], strike_interval=0)