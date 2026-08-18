from __future__ import annotations

from red_bar_lab.ui.strategy_monetary_exposure import (
    apply_monetary_exposure_admission,
    canonical_contract_identity,
)


def candidate(candidate_id, side="CE", strike=25000, expiry="2026-08-27", token="101"):
    return {
        "candidate_id": candidate_id,
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "role": "ENTRY_1",
        "portfolio_outcome": "PORTFOLIO_READY_READ_ONLY",
        "portfolio_reason": "ALL_PORTFOLIO_CHECKS_PASSED",
        "exchange": "NFO",
        "instrument_token": token,
        "trading_symbol": f"NIFTY-{strike}-{side}",
        "contract_side": side,
        "expiry": expiry,
        "strike": strike,
        "ltp": 100.0,
        "lot_size": 75,
        "proposed_lots": 1,
        "opportunity": {
            "entry_premium": 100.0,
            "initial_option_stop": 97.0,
            "estimated_slippage": 0.4,
            "estimated_charges": 0.3,
        },
        "checks": [],
    }


def test_canonical_identity_prefers_exchange_and_token():
    identity = canonical_contract_identity(candidate("C1"))
    assert identity["key"] == "NFO|TOKEN|101"
    assert identity["confidence"] == "VERIFIED_EXCHANGE_TOKEN"


def test_symbol_fallback_is_explicitly_lower_confidence():
    row = candidate("C1")
    row.pop("exchange")
    row.pop("instrument_token")
    identity = canonical_contract_identity(row)
    assert identity["key"].startswith("SYMBOL|")
    assert identity["confidence"] == "FALLBACK_SYMBOL"


def test_cross_strategy_same_contract_is_rejected():
    active = candidate("ACTIVE")
    active["strategy_id"] = "DIRECTIONAL_REGIME"
    active["exposure"] = 7500.0
    result = apply_monetary_exposure_admission(
        {"rows": [candidate("RSI-1")]},
        account_context={"active_positions": [active]},
    )["rows"][0]
    assert result["portfolio_outcome"] == "REJECT"
    assert "REJECT_DUPLICATE_EXPOSURE" in result["portfolio_reason"]


def test_ce_and_pe_capital_and_risk_are_accumulated_separately():
    result = apply_monetary_exposure_admission(
        {"rows": [candidate("CE-1", side="CE", token="101"), candidate("PE-1", side="PE", token="102")]},
        account_context={},
    )
    assert result["ce_capital_exposure"] == 7500.0
    assert result["pe_capital_exposure"] == 7500.0
    assert result["ce_risk_exposure"] == 277.5
    assert result["pe_risk_exposure"] == 277.5


def test_directional_capital_limit_waits_only_when_configured_and_exceeded():
    row = apply_monetary_exposure_admission(
        {"rows": [candidate("CE-1")]},
        account_context={"maximum_ce_capital_exposure": 7000.0},
    )["rows"][0]
    assert row["portfolio_outcome"] == "WAIT"
    assert "WAIT_DIRECTIONAL_CAPITAL_CONCENTRATION" in row["portfolio_reason"]


def test_missing_monetary_limits_are_diagnostic_not_blocking():
    row = apply_monetary_exposure_admission(
        {"rows": [candidate("CE-1")]},
        account_context={},
    )["rows"][0]
    assert row["portfolio_outcome"] == "PORTFOLIO_READY_READ_ONLY"
    assert any(
        check["status"] == "INFO" and "NOT_CONFIGURED" in str(check["detail"])
        for check in row["checks"]
    )


def test_expiry_risk_limit_is_cumulative():
    first = candidate("C1", token="101")
    second = candidate("C2", token="102")
    rows = apply_monetary_exposure_admission(
        {"rows": [first, second]},
        account_context={"maximum_expiry_risk_exposure": 500.0},
    )["rows"]
    assert rows[0]["portfolio_outcome"] == "PORTFOLIO_READY_READ_ONLY"
    assert rows[1]["portfolio_outcome"] == "WAIT"
    assert "WAIT_EXPIRY_RISK_CONCENTRATION" in rows[1]["portfolio_reason"]


def test_same_strike_limit_counts_expiry_strike_and_side():
    first = candidate("C1", token="101")
    second = candidate("C2", token="102")
    rows = apply_monetary_exposure_admission(
        {"rows": [first, second]},
        account_context={"maximum_same_strike_positions": 1},
    )["rows"]
    assert rows[0]["portfolio_outcome"] == "PORTFOLIO_READY_READ_ONLY"
    assert rows[1]["portfolio_outcome"] == "WAIT"
    assert "WAIT_SAME_STRIKE_CONCENTRATION" in rows[1]["portfolio_reason"]


def test_model_is_read_only():
    result = apply_monetary_exposure_admission(
        {"rows": [candidate("C1")]},
        account_context={},
    )
    row = result["rows"][0]
    assert result["persisted"] is False
    assert result["reserved"] is False
    assert row["bundle_consumed"] is False
    assert row["submitted"] is False
