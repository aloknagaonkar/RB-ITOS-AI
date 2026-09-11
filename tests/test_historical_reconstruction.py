from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from market_lab.domain import HistoricalCandle, HistoricalOptionContract, IST
from market_lab.gateways import (
    GatewayError,
    UpstoxGateway,
    normalize_upstox_historical_candles,
    normalize_upstox_historical_option_contracts,
)
from market_lab.historical import (
    index_historical_option_candles,
    load_historical_option_candles,
    resolve_historical_atm,
    resolve_historical_option_contracts,
)


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

def option_contract(strike, side, expiry=SESSION, underlying=UNDERLYING, suffix=""):
    return HistoricalOptionContract(
        instrument_key=f"NSE_FO|{strike}|{side}{suffix}",
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        side=side,
        lot_size=75,
        is_weekly=True,
    )


def requested_option_contracts(atm=23250, wings=5):
    return [
        option_contract(strike, side)
        for strike in range(atm - wings * 50, atm + wings * 50 + 1, 50)
        for side in ("CE", "PE")
    ]


def test_normal_historical_option_atm_wings_resolution():
    selected = resolve_historical_option_contracts(
        requested_option_contracts(), UNDERLYING, SESSION, 23250, wings=5
    )

    assert len(selected) == 22
    assert [contract.strike for contract in selected[::2]] == list(range(23000, 23501, 50))
    assert [(contract.strike, contract.side) for contract in selected[:4]] == [
        (23000, "CE"), (23000, "PE"), (23050, "CE"), (23050, "PE")
    ]


def test_historical_option_resolution_orders_unordered_provider_contracts():
    contracts = list(reversed(requested_option_contracts(wings=1)))

    selected = resolve_historical_option_contracts(
        contracts, UNDERLYING, SESSION, 23250, wings=1
    )

    assert [(value.strike, value.side) for value in selected] == [
        (23200, "CE"), (23200, "PE"),
        (23250, "CE"), (23250, "PE"),
        (23300, "CE"), (23300, "PE"),
    ]


@pytest.mark.parametrize("missing_side", ["CE", "PE"])
def test_missing_historical_option_side_remains_absent(missing_side):
    contracts = [
        value for value in requested_option_contracts(wings=0)
        if value.side != missing_side
    ]

    selected = resolve_historical_option_contracts(
        contracts, UNDERLYING, SESSION, 23250, wings=0
    )

    assert len(selected) == 1
    assert selected[0].side != missing_side


def test_wrong_expiry_and_unrequested_strikes_are_excluded():
    contracts = [
        option_contract(23250, "CE"),
        option_contract(23250, "PE", expiry=date(2026, 9, 18)),
        option_contract(23300, "PE"),
    ]

    selected = resolve_historical_option_contracts(
        contracts, UNDERLYING, SESSION, 23250, wings=0
    )

    assert [(value.strike, value.side) for value in selected] == [(23250, "CE")]


def test_duplicate_historical_option_contract_is_rejected():
    contracts = [
        option_contract(23250, "CE"),
        option_contract(23250, "CE", suffix="-duplicate"),
    ]

    with pytest.raises(ValueError, match="Duplicate"):
        resolve_historical_option_contracts(
            contracts, UNDERLYING, SESSION, 23250, wings=0
        )


@pytest.mark.parametrize("atm", [300, 99900])
def test_historical_option_resolution_supports_low_and_high_positive_ranges(atm):
    selected = resolve_historical_option_contracts(
        requested_option_contracts(atm=atm), UNDERLYING, SESSION, atm, wings=5
    )

    assert selected[0].strike == atm - 250
    assert selected[-1].strike == atm + 250


def test_upstox_contract_normalization_filters_identity_and_preserves_metadata():
    rows = [
        {
            "instrument_key": "NSE_FO|PE", "underlying_key": UNDERLYING,
            "expiry": SESSION.isoformat(), "strike_price": 23250,
            "instrument_type": "PE", "lot_size": 75, "weekly": True,
        },
        {
            "instrument_key": "NSE_FO|CE", "underlying_key": UNDERLYING,
            "expiry": SESSION.isoformat(), "strike_price": 23250,
            "instrument_type": "CE",
        },
        {
            "instrument_key": "NSE_FO|WRONG", "underlying_key": UNDERLYING,
            "expiry": "2026-09-18", "strike_price": 23250,
            "instrument_type": "PE",
        },
    ]

    contracts = normalize_upstox_historical_option_contracts(
        UNDERLYING, SESSION, {"status": "success", "data": rows}
    )

    assert [value.side for value in contracts] == ["CE", "PE"]
    assert contracts[0].lot_size is None and contracts[0].is_weekly is None
    assert contracts[1].lot_size == 75 and contracts[1].is_weekly is True


def test_upstox_contract_normalization_rejects_duplicate_identity():
    row = {
        "underlying_key": UNDERLYING, "expiry": SESSION.isoformat(),
        "strike_price": 23250, "instrument_type": "CE", "lot_size": 75,
    }
    with pytest.raises(ValueError, match="Duplicate"):
        normalize_upstox_historical_option_contracts(
            UNDERLYING,
            SESSION,
            {"status": "success", "data": [
                dict(row, instrument_key="NSE_FO|1"),
                dict(row, instrument_key="NSE_FO|2"),
            ]},
        )


def test_upstox_contract_discovery_is_one_explicit_expiry_request():
    seen = []
    response = {
        "status": "success",
        "data": [{
            "instrument_key": "NSE_FO|1", "underlying_key": UNDERLYING,
            "expiry": SESSION.isoformat(), "strike_price": 23250,
            "instrument_type": "CE", "lot_size": 75,
        }],
    }

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=response)

    with httpx.Client(
        base_url="https://api.upstox.com", transport=httpx.MockTransport(handler)
    ) as client:
        contracts = UpstoxGateway("test-token", client).historical_option_contracts(
            UNDERLYING, SESSION
        )

    assert len(contracts) == 1 and len(seen) == 1
    assert seen[0].url.path == "/v2/option/contract"
    assert seen[0].url.params["instrument_key"] == UNDERLYING
    assert seen[0].url.params["expiry_date"] == SESSION.isoformat()


class StubHistoricalLoader:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def historical_candles(self, instrument_key, session_date):
        self.calls.append((instrument_key, session_date))
        return self.values.get(instrument_key, [])


def test_option_candle_loader_fetches_each_contract_once_and_builds_lookup():
    contracts = requested_option_contracts(wings=0)
    ce = candle(close=120).model_copy(update={
        "instrument_key": contracts[0].instrument_key,
        "open_interest": 1000,
    })
    pe = candle(close=80).model_copy(update={
        "instrument_key": contracts[1].instrument_key,
        "open_interest": 1500,
    })
    loader = StubHistoricalLoader({
        contracts[0].instrument_key: [ce],
        contracts[1].instrument_key: [pe],
    })

    series = load_historical_option_candles(loader, contracts, SESSION)
    lookup = index_historical_option_candles(series)

    assert loader.calls == [
        (contracts[0].instrument_key, SESSION),
        (contracts[1].instrument_key, SESSION),
    ]
    assert lookup[(ce.timestamp, 23250, "CE")].close == 120
    assert lookup[(pe.timestamp, 23250, "PE")].open_interest == 1500


def test_empty_option_candle_response_remains_an_empty_unavailable_series():
    contract = option_contract(23250, "CE")
    loader = StubHistoricalLoader({})

    series = load_historical_option_candles(loader, [contract], SESSION)

    assert len(series) == 1
    assert series[0].candles == []
    assert index_historical_option_candles(series) == {}


def test_missing_intraday_open_interest_remains_unavailable():
    contract = option_contract(23250, "CE")
    value = candle(close=120).model_copy(update={"instrument_key": contract.instrument_key})
    loader = StubHistoricalLoader({contract.instrument_key: [value]})

    series = load_historical_option_candles(loader, [contract], SESSION)

    assert series[0].candles[0].open_interest is None


def test_option_candle_series_rejects_wrong_contract_identity():
    contract = option_contract(23250, "CE")
    loader = StubHistoricalLoader({
        contract.instrument_key: [candle(close=120)]
    })

    with pytest.raises(ValidationError, match="identity mismatch"):
        load_historical_option_candles(loader, [contract], SESSION)


def test_option_candle_loader_rejects_duplicate_contracts_before_fetching():
    contract = option_contract(23250, "CE")
    loader = StubHistoricalLoader({})

    with pytest.raises(ValueError, match="unique"):
        load_historical_option_candles(loader, [contract, contract], SESSION)

    assert loader.calls == []