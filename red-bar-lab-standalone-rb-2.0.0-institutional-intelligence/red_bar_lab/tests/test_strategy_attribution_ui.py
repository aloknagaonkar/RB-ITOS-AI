from red_bar_lab.ui.strategy_attribution import (
    build_strategy_attribution,
)


def _order(**overrides):
    row = {
        "order_id": "PAPER-1",
        "tradingsymbol": "NIFTY26AUG25000CE",
        "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
        "strategy_stop_loss_pct": 7.0,
        "strategy_target_pct": None,
        "exit_mode": "RSI_PREMIUM_PROTECTION_ONLY",
        "evaluation_horizon_minutes": 15,
        "merge_status": "RSI_PRIMARY",
        "rsi_signal_id": "RSI7-ABC",
        "rsi_confirmation_timestamp": "2026-08-17T10:00:00+05:30",
    }
    row.update(overrides)
    return row


def test_pending_checkpoint_and_missing_telemetry():
    result = build_strategy_attribution(_order(), None, None)
    assert result["strategy"] == "RSI Extreme Reversal"
    assert result["exit_policy"] == "7.00% stop · No fixed target"
    assert result["checkpoint_status"] == "Pending"
    assert result["telemetry_status"] == "NOT_AVAILABLE"
    assert result["telemetry_authority"] == "OBSERVATIONAL_ONLY"


def test_captured_checkpoint_and_supported_telemetry():
    checkpoint = {
        "horizon_minutes": 15,
        "checkpoint_price": 109.0,
        "return_pct": 9.0,
        "mfe_points": 10.0,
        "mae_points": -2.0,
    }
    telemetry = {
        "support_classification": "SUPPORTED",
        "authority": "OBSERVATIONAL_ONLY",
        "premium_return_pct": 6.0,
        "oi_change": 2000.0,
        "relative_volume": 1.5,
        "spread_pct": 0.47,
        "iv": 12.5,
    }
    result = build_strategy_attribution(
        _order(),
        checkpoint,
        telemetry,
    )
    assert result["checkpoint_status"] == "Captured"
    assert "return 9.00%" in result["checkpoint_detail"]
    assert result["telemetry_status"] == "SUPPORTED"
    assert "OI Δ 2000.00" in result["telemetry_detail"]
    assert "relative volume 1.50" in result["telemetry_detail"]


def test_standard_strategy_fallback_remains_readable():
    result = build_strategy_attribution(
        _order(
            execution_strategy_source="REFERENCE_LEVEL",
            strategy_stop_loss_pct=15.0,
            strategy_target_pct=25.0,
            evaluation_horizon_minutes=0,
        ),
        None,
        None,
    )
    assert result["strategy"] == "REFERENCE_LEVEL"
    assert result["exit_policy"] == "15.00% stop · 25.00%"
    assert result["checkpoint_status"] == "Not configured"
