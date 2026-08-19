from __future__ import annotations

from copy import deepcopy

from red_bar_lab.ui.unified_shadow_execution_router import (
    UNIFIED_SHADOW_ROUTER_VERSION,
    build_unified_shadow_routes,
)


def _evidence(**overrides):
    row = {
        "strategy_id": "RED_BAR",
        "signal_id": "RB-1",
        "bundle_id": "BUNDLE-1",
        "candidate_id": "CANDIDATE-1",
        "snapshot_timestamp": "2026-08-18T09:20:00+05:30",
        "evaluation_timestamp": "2026-08-18T09:20:01+05:30",
        "new_chain_decision": "ADMIT_READ_ONLY",
    }
    row.update(overrides)
    return row


def test_router_routes_admitted_candidate_without_side_effects():
    evidence = [_evidence()]
    original = deepcopy(evidence)

    result = build_unified_shadow_routes(evidence)

    assert evidence == original
    assert result["outcome"] == "ROUTED_SHADOW_ONLY"
    assert result["routed_count"] == 1
    row = result["rows"][0]
    assert row["strategy_id"] == "RED_BAR"
    assert row["route_outcome"] == "ROUTED_SHADOW_ONLY"
    assert row["strategy_owner_preserved"] is True
    assert row["bundle_owner_preserved"] is True
    assert row["effective_mode"] == "SHADOW"
    assert row["execution_enabled"] is False
    assert row["paper_adapter_attached"] is False
    assert row["live_adapter_attached"] is False
    assert row["persisted"] is False
    assert row["queue_mutated"] is False
    assert row["capital_reserved"] is False
    assert row["bundle_consumed"] is False
    assert row["position_created"] is False
    assert row["order_created"] is False
    assert row["order_submitted"] is False
    assert row["router_version"] == UNIFIED_SHADOW_ROUTER_VERSION


def test_router_accepts_direct_section_9e_shadow_ready_row():
    result = build_unified_shadow_routes(
        [
            _evidence(
                new_chain_decision=None,
                shadow_handoff_ready=True,
                shadow_rehearsal_outcome="SHADOW_HANDOFF_READY_DISABLED",
            )
        ]
    )

    assert result["routed_count"] == 1
    assert result["rows"][0]["route_outcome"] == "ROUTED_SHADOW_ONLY"


def test_router_id_is_deterministic():
    first = build_unified_shadow_routes([_evidence()])["rows"][0]
    second = build_unified_shadow_routes([_evidence()])["rows"][0]

    assert first["route_id"] == second["route_id"]
    assert first["idempotency_key"] == first["route_id"]


def test_router_rejects_non_admitted_evidence():
    result = build_unified_shadow_routes(
        [_evidence(new_chain_decision="REJECT_OR_WAIT_READ_ONLY")]
    )

    row = result["rows"][0]
    assert row["route_outcome"] == "NOT_ROUTED"
    assert "NEW_CHAIN_NOT_ADMITTED" in row["route_reason"]


def test_router_rejects_incomplete_identity():
    result = build_unified_shadow_routes([_evidence(bundle_id="")])

    row = result["rows"][0]
    assert row["route_outcome"] == "NOT_ROUTED"
    assert "INCOMPLETE_EXECUTION_IDENTITY" in row["route_reason"]


def test_router_rejects_retired_strategy_evidence_but_preserves_identity():
    result = build_unified_shadow_routes(
        [
            _evidence(strategy_id="RED_BAR", signal_id="RB-1"),
            _evidence(
                strategy_id="DIRECTIONAL_REGIME",
                signal_id="DRI-1",
                bundle_id="DRI-BUNDLE-1",
                candidate_id="DRI-CANDIDATE-1",
            ),
            _evidence(
                strategy_id="RSI_EXTREME_REVERSAL",
                signal_id="RSI-1",
                bundle_id="RSI-BUNDLE-1",
                candidate_id="RSI-CANDIDATE-1",
            ),
        ]
    )

    assert result["routed_count"] == 1
    assert result["not_routed_count"] == 2
    assert {row["strategy_id"] for row in result["rows"]} == {
        "RED_BAR",
        "DIRECTIONAL_REGIME",
        "RSI_EXTREME_REVERSAL",
    }

    rows_by_strategy = {row["strategy_id"]: row for row in result["rows"]}
    assert rows_by_strategy["RED_BAR"]["route_outcome"] == "ROUTED_SHADOW_ONLY"
    for strategy_id in ("DIRECTIONAL_REGIME", "RSI_EXTREME_REVERSAL"):
        row = rows_by_strategy[strategy_id]
        assert row["route_outcome"] == "NOT_ROUTED"
        assert "UNSUPPORTED_STRATEGY" in row["route_reason"]
        assert row["strategy_owner_preserved"] is True
        assert row["bundle_owner_preserved"] is True
        assert row["execution_enabled"] is False
        assert row["order_submitted"] is False


def test_duplicate_route_identity_is_not_routed_twice_in_same_batch():
    result = build_unified_shadow_routes([_evidence(), _evidence()])

    assert result["routed_count"] == 1
    assert result["not_routed_count"] == 1
    assert "DUPLICATE_ROUTE_ID" in result["rows"][1]["route_reason"]
