from __future__ import annotations

from red_bar_lab.ui.strategy_risk_readiness import build_risk_readiness


def _candidate(**overrides):
    row = {
        "candidate_id": "RSI-CAND-B1-T1-ENTRY-1",
        "identity_key": "IDENTITY-1",
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "bundle_id": "B1",
        "role": "ENTRY_1",
        "contract_side": "PE",
        "trading_symbol": "NIFTY-PE",
        "lot_size": 75,
        "ltp": 100.0,
        "validation_outcome": "HANDOFF_READY",
        "exact_reason": "ALL_MANDATORY_HANDOFF_CHECKS_PASSED",
    }
    row.update(overrides)
    return row


def _candidate_result(*rows):
    return {"candidates": list(rows)}


def _context(**overrides):
    value = {
        "available_cash": 100000.0,
        "daily_realized_pnl": -500.0,
        "daily_unrealized_pnl": 200.0,
        "daily_loss_limit": 5000.0,
        "strategy_loss_consumed": 500.0,
        "strategy_loss_limit": 3000.0,
        "portfolio_exposure": 10000.0,
        "maximum_portfolio_exposure": 50000.0,
        "open_positions": 1,
        "maximum_open_positions": 5,
        "open_position_identity_keys": ["OTHER"],
        "cooldown_active": False,
        "emergency_stop": False,
        "proposed_lots": 1,
    }
    value.update(overrides)
    return value


def test_complete_context_produces_read_only_risk_ready():
    result = build_risk_readiness(
        _candidate_result(_candidate()),
        risk_context=_context(),
    )

    assert result["outcome"] == "RISK_READY_READ_ONLY"
    assert result["risk_ready_count"] == 1
    row = result["rows"][0]
    assert row["required_premium"] == 7500.0
    assert row["risk_outcome"] == "RISK_READY_READ_ONLY"
    assert row["persisted"] is False
    assert row["reserved"] is False
    assert row["bundle_consumed"] is False
    assert row["submitted"] is False


def test_missing_account_context_waits_without_fabricating_values():
    result = build_risk_readiness(_candidate_result(_candidate()), risk_context={})

    assert result["outcome"] == "WAIT"
    row = result["rows"][0]
    assert row["available_cash"] is None
    assert "ACCOUNT_CASH_UNAVAILABLE" in row["exact_reason"]


def test_insufficient_capital_blocks_candidate():
    result = build_risk_readiness(
        _candidate_result(_candidate()),
        risk_context=_context(available_cash=5000.0),
    )

    row = result["rows"][0]
    assert row["risk_outcome"] == "RISK_BLOCKED"
    assert "INSUFFICIENT_CAPITAL" in row["exact_reason"]


def test_daily_and_strategy_loss_limits_block_independently():
    daily = build_risk_readiness(
        _candidate_result(_candidate()),
        risk_context=_context(daily_realized_pnl=-5000.0, daily_unrealized_pnl=0.0),
    )
    strategy = build_risk_readiness(
        _candidate_result(_candidate()),
        risk_context=_context(strategy_loss_consumed=3000.0),
    )

    assert "DAILY_LOSS_LIMIT_REACHED" in daily["rows"][0]["exact_reason"]
    assert "STRATEGY_LOSS_LIMIT_REACHED" in strategy["rows"][0]["exact_reason"]


def test_exposure_and_open_position_limits_block():
    exposure = build_risk_readiness(
        _candidate_result(_candidate()),
        risk_context=_context(portfolio_exposure=45000.0),
    )
    positions = build_risk_readiness(
        _candidate_result(_candidate()),
        risk_context=_context(open_positions=5),
    )

    assert "PORTFOLIO_EXPOSURE_LIMIT" in exposure["rows"][0]["exact_reason"]
    assert "OPEN_POSITION_LIMIT" in positions["rows"][0]["exact_reason"]


def test_duplicate_position_cooldown_and_emergency_stop_block():
    duplicate = build_risk_readiness(
        _candidate_result(_candidate()),
        risk_context=_context(open_position_identity_keys=["IDENTITY-1"]),
    )
    cooldown = build_risk_readiness(
        _candidate_result(_candidate()),
        risk_context=_context(cooldown_active=True),
    )
    emergency = build_risk_readiness(
        _candidate_result(_candidate()),
        risk_context=_context(emergency_stop=True),
    )

    assert "DUPLICATE_OPEN_POSITION" in duplicate["rows"][0]["exact_reason"]
    assert "COOLDOWN_ACTIVE" in cooldown["rows"][0]["exact_reason"]
    assert "EMERGENCY_STOP_ACTIVE" in emergency["rows"][0]["exact_reason"]


def test_candidate_not_handoff_ready_never_becomes_risk_ready():
    result = build_risk_readiness(
        _candidate_result(_candidate(validation_outcome="WAIT", exact_reason="MISSING_LOT_SIZE")),
        risk_context=_context(),
    )

    assert result["rows"][0]["risk_outcome"] == "RISK_BLOCKED"
    assert "CANDIDATE_NOT_HANDOFF_READY" in result["rows"][0]["exact_reason"]


def test_risk_module_contains_no_write_or_execution_action():
    import red_bar_lab.ui.strategy_risk_readiness as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "reserve_contract" not in source
    assert "update_position" not in source
