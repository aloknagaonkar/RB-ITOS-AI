from datetime import date, datetime

from market_lab.domain import HistoricalCandle, HistoricalOptionContract, IST
from market_lab.historical_validation import validate_historical_session


UNDERLYING = "NSE_INDEX|Nifty 50"
SESSION = date(2026, 9, 8)
EXPIRY = date(2026, 9, 8)


def candle(instrument_key, minute, close, oi=None):
    timestamp = datetime(2026, 9, 8, 9, minute, tzinfo=IST)
    return HistoricalCandle(
        provider="upstox",
        instrument_key=instrument_key,
        session_date=SESSION,
        timestamp=timestamp,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=100,
        open_interest=oi,
    )


def contract(strike, side):
    return HistoricalOptionContract(
        instrument_key=f"NSE_FO|{strike}|{side}",
        underlying=UNDERLYING,
        expiry=EXPIRY,
        strike=strike,
        side=side,
        lot_size=75,
        is_weekly=True,
    )


class HistoricalGatewayStub:
    def __init__(self, underlying_candles, contracts, option_candles):
        self.underlying_candles = underlying_candles
        self.contracts = contracts
        self.option_candles = option_candles
        self.catalog_calls = []
        self.candle_calls = []

    def historical_candles(self, instrument_key, session_date):
        self.candle_calls.append(("underlying", instrument_key, session_date))
        if instrument_key != UNDERLYING:
            return []
        return self.underlying_candles

    def historical_option_candles(self, instrument_key, session_date):
        self.candle_calls.append(("option", instrument_key, session_date))
        return self.option_candles.get(instrument_key, [])

    def historical_option_contracts(self, underlying, expiry):
        self.catalog_calls.append((underlying, expiry))
        return self.contracts


def complete_inputs():
    underlying = [
        candle(UNDERLYING, 15, 23249),
        candle(UNDERLYING, 16, 23276),
        candle(UNDERLYING, 18, 23290),
    ]
    contracts = [
        contract(strike, side)
        for strike in (23250, 23300)
        for side in ("CE", "PE")
    ]
    option_candles = {
        value.instrument_key: [
            candle(
                value.instrument_key,
                minute,
                close=100 if value.side == "CE" else 120,
                oi=1000 if value.side == "CE" else 1500,
            )
            for minute in (15, 16, 18)
        ]
        for value in contracts
    }
    return underlying, contracts, option_candles


def test_historical_session_runner_executes_once_per_selected_contract():
    underlying, contracts, option_candles = complete_inputs()
    gateway = HistoricalGatewayStub(underlying, contracts, option_candles)

    report = validate_historical_session(
        gateway, UNDERLYING, SESSION, EXPIRY, wings=0
    )

    assert report.status == "AVAILABLE"
    assert report.underlying_candle_count == 3
    assert report.reconstructed_snapshot_count == 3
    assert report.first_timestamp == underlying[0].timestamp
    assert report.last_timestamp == underlying[-1].timestamp
    assert report.minimum_atm == 23250
    assert report.maximum_atm == 23300
    assert report.atm_change_count == 1
    assert report.selected_contract_count == 4
    assert gateway.catalog_calls == [(UNDERLYING, EXPIRY)]
    assert gateway.candle_calls[0] == ("underlying", UNDERLYING, SESSION)
    assert gateway.candle_calls[1:] == [
        ("option", value.instrument_key, SESSION)
        for value in contracts
    ]
    assert len(set(gateway.candle_calls[1:])) == 4


def test_historical_session_report_summarizes_pcr_gaps_and_provenance():
    underlying, contracts, option_candles = complete_inputs()
    report = validate_historical_session(
        HistoricalGatewayStub(underlying, contracts, option_candles),
        UNDERLYING,
        SESSION,
        EXPIRY,
        wings=0,
    )

    assert report.empty_candle_series_count == 0
    assert report.missing_contract_side_count == 0
    assert report.missing_candle_side_count == 0
    assert report.missing_oi_side_count == 0
    assert report.moving_pcr_available_count == 3
    assert report.moving_pcr_unavailable_count == 0
    assert report.full_reconstructed_pcr_available_count == 3
    assert report.full_reconstructed_pcr_unavailable_count == 0
    assert report.first_valid_moving_pcr.timestamp == underlying[0].timestamp
    assert report.first_valid_moving_pcr.pcr == 1.5
    assert report.last_valid_moving_pcr.timestamp == underlying[-1].timestamp
    assert len(report.timestamp_gaps) == 1
    assert report.timestamp_gaps[0].previous_timestamp == underlying[1].timestamp
    assert report.timestamp_gaps[0].next_timestamp == underlying[2].timestamp
    assert report.timestamp_gaps[0].elapsed_seconds == 120
    assert report.duplicate_timestamp_count == 0
    assert report.provenance == "HISTORICAL_CANDLE_RECONSTRUCTION"
    assert "snapshots" not in report.model_dump()
    assert "option_candles" not in report.model_dump()


def test_historical_session_report_preserves_partial_and_empty_data():
    underlying, contracts, option_candles = complete_inputs()
    missing_contract = next(
        value for value in contracts
        if value.strike == 23300 and value.side == "PE"
    )
    contracts.remove(missing_contract)
    empty_key = next(
        value.instrument_key for value in contracts
        if value.strike == 23250 and value.side == "CE"
    )
    missing_oi_key = next(
        value.instrument_key for value in contracts
        if value.strike == 23250 and value.side == "PE"
    )
    option_candles[empty_key] = []
    option_candles[missing_oi_key] = [
        candle(missing_oi_key, minute, close=120, oi=None)
        for minute in (15, 16, 18)
    ]
    gateway = HistoricalGatewayStub(underlying, contracts, option_candles)

    report = validate_historical_session(
        gateway, UNDERLYING, SESSION, EXPIRY, wings=0
    )

    assert report.selected_contract_count == 3
    assert report.empty_candle_series_count == 1
    assert report.missing_contract_side_count == 2
    assert report.missing_candle_side_count == 1
    assert report.missing_oi_side_count == 1
    assert report.moving_pcr_available_count == 0
    assert report.moving_pcr_unavailable_count == 3
    assert report.first_valid_moving_pcr is None
    assert len(gateway.candle_calls[1:]) == 3
    assert missing_contract.instrument_key not in {
        instrument_key for _, instrument_key, _ in gateway.candle_calls
    }


def test_empty_underlying_session_exits_cleanly_without_other_provider_calls():
    gateway = HistoricalGatewayStub([], [], {})

    report = validate_historical_session(
        gateway, UNDERLYING, SESSION, EXPIRY, wings=5
    )

    assert report.status == "UNAVAILABLE"
    assert report.issues == ["underlying_candles_unavailable"]
    assert report.underlying_candle_count == 0
    assert report.reconstructed_snapshot_count == 0
    assert report.selected_contract_count == 0
    assert gateway.candle_calls == [("underlying", UNDERLYING, SESSION)]
    assert gateway.catalog_calls == []


def test_duplicate_underlying_timestamps_are_reported_without_reconstruction():
    duplicate = candle(UNDERLYING, 15, 23249)
    gateway = HistoricalGatewayStub([duplicate, duplicate], [], {})

    report = validate_historical_session(
        gateway, UNDERLYING, SESSION, EXPIRY, wings=5
    )

    assert report.status == "UNAVAILABLE"
    assert report.duplicate_timestamp_count == 1
    assert report.issues == ["duplicate_underlying_timestamps"]
    assert report.reconstructed_snapshot_count == 0
    assert gateway.catalog_calls == []
    assert gateway.candle_calls == [("underlying", UNDERLYING, SESSION)]