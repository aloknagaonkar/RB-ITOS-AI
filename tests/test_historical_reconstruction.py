from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from market_lab.domain import (
    HistoricalCandle,
    HistoricalOptionCandleSeries,
    HistoricalOptionContract,
    IST,
    PCRConfig,
    Quote,
    calculate_pcr_value,
    evaluate,
)
from market_lab.gateways import DemoGateway
from market_lab.gateways import (
    GatewayError,
    UpstoxGateway,
    normalize_upstox_historical_candles,
    normalize_upstox_historical_option_contracts,
)
from market_lab.historical import (
    index_historical_option_candles,
    load_historical_option_candles,
    reconstruct_historical_pcr,
    reconstruct_historical_snapshots,
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

def option_series(contracts, timestamps=(FIRST,), missing_candles=(), missing_oi=()):
    missing_candles = set(missing_candles)
    missing_oi = set(missing_oi)
    values = []
    for contract in contracts:
        candles = []
        if contract.instrument_key not in missing_candles:
            for timestamp in timestamps:
                candles.append(candle(timestamp=timestamp, close=100).model_copy(update={
                    "instrument_key": contract.instrument_key,
                    "volume": 500,
                    "open_interest": None if contract.instrument_key in missing_oi else 1000,
                }))
        values.append(HistoricalOptionCandleSeries(
            contract=contract,
            session_date=SESSION,
            candles=candles,
        ))
    return values


def reconstruct(
    timeline=None, contracts=None, series=None, wings=5, session_date=SESSION
):
    timeline = timeline or [candle(close=23250)]
    contracts = contracts if contracts is not None else requested_option_contracts(wings=wings)
    series = series if series is not None else option_series(contracts)
    return reconstruct_historical_snapshots(
        timeline,
        contracts,
        series,
        underlying=UNDERLYING,
        expiry=SESSION,
        session_date=session_date,
        wings=wings,
        strike_interval=50,
    )


def test_complete_canonical_historical_snapshot_reconstruction():
    snapshots = reconstruct()

    assert len(snapshots) == 1
    value = snapshots[0]
    assert value.timestamp == datetime.fromisoformat(FIRST)
    assert value.spot == 23250
    assert value.moving_atm == 23250
    assert len(value.strikes) == 11
    assert [row.strike for row in value.strikes] == list(range(23000, 23501, 50))
    assert all(row.ce.status == row.pe.status == "AVAILABLE" for row in value.strikes)
    assert all(row.ce.close == row.pe.close == 100 for row in value.strikes)
    assert all(row.ce.open_interest == row.pe.open_interest == 1000 for row in value.strikes)


def test_reconstruction_tracks_moving_atm_on_underlying_timeline():
    timeline = [
        candle(timestamp=SECOND, close=23276),
        candle(timestamp=FIRST, close=23249),
    ]
    contracts_by_key = {
        contract.instrument_key: contract
        for contract in requested_option_contracts(atm=23250)
        + requested_option_contracts(atm=23300)
    }
    contracts = list(contracts_by_key.values())
    snapshots = reconstruct(
        timeline=timeline,
        contracts=contracts,
        series=option_series(contracts, timestamps=(FIRST, SECOND)),
    )

    assert [value.timestamp.isoformat() for value in snapshots] == [FIRST, SECOND]
    assert [value.moving_atm for value in snapshots] == [23250, 23300]
    assert snapshots[0].strikes[0].strike == 23000
    assert snapshots[1].strikes[-1].strike == 23550


@pytest.mark.parametrize("missing_side", ["CE", "PE"])
def test_missing_contract_side_does_not_hide_available_other_side(missing_side):
    contracts = [
        contract for contract in requested_option_contracts(wings=0)
        if contract.side != missing_side
    ]

    row = reconstruct(
        contracts=contracts,
        series=option_series(contracts),
        wings=0,
    )[0].strikes[0]

    missing = row.ce if missing_side == "CE" else row.pe
    available = row.pe if missing_side == "CE" else row.ce
    assert missing.status == "CONTRACT_UNAVAILABLE"
    assert missing.instrument_key is None
    assert missing.close is None
    assert missing.open_interest is None
    assert available.status == "AVAILABLE"


@pytest.mark.parametrize("missing_side", ["CE", "PE"])
def test_missing_exact_candle_side_does_not_hide_available_other_side(missing_side):
    contracts = requested_option_contracts(wings=0)
    missing_key = next(value.instrument_key for value in contracts if value.side == missing_side)

    row = reconstruct(
        contracts=contracts,
        series=option_series(contracts, missing_candles={missing_key}),
        wings=0,
    )[0].strikes[0]

    missing = row.ce if missing_side == "CE" else row.pe
    available = row.pe if missing_side == "CE" else row.ce
    assert missing.status == "CANDLE_UNAVAILABLE"
    assert missing.instrument_key == missing_key
    assert missing.close is None
    assert missing.open_interest is None
    assert available.status == "AVAILABLE"


def test_candle_price_survives_when_intraday_oi_is_missing():
    contracts = requested_option_contracts(wings=0)
    ce_key = next(value.instrument_key for value in contracts if value.side == "CE")

    row = reconstruct(
        contracts=contracts,
        series=option_series(contracts, missing_oi={ce_key}),
        wings=0,
    )[0].strikes[0]

    assert row.ce.status == "OI_UNAVAILABLE"
    assert row.ce.close == 100
    assert row.ce.open_interest is None
    assert row.pe.status == "AVAILABLE"


def test_empty_option_series_remains_candle_unavailable_without_zero_substitution():
    contracts = requested_option_contracts(wings=0)

    row = reconstruct(
        contracts=contracts,
        series=option_series(contracts, missing_candles={
            contract.instrument_key for contract in contracts
        }),
        wings=0,
    )[0].strikes[0]

    assert row.ce.status == row.pe.status == "CANDLE_UNAVAILABLE"
    assert row.ce.close is None and row.pe.close is None
    assert row.ce.open_interest is None and row.pe.open_interest is None


def test_reconstruction_uses_exact_timestamp_without_interpolation_or_fill():
    timeline = [
        candle(timestamp=FIRST, close=23250),
        candle(timestamp=SECOND, close=23250),
    ]
    contracts = requested_option_contracts(wings=0)

    snapshots = reconstruct(
        timeline=timeline,
        contracts=contracts,
        series=option_series(contracts, timestamps=(FIRST,)),
        wings=0,
    )

    assert all(side.status == "AVAILABLE" for side in (
        snapshots[0].strikes[0].ce, snapshots[0].strikes[0].pe
    ))
    assert all(side.status == "CANDLE_UNAVAILABLE" for side in (
        snapshots[1].strikes[0].ce, snapshots[1].strikes[0].pe
    ))
    assert snapshots[1].strikes[0].ce.close is None
    assert snapshots[1].strikes[0].pe.open_interest is None


def test_reconstruction_order_and_provenance_are_deterministic():
    timeline = [
        candle(timestamp=SECOND, close=23250),
        candle(timestamp=FIRST, close=23250),
    ]
    contracts = list(reversed(requested_option_contracts(wings=1)))

    snapshots = reconstruct(
        timeline=timeline,
        contracts=contracts,
        series=list(reversed(option_series(contracts, timestamps=(FIRST, SECOND)))),
        wings=1,
    )

    assert [value.timestamp.isoformat() for value in snapshots] == [FIRST, SECOND]
    assert all(value.provenance == "HISTORICAL_CANDLE_RECONSTRUCTION" for value in snapshots)
    assert all(
        row.provenance == "HISTORICAL_CANDLE_RECONSTRUCTION"
        for value in snapshots for row in value.strikes
    )
    assert [row.strike for row in snapshots[0].strikes] == [23200, 23250, 23300]


def test_reconstruction_does_not_mutate_inputs_and_repeats_equivalently():
    timeline = [candle(close=23250)]
    contracts = requested_option_contracts(wings=1)
    series = option_series(contracts)
    before = (
        [value.model_dump(mode="json") for value in timeline],
        [value.model_dump(mode="json") for value in contracts],
        [value.model_dump(mode="json") for value in series],
    )

    first = reconstruct(timeline=timeline, contracts=contracts, series=series, wings=1)
    second = reconstruct(timeline=timeline, contracts=contracts, series=series, wings=1)

    assert first == second
    assert [value.model_dump(mode="json") for value in first] == [
        value.model_dump(mode="json") for value in second
    ]
    assert before == (
        [value.model_dump(mode="json") for value in timeline],
        [value.model_dump(mode="json") for value in contracts],
        [value.model_dump(mode="json") for value in series],
    )


def test_wrong_session_underlying_timeline_is_rejected():
    wrong_session = date(2026, 9, 10)
    wrong = HistoricalCandle(
        provider="upstox",
        instrument_key=UNDERLYING,
        session_date=wrong_session,
        timestamp=datetime(2026, 9, 10, 9, 15, tzinfo=IST),
        open=23250,
        high=23255,
        low=23245,
        close=23250,
    )

    with pytest.raises(ValueError, match="session mismatch"):
        reconstruct(timeline=[wrong], wings=0)

def snapshot_with_oi(timestamp=FIRST, spot=23250, wings=0, call_oi=100, put_oi=150):
    contracts = requested_option_contracts(atm=spot, wings=wings)
    reconstructed = reconstruct(
        timeline=[candle(timestamp=timestamp, close=spot)],
        contracts=contracts,
        series=option_series(contracts, timestamps=(timestamp,)),
        wings=wings,
    )[0]
    rows = []
    for row in reconstructed.strikes:
        rows.append(row.model_copy(update={
            "ce": row.ce.model_copy(update={"open_interest": call_oi}),
            "pe": row.pe.model_copy(update={"open_interest": put_oi}),
        }))
    return reconstructed.model_copy(update={"strikes": rows})


def test_historical_strike_and_panel_pcr_use_valid_oi():
    observation = reconstruct_historical_pcr([
        snapshot_with_oi(wings=1, call_oi=100, put_oi=150)
    ])[0]

    assert [result.pcr for result in observation.strike_results] == [1.5, 1.5, 1.5]
    assert observation.moving_panel.call_oi == 300
    assert observation.moving_panel.put_oi == 450
    assert observation.moving_panel.pcr == 1.5
    assert observation.moving_panel.status == "AVAILABLE"


def test_first_historical_observation_has_no_previous_oi_or_change():
    observation = reconstruct_historical_pcr([
        snapshot_with_oi(call_oi=100, put_oi=150)
    ])[0]
    strike = observation.strike_results[0]

    assert strike.call_oi == 100 and strike.put_oi == 150
    assert strike.previous_call_oi is None and strike.previous_put_oi is None
    assert strike.call_oi_change is None and strike.put_oi_change is None
    assert strike.call_oi_change_pct is None and strike.put_oi_change_pct is None


def test_consecutive_historical_oi_change_and_percentage():
    first = snapshot_with_oi(timestamp=FIRST, call_oi=100, put_oi=150)
    second = snapshot_with_oi(timestamp=SECOND, call_oi=120, put_oi=180)

    observation = reconstruct_historical_pcr([second, first])[1]
    strike = observation.strike_results[0]

    assert strike.previous_call_oi == 100 and strike.previous_put_oi == 150
    assert strike.call_oi_change == 20 and strike.put_oi_change == 30
    assert strike.call_oi_change_pct == pytest.approx(20)
    assert strike.put_oi_change_pct == pytest.approx(20)
    assert observation.moving_panel.call_oi_change == 20
    assert observation.moving_panel.put_oi_change_pct == pytest.approx(20)


@pytest.mark.parametrize("missing_side", ["ce", "pe"])
def test_missing_current_historical_oi_remains_unavailable(missing_side):
    value = snapshot_with_oi()
    row = value.strikes[0]
    missing = getattr(row, missing_side).model_copy(update={
        "open_interest": None,
        "status": "OI_UNAVAILABLE",
    })
    value = value.model_copy(update={
        "strikes": [row.model_copy(update={missing_side: missing})]
    })

    observation = reconstruct_historical_pcr([value])[0]
    strike = observation.strike_results[0]

    assert getattr(strike, "call_oi" if missing_side == "ce" else "put_oi") is None
    assert strike.pcr is None
    assert strike.status == "UNAVAILABLE"
    assert observation.moving_panel.pcr is None
    assert observation.moving_panel.call_oi is None
    assert observation.moving_panel.put_oi is None


def test_missing_previous_side_oi_keeps_changes_unavailable():
    first = snapshot_with_oi(timestamp=FIRST)
    row = first.strikes[0]
    first = first.model_copy(update={"strikes": [row.model_copy(update={
        "ce": row.ce.model_copy(update={"open_interest": None, "status": "OI_UNAVAILABLE"})
    })]})
    second = snapshot_with_oi(timestamp=SECOND, call_oi=120, put_oi=180)

    strike = reconstruct_historical_pcr([first, second])[1].strike_results[0]

    assert strike.previous_call_oi is None
    assert strike.call_oi_change is None
    assert strike.call_oi_change_pct is None
    assert strike.previous_put_oi == 150
    assert strike.put_oi_change == 30


@pytest.mark.parametrize(
    "side_status",
    ["CONTRACT_UNAVAILABLE", "CANDLE_UNAVAILABLE"],
)
def test_missing_contract_or_candle_never_substitutes_zero(side_status):
    value = snapshot_with_oi()
    row = value.strikes[0]
    unavailable = row.ce.model_copy(update={
        "instrument_key": None if side_status == "CONTRACT_UNAVAILABLE" else row.ce.instrument_key,
        "close": None,
        "open_interest": None,
        "volume": None,
        "status": side_status,
    })
    value = value.model_copy(update={
        "strikes": [row.model_copy(update={"ce": unavailable})]
    })

    result = reconstruct_historical_pcr([value])[0].strike_results[0]

    assert result.call_oi is None
    assert result.put_oi == 150
    assert result.pcr is None
    assert any(side_status.lower() in issue for issue in result.issues)


def test_zero_call_oi_denominator_is_unavailable_not_divided():
    observation = reconstruct_historical_pcr([
        snapshot_with_oi(call_oi=0, put_oi=150)
    ])[0]

    assert observation.strike_results[0].call_oi == 0
    assert observation.strike_results[0].pcr is None
    assert "zero_call_oi" in observation.strike_results[0].issues
    assert observation.moving_panel.pcr is None


def test_timeline_gap_does_not_forward_fill_previous_oi():
    first = snapshot_with_oi(timestamp=FIRST, call_oi=100, put_oi=150)
    third_time = "2026-09-11T09:17:00+05:30"
    third = snapshot_with_oi(timestamp=third_time, call_oi=120, put_oi=180)

    strike = reconstruct_historical_pcr([first, third])[1].strike_results[0]

    assert strike.previous_call_oi is None
    assert strike.previous_put_oi is None
    assert strike.call_oi_change is None
    assert strike.put_oi_change_pct is None


def test_moving_atm_changes_panel_membership_and_full_is_reconstructed_scope():
    first = snapshot_with_oi(timestamp=FIRST, spot=23250, wings=1)
    second = snapshot_with_oi(timestamp=SECOND, spot=23300, wings=1)

    observations = reconstruct_historical_pcr([second, first])

    assert observations[0].moving_atm == 23250
    assert observations[0].moving_panel.strikes == [23200, 23250, 23300]
    assert observations[1].moving_atm == 23300
    assert observations[1].moving_panel.strikes == [23250, 23300, 23350]
    assert observations[1].full_reconstructed_panel.mode == "full_reconstructed"
    assert observations[1].full_reconstructed_panel.strikes == observations[1].moving_panel.strikes


def test_fixed_historical_panel_is_explicitly_unavailable():
    fixed = reconstruct_historical_pcr([snapshot_with_oi()])[0].fixed_panel

    assert fixed.mode == "fixed"
    assert fixed.status == "UNAVAILABLE"
    assert fixed.pcr is None
    assert fixed.call_oi is None and fixed.put_oi is None
    assert fixed.issues == ["fixed_basket_not_reconstructed"]


def test_historical_pcr_provenance_order_and_repeatability():
    first = snapshot_with_oi(timestamp=FIRST)
    second = snapshot_with_oi(timestamp=SECOND, call_oi=110, put_oi=160)

    one = reconstruct_historical_pcr([second, first])
    two = reconstruct_historical_pcr([second, first])

    assert one == two
    assert [value.timestamp.isoformat() for value in one] == [FIRST, SECOND]
    assert all(value.provenance == "HISTORICAL_CANDLE_RECONSTRUCTION" for value in one)
    assert all(
        result.provenance == "HISTORICAL_CANDLE_RECONSTRUCTION"
        for value in one for result in value.strike_results
    )
    assert all(value.moving_panel.provenance == "HISTORICAL_CANDLE_RECONSTRUCTION" for value in one)


def test_equivalent_aware_timestamps_match_exact_previous_contract():
    first = snapshot_with_oi(timestamp=FIRST, call_oi=100, put_oi=150)
    second_utc = datetime.fromisoformat(SECOND).astimezone(timezone.utc).isoformat()
    second = snapshot_with_oi(timestamp=second_utc, call_oi=120, put_oi=180)

    strike = reconstruct_historical_pcr([first, second])[1].strike_results[0]

    assert strike.previous_call_oi == 100
    assert strike.call_oi_change == 20


def test_historical_pcr_requires_no_loader_or_network_call():
    value = snapshot_with_oi()

    result = reconstruct_historical_pcr([value])

    assert len(result) == 1
    assert result[0].moving_panel.pcr == 1.5


def test_shared_pcr_core_matches_equivalent_live_oi_math():
    config = PCRConfig(expiry=date(2026, 9, 15), wings=0)
    live = DemoGateway().collect_at(
        config, datetime(2026, 9, 9, 9, 20, tzinfo=IST), 0
    )
    atm = min({contract.strike for contract in live.catalog}, key=lambda strike: abs(strike-live.spot))
    quotes = [
        Quote(key=contract.key, oi=100 if contract.side == "CE" else 150)
        for contract in live.catalog if contract.strike == atm
    ]
    live_result = next(
        result for result in evaluate(live.model_copy(update={"quotes": quotes}), config).results
        if result.mode == "moving"
    )
    historical = reconstruct_historical_pcr([
        snapshot_with_oi(call_oi=100, put_oi=150)
    ])[0]

    assert live_result.pcr == calculate_pcr_value(150, 100)
    assert historical.moving_panel.pcr == live_result.pcr