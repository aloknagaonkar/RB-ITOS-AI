from __future__ import annotations

from red_bar_lab.ui.strategy_opportunity_context_source import build_opportunity_context


def candidate(candidate_id="RSI-1"):
    return {
        "candidate_id": candidate_id,
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "contract_side": "PE",
        "ltp": 100.0,
        "bid": 99.0,
        "ask": 101.0,
        "spread_pct": 2.0,
        "lot_size": 75,
    }


def history():
    return [
        {"strategy_id": "RSI_EXTREME_REVERSAL", "contract_side": "PE", "mfe_points": 8.0, "mae_points": 3.0},
        {"strategy_id": "RSI_EXTREME_REVERSAL", "contract_side": "PE", "mfe_points": 12.0, "mae_points": 5.0},
        {"strategy_id": "DIRECTIONAL_REGIME", "contract_side": "PE", "mfe_points": 50.0, "mae_points": 20.0},
    ]


def test_builds_quote_history_and_account_inputs_without_inventing_stop():
    result = build_opportunity_context(
        {"candidates": [candidate()]},
        historical_records=history(),
        account_context={
            "available_cash": 20000.0,
            "reserved_capital": 5000.0,
            "proposed_lots": 1,
            "estimated_charges_per_unit": 0.2,
        },
    )
    row = result["candidates"]["RSI-1"]
    assert row["initial_option_stop"] is None
    assert row["estimated_slippage"] == 1.0
    assert row["estimated_charges"] == 0.2
    assert row["expected_favourable_excursion"] == 10.0
    assert row["expected_adverse_excursion"] == 4.0
    assert row["available_capital"] == 15000.0
    assert row["proposed_lots"] == 1
    assert row["historical_excursion_sample_count"] == 2
    assert result["field_provenance"]["RSI-1"]["initial_option_stop"]["source"] == "UNAVAILABLE"


def test_candidate_native_stop_precedes_derived_sources():
    value = candidate()
    value["initial_stop"] = 97.0
    result = build_opportunity_context(
        {"candidates": [value]},
        historical_records=history(),
    )
    row = result["candidates"]["RSI-1"]
    assert row["initial_option_stop"] == 97.0
    assert result["field_provenance"]["RSI-1"]["initial_option_stop"]["source"] == "CANDIDATE"


def test_candidate_specific_explicit_override_has_highest_precedence():
    value = candidate()
    value["initial_stop"] = 97.0
    result = build_opportunity_context(
        {"candidates": [value]},
        historical_records=history(),
        explicit_context={
            "candidates": {
                "RSI-1": {
                    "initial_option_stop": 96.0,
                    "estimated_slippage": 0.5,
                    "estimated_charges": 0.1,
                }
            }
        },
    )
    row = result["candidates"]["RSI-1"]
    assert row["initial_option_stop"] == 96.0
    assert row["estimated_slippage"] == 0.5
    assert row["estimated_charges"] == 0.1
    assert result["field_provenance"]["RSI-1"]["initial_option_stop"]["source"] == "EXPLICIT_CALLER_OVERRIDE"


def test_history_is_scoped_by_strategy_and_side():
    ce = candidate("RSI-CE")
    ce["contract_side"] = "CE"
    result = build_opportunity_context(
        {"candidates": [ce]},
        historical_records=history(),
    )["candidates"]["RSI-CE"]
    assert result["expected_favourable_excursion"] is None
    assert result["expected_adverse_excursion"] is None
    assert result["historical_excursion_sample_count"] == 0


def test_adapter_is_read_only():
    result = build_opportunity_context(
        {"candidates": [candidate()]},
        historical_records=history(),
    )
    assert result["source_read_only"] is True
    assert result["persisted"] is False
    assert result["reserved"] is False
    assert result["submitted"] is False
