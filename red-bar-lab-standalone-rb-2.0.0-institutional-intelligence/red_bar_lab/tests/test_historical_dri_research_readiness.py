from types import SimpleNamespace

import pandas as pd

from red_bar_lab.services.historical_dri_research_readiness import (
    HistoricalDRIResearchReadinessService,
)


def _contract(strike, option_type, *, candle=100.0, oi=100.0):
    expected = 100
    stored = int(expected * candle / 100.0)
    return SimpleNamespace(
        symbol=f"NIFTY{int(strike)}{option_type}",
        option_type=option_type,
        strike=float(strike),
        expected_bars=expected,
        stored_bars=stored,
        candle_coverage_pct=candle,
        missing_bars=expected - stored,
        oi_bars=int(expected * oi / 100.0),
    )


def _underlying():
    return pd.DataFrame(
        {
            "open": [24450.0, 24500.0],
            "high": [24520.0, 24575.0],
            "low": [24430.0, 24480.0],
            "close": [24490.0, 24540.0],
        }
    )


class _Historical:
    def read_day(self, instrument_key, trading_date, interval_minutes=1):
        return _underlying()


class _Sync:
    def __init__(self, global_ready=False, missing_near_market=False):
        self.global_ready = global_ready
        self.missing_near_market = missing_near_market

    def validate_day(self, instrument_key, trading_date):
        return SimpleNamespace(
            replay_ready=self.global_ready,
            fidelity=(
                "LIVE_CAPTURE_PARITY_HIGH"
                if self.global_ready
                else "UNRELIABLE_OPTION_REPLAY"
            ),
            reason="global result",
            data_source="LIVE_MARKET_CAPTURE" if self.global_ready else "EXPIRED_OPTION_CANDLES",
            contracts=(),
        )

    def _validate_expired_day(self, instrument_key, trading_date):
        contracts = []
        for strike in range(24250, 24751, 50):
            bad = self.missing_near_market and strike == 24500
            contracts.extend(
                [
                    _contract(strike, "CE", candle=0.0 if bad else 100.0, oi=0.0 if bad else 100.0),
                    _contract(strike, "PE"),
                ]
            )
        return SimpleNamespace(
            replay_ready=False,
            fidelity="UNRELIABLE_OPTION_REPLAY",
            contracts=tuple(contracts),
        )

    def option_candles_asof(self, *args, **kwargs):
        return "delegated"


def test_global_ready_is_preserved_without_reclassification():
    service = HistoricalDRIResearchReadinessService(_Sync(global_ready=True), _Historical())

    result = service.validate_day("NIFTY", object())

    assert result.replay_ready is True
    assert result.qualification == "GLOBAL_REPLAY_READY"
    assert result.fidelity == "LIVE_CAPTURE_PARITY_HIGH"


def test_relevant_complete_day_is_qualified_for_research_only():
    service = HistoricalDRIResearchReadinessService(_Sync(), _Historical())

    result = service.validate_day("NIFTY", object())

    assert result.replay_ready is True
    assert result.qualification == "STRATEGY_RELEVANT_COVERAGE_HIGH"
    assert result.fidelity == "STRATEGY_RELEVANT_OPTION_REPLAY"
    assert result.data_source == "EXPIRED_OPTION_CANDLES_RELEVANT_WINDOW"
    assert service.option_candles_asof() == "delegated"


def test_missing_relevant_contract_remains_not_ready():
    service = HistoricalDRIResearchReadinessService(
        _Sync(missing_near_market=True),
        _Historical(),
    )

    result = service.validate_day("NIFTY", object())

    assert result.replay_ready is False
    assert result.fidelity == "UNRELIABLE_OPTION_REPLAY"
