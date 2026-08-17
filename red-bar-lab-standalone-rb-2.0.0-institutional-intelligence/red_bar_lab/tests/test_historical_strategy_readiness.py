from datetime import date
from types import SimpleNamespace

import pandas as pd

from red_bar_lab.services.historical_strategy_adapters import (
    DRIHistoricalStrategyAdapter,
)
from red_bar_lab.services.historical_strategy_readiness import (
    HistoricalStrategyReadinessService,
)


class FakeReader:
    def read_day(self, instrument_key, trading_date, interval_minutes=1):
        return pd.DataFrame(
            {
                'open': [100.0, 101.0],
                'high': [102.0, 103.0],
                'low': [99.0, 100.0],
                'close': [101.0, 102.0],
            }
        )


def _contract(symbol, side, strike):
    return SimpleNamespace(
        symbol=symbol,
        option_type=side,
        strike=strike,
        expected_bars=100,
        stored_bars=100,
        oi_bars=100,
        candle_coverage_pct=100.0,
        missing_bars=0,
    )


class GloballyBlockedCoverage:
    replay_ready = False
    fidelity = 'UNRELIABLE_OPTION_REPLAY'
    reason = 'Full-chain coverage is below the authoritative threshold.'
    contracts = (
        _contract('CE100', 'CE', 100.0),
        _contract('PE100', 'PE', 100.0),
        _contract('CE105', 'CE', 105.0),
        _contract('PE105', 'PE', 105.0),
    )


class FakeSync:
    def validate_day(self, instrument_key, trading_date):
        return GloballyBlockedCoverage()


def test_relevant_high_never_overrides_global_replay_gate():
    service = HistoricalStrategyReadinessService(
        FakeSync(),
        FakeReader(),
    )

    audit = service.inspect_day(
        'NIFTY',
        date(2026, 8, 11),
    )

    assert audit.relevant_status == 'STRATEGY_RELEVANT_COVERAGE_HIGH'
    assert audit.global_replay_ready is False
    assert audit.effective_ready is False
    assert audit.coverage_basis == 'BLOCKED'


class NeverRunReplay:
    def __init__(self):
        self.called = False

    def run_day(self, instrument_key, trading_date):
        self.called = True
        raise AssertionError('Blocked replay must not run.')


class FakeReadiness:
    def inspect_day(self, instrument_key, trading_date):
        return SimpleNamespace(
            effective_ready=False,
            global_replay_ready=False,
            global_fidelity='UNRELIABLE_OPTION_REPLAY',
            global_reason='GLOBAL_BLOCK',
            coverage_basis='BLOCKED',
            relevant_status='STRATEGY_RELEVANT_COVERAGE_HIGH',
            relevant_reason='Diagnostic only.',
            relevant_contracts=4,
            relevant_ce_contracts=2,
            relevant_pe_contracts=2,
            relevant_complete_contracts=4,
            relevant_candle_coverage_pct=100.0,
            relevant_oi_coverage_pct=100.0,
            missing_relevant_contracts=0,
        )


def test_adapter_returns_blocked_diagnostics_without_running_replay():
    replay = NeverRunReplay()
    adapter = DRIHistoricalStrategyAdapter(
        replay,
        readiness_service=FakeReadiness(),
    )

    result = adapter.run_day(
        'NIFTY',
        date(2026, 8, 11),
    )

    assert result.ready is False
    assert result.global_replay_ready is False
    assert result.strategy_relevant_status == (
        'STRATEGY_RELEVANT_COVERAGE_HIGH'
    )
    assert result.coverage_basis == 'BLOCKED'
    assert replay.called is False
