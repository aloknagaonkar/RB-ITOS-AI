from __future__ import annotations

from red_bar_lab.ui.strategy_scoped_risk import build_risk_readiness, resolve_candidate_risk_context


def candidate(strategy_id="RSI_EXTREME_REVERSAL", bundle_id="B-1", instrument_key="I-1"):
    return {
        "candidate_id": strategy_id + "-C1",
        "strategy_id": strategy_id,
        "bundle_id": bundle_id,
        "identity_key": strategy_id + "|" + bundle_id + "|" + instrument_key,
        "instrument_key": instrument_key,
        "validation_outcome": "HANDOFF_READY",
        "ltp": 100.0,
        "lot_size": 75,
        "role": "ENTRY_1",
        "contract_side": "PE",
    }


def context():
    return {
        "available_cash": 100000.0,
        "daily_realized_pnl": 0.0,
        "daily_unrealized_pnl": 0.0,
        "daily_loss_limit": 5000.0,
        "portfolio_exposure": 0.0,
        "maximum_portfolio_exposure": 200000.0,
        "open_positions": 0,
        "maximum_open_positions": 10,
        "open_position_identity_keys": ["OTHER"],
        "emergency_stop": False,
        "global_cooldown_active": False,
        "proposed_lots": 1,
        "strategy_risk": {
            "RSI_EXTREME_REVERSAL": {"consumed": 100.0, "limit": 1000.0},
            "DIRECTIONAL_REGIME": {"consumed": 50.0, "limit": 1000.0},
        },
        "strategy_cooldowns": {
            "RSI_EXTREME_REVERSAL": True,
            "DIRECTIONAL_REGIME": False,
        },
    }


def test_strategy_cooldown_is_isolated():
    values = context()
    rsi = resolve_candidate_risk_context(values, candidate())
    dri = resolve_candidate_risk_context(values, candidate("DIRECTIONAL_REGIME"))
    assert rsi["cooldown_active"] is True
    assert dri["cooldown_active"] is False


def test_global_cooldown_has_precedence():
    values = context()
    values["global_cooldown_active"] = True
    result = resolve_candidate_risk_context(values, candidate("DIRECTIONAL_REGIME"))
    assert result["cooldown_active"] is True
    assert result["effective_cooldown_scope"]["global"] is True


def test_bundle_and_contract_scopes_are_candidate_specific():
    values = context()
    values["strategy_cooldowns"] = {}
    values["bundle_cooldowns"] = {"B-1": True}
    values["contract_cooldowns"] = {"I-2": True}
    assert resolve_candidate_risk_context(values, candidate(bundle_id="B-1"))["cooldown_active"] is True
    assert resolve_candidate_risk_context(values, candidate(bundle_id="B-2", instrument_key="I-2"))["cooldown_active"] is True
    assert resolve_candidate_risk_context(values, candidate(bundle_id="B-3", instrument_key="I-3"))["cooldown_active"] is False


def test_each_strategy_uses_its_own_scope():
    result = build_risk_readiness(
        {"candidates": [candidate(), candidate("DIRECTIONAL_REGIME")]},
        risk_context=context(),
    )
    rows = {row["strategy_id"]: row for row in result["rows"]}
    assert rows["RSI_EXTREME_REVERSAL"]["risk_outcome"] == "RISK_BLOCKED"
    assert "COOLDOWN_ACTIVE" in rows["RSI_EXTREME_REVERSAL"]["exact_reason"]
    assert rows["DIRECTIONAL_REGIME"]["risk_outcome"] == "RISK_READY_READ_ONLY"
    assert rows["DIRECTIONAL_REGIME"]["strategy_risk_scope"]["consumed"] == 50.0


def test_legacy_scalar_values_remain_supported():
    values = context()
    values.pop("strategy_risk")
    values.pop("strategy_cooldowns")
    values["strategy_loss_consumed"] = 10.0
    values["strategy_loss_limit"] = 100.0
    values["cooldown_active"] = False
    result = resolve_candidate_risk_context(values, candidate())
    assert result["strategy_loss_consumed"] == 10.0
    assert result["strategy_loss_limit"] == 100.0
    assert result["cooldown_active"] is False
