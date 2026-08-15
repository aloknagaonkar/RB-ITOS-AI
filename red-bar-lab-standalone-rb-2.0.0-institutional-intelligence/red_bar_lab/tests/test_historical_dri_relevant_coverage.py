from types import SimpleNamespace

import pandas as pd

from red_bar_lab.services.historical_dri_relevant_coverage import (
    analyze_historical_dri_relevant_coverage,
)


def _contract(strike, option_type, candle=100.0, oi=100.0, expected=100):
    return SimpleNamespace(
        symbol=f"NIFTY{int(strike)}{option_type}",
        option_type=option_type,
        strike=float(strike),
        expected_bars=expected,
        stored_bars=int(expected * candle / 100.0),
        candle_coverage_pct=candle,
        missing_bars=expected - int(expected * candle / 100.0),
        oi_bars=int(expected * oi / 100.0),
    )


def _underlying(low=24000.0, high=24100.0):
    return pd.DataFrame(
        {
            "open": [24020.0, 24080.0],
            "high": [24050.0, high],
            "low": [low, 24040.0],
            "close": [24040.0, 24090.0],
        }
    )


def test_far_otm_missing_contracts_do_not_reduce_relevant_coverage():
    contracts = []
    for strike in range(23800, 24301, 50):
        contracts.extend([
            _contract(strike, "CE"),
            _contract(strike, "PE"),
        ])
    contracts.extend([
        _contract(25000, "CE", candle=0.0, oi=0.0),
        _contract(25000, "PE", candle=0.0, oi=0.0),
    ])
    coverage = SimpleNamespace(
        replay_ready=False,
        fidelity="UNRELIABLE_OPTION_REPLAY",
        contracts=tuple(contracts),
    )

    audit = analyze_historical_dri_relevant_coverage(coverage, _underlying())

    assert audit.status == "STRATEGY_RELEVANT_COVERAGE_HIGH"
    assert audit.relevant_complete_contracts == audit.relevant_contracts
    assert audit.missing_relevant_contracts == 0
    assert audit.global_replay_ready is False


def test_missing_near_market_contract_keeps_relevant_audit_incomplete():
    contracts = []
    for strike in range(23800, 24301, 50):
        candle = 0.0 if strike == 24050 else 100.0
        contracts.extend([
            _contract(strike, "CE", candle=candle, oi=candle),
            _contract(strike, "PE"),
        ])
    coverage = SimpleNamespace(
        replay_ready=False,
        fidelity="UNRELIABLE_OPTION_REPLAY",
        contracts=tuple(contracts),
    )

    audit = analyze_historical_dri_relevant_coverage(coverage, _underlying())

    assert audit.status == "STRATEGY_RELEVANT_COVERAGE_INCOMPLETE"
    assert audit.missing_relevant_contracts == 1
    assert audit.relevant_complete_contracts < audit.relevant_contracts


def test_global_ready_remains_full_replay_ready():
    coverage = SimpleNamespace(
        replay_ready=True,
        fidelity="PARTIAL_LIVE_PARITY_HIGH",
        contracts=(
            _contract(24000, "CE"),
            _contract(24000, "PE"),
            _contract(24050, "CE"),
            _contract(24050, "PE"),
        ),
    )

    audit = analyze_historical_dri_relevant_coverage(coverage, _underlying(24000, 24050))

    assert audit.status == "FULL_REPLAY_READY"
    assert audit.strategy_relevant_ready is True


def test_missing_underlying_data_returns_insufficient_audit_status():
    coverage = SimpleNamespace(
        replay_ready=False,
        fidelity="UNRELIABLE_OPTION_REPLAY",
        contracts=(_contract(24000, "CE"), _contract(24000, "PE")),
    )

    audit = analyze_historical_dri_relevant_coverage(
        coverage,
        pd.DataFrame(),
    )

    assert audit.status == "INSUFFICIENT_AUDIT_DATA"
    assert audit.relevant_contracts == 0
