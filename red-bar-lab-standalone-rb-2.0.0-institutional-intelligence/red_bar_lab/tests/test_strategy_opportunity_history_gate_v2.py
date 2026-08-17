from __future__ import annotations

from red_bar_lab.ui.strategy_opportunity_history_gate_v2 import build_opportunity_history_gate


def _candidate(**overrides):
    row = {
        "candidate_id": "RSI-CAND-1",
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "strategy_version": "RSI-V1",
        "setup_type": "RSI_CROSS_BACK",
        "exit_policy_version": "EXIT-V1",
        "role": "ENTRY_1",
        "contract_side": "PE",
        "validation_outcome": "HANDOFF_READY",
        "ltp": 100.0,
        "bid": 99.5,
        "ask": 100.5,
        "spread_pct": 1.0,
        "lot_size": 75,
        "snapshot_freshness": "FRESH",
        "bundle_freshness": "FRESH",
    }
    row.update(overrides)
    return row


def _opportunity():
    return {
        "initial_option_stop": 97.0,
        "estimated_slippage": 0.4,
        "estimated_charges": 0.3,
        "expected_favourable_excursion": 8.0,
        "expected_adverse_excursion": 2.5,
        "available_capital": 100000.0,
    }


def _record(**overrides):
    row = {
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "strategy_version": "RSI-V1",
        "setup_type": "RSI_CROSS_BACK",
        "exit_policy_version": "EXIT-V1",
        "role": "ENTRY_1",
        "side": "PE",
        "status": "CLOSED",
        "net_points": 3.0,
        "estimated_costs": 0.2,
    }
    row.update(overrides)
    return row


def _build(candidate, records):
    return build_opportunity_history_gate(
        {"candidates": [candidate]},
        opportunity_context=_opportunity(),
        historical_records=records,
    )["rows"][0]


def test_exact_context_tier_is_preferred():
    records = [_record() for _ in range(20)] + [
        _record(setup_type="OTHER", net_points=-10.0) for _ in range(30)
    ]
    row = _build(_candidate(), records)
    assert row["historical"]["matching_tier"] == "TIER_1_EXACT_CONTEXT"
    assert row["historical"]["sample_count"] == 20
    assert row["historical_outcome"] == "PASS"


def test_versioned_tier_relaxes_setup_when_exact_context_is_absent():
    records = [_record(setup_type="OTHER") for _ in range(20)]
    row = _build(_candidate(), records)
    assert row["historical"]["matching_tier"] == "TIER_2_VERSIONED_BASELINE"
    assert "setup_type" in row["historical"]["filters_relaxed_or_missing"]
    assert row["historical"]["sample_count"] == 20


def test_baseline_tier_is_used_when_version_fields_are_unavailable():
    candidate = _candidate(strategy_version=None, exit_policy_version=None, setup_type=None, role=None)
    row = _build(candidate, [_record(strategy_version=None, exit_policy_version=None) for _ in range(5)])
    assert row["historical"]["matching_tier"] == "TIER_3_STRATEGY_SIDE_BASELINE"
    assert row["historical"]["sample_count"] == 5
    assert row["historical_outcome"] == "OBSERVE_ONLY"


def test_other_strategy_and_side_never_enter_fallback_samples():
    records = (
        [_record() for _ in range(3)]
        + [_record(strategy_id="DIRECTIONAL_REGIME") for _ in range(50)]
        + [_record(side="CE") for _ in range(50)]
    )
    row = _build(_candidate(), records)
    assert row["historical"]["sample_count"] == 3
    assert row["historical_outcome"] == "NO_VETO_INSUFFICIENT_DATA"


def test_version_mismatch_does_not_enter_exact_or_versioned_tier():
    row = _build(_candidate(), [_record(strategy_version="RSI-V0") for _ in range(20)])
    assert row["historical"]["matching_tier"] == "TIER_3_STRATEGY_SIDE_BASELINE"
    assert row["historical"]["sample_count"] == 20


def test_coverage_diagnostics_are_propagated_without_changing_outcome():
    result = build_opportunity_history_gate(
        {"candidates": [_candidate()]},
        opportunity_context=_opportunity(),
        historical_records=[_record() for _ in range(20)],
        history_source={
            "source_status": "READY",
            "source_reason": "COMPLETED_TRADES_NORMALIZED",
            "coverage": {
                "coverage_status": "PARTIAL",
                "matching_readiness": "PARTIAL_VERSIONED_MATCHING",
                "excursion_readiness": "PARTIAL_MFE_MAE",
                "missing_fields": ["mfe_points"],
            },
        },
    )
    row = result["rows"][0]
    assert row["historical_outcome"] == "PASS"
    assert row["history_coverage_status"] == "PARTIAL"
    assert row["history_matching_readiness"] == "PARTIAL_VERSIONED_MATCHING"
    assert row["history_excursion_readiness"] == "PARTIAL_MFE_MAE"
    assert row["history_missing_fields"] == ["mfe_points"]
    assert result["history_coverage"]["coverage_status"] == "PARTIAL"


def test_v2_gate_remains_read_only():
    row = _build(_candidate(), [])
    assert row["persisted"] is False
    assert row["reserved"] is False
    assert row["bundle_consumed"] is False
    assert row["submitted"] is False
