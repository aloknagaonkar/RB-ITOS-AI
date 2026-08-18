from red_bar_lab.ui.controlled_paper_activation import (
    PaperActivationControls,
    build_controlled_paper_activation,
)


def _router():
    return {
        "rows": [
            {
                "route_id": "ROUTE-1",
                "route_outcome": "ROUTED_SHADOW_ONLY",
                "strategy_id": "RED_BAR",
                "signal_id": "RB-1",
                "bundle_id": "BUNDLE-1",
                "candidate_id": "CANDIDATE-1",
            }
        ]
    }


def test_default_activation_is_blocked_and_side_effect_free():
    result = build_controlled_paper_activation(_router())

    assert result["outcome"] == "PAPER_ACTIVATION_BLOCKED"
    assert result["blocked_count"] == 1
    assert result["paper_execution_allowed"] is False
    assert result["live_execution_allowed"] is False
    assert result["persisted"] is False
    assert result["capital_reserved"] is False
    assert result["bundle_consumed"] is False
    assert result["position_created"] is False
    assert result["lifecycle_started"] is False
    assert result["order_created"] is False
    assert result["order_submitted"] is False


def test_all_ready_controls_only_produce_ready_disabled_state():
    controls = PaperActivationControls(
        paper_activation_enabled=True,
        live_activation_enabled=False,
        durable_idempotency_ready=True,
        atomic_reservation_ready=True,
        lifecycle_journal_ready=True,
        paper_adapter_ready=True,
        position_monitor_ready=True,
        exit_controller_ready=True,
        restart_recovery_ready=True,
        rollback_ready=True,
        legacy_fallback_ready=True,
    )

    result = build_controlled_paper_activation(_router(), controls=controls)
    row = result["rows"][0]

    assert result["outcome"] == "PAPER_ACTIVATION_READY_DISABLED"
    assert row["strategy_id"] == "RED_BAR"
    assert row["route_id"] == "ROUTE-1"
    assert row["paper_execution_allowed"] is False
    assert row["live_execution_allowed"] is False
    assert row["idempotency_persisted"] is False
    assert row["capital_reserved"] is False
    assert row["bundle_consumed"] is False
    assert row["position_created"] is False
    assert row["lifecycle_started"] is False
    assert row["order_created"] is False
    assert row["order_submitted"] is False


def test_live_enablement_blocks_activation_readiness():
    controls = PaperActivationControls(
        paper_activation_enabled=True,
        live_activation_enabled=True,
        durable_idempotency_ready=True,
        atomic_reservation_ready=True,
        lifecycle_journal_ready=True,
        paper_adapter_ready=True,
        position_monitor_ready=True,
        exit_controller_ready=True,
        restart_recovery_ready=True,
        rollback_ready=True,
        legacy_fallback_ready=True,
    )

    result = build_controlled_paper_activation(_router(), controls=controls)

    assert result["outcome"] == "PAPER_ACTIVATION_BLOCKED"
    assert "LIVE_ACTIVATION_HARD_DISABLED" in result["rows"][0]["activation_reason"]
    assert result["live_execution_allowed"] is False


def test_unrouted_candidate_cannot_be_activated():
    router = _router()
    router["rows"][0]["route_outcome"] = "NOT_ROUTED"

    result = build_controlled_paper_activation(router)

    assert result["outcome"] == "PAPER_ACTIVATION_BLOCKED"
    assert "SHADOW_ROUTE_NOT_READY" in result["rows"][0]["activation_reason"]
