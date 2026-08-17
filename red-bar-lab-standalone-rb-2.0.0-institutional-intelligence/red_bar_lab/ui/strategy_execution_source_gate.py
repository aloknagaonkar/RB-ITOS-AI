from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import os
from types import ModuleType
from typing import Mapping

import streamlit as st


@dataclass(frozen=True)
class StrategyGatePolicy:
    page: str
    strategy_id: str
    strategy_owner: str
    builder_name: str
    setup_builder_name: str
    enable_environment: str


POLICIES: Mapping[str, StrategyGatePolicy] = {
    "Red Bar Strategy": StrategyGatePolicy(
        page="Red Bar Strategy",
        strategy_id="RED_BAR",
        strategy_owner="Red Bar",
        builder_name="build_red_bar_bundle_resolution",
        setup_builder_name="build_red_bar_owned_setup_state",
        enable_environment="RB_ENABLE_RED_BAR_STRATEGY",
    ),
    "Directional Regime Intelligence": StrategyGatePolicy(
        page="Directional Regime Intelligence",
        strategy_id="DIRECTIONAL_REGIME_INTELLIGENCE",
        strategy_owner="Directional Regime Intelligence",
        builder_name="build_dri_bundle_resolution",
        setup_builder_name="build_dri_setup_state",
        enable_environment="RB_ENABLE_DRI_STRATEGY",
    ),
    "RSI Extreme Reversal": StrategyGatePolicy(
        page="RSI Extreme Reversal",
        strategy_id="RSI_EXTREME_REVERSAL",
        strategy_owner="RSI Extreme Reversal",
        builder_name="build_rsi_signal_resolution",
        setup_builder_name="build_rsi_setup_state",
        enable_environment="RB_ENABLE_RSI_STRATEGY",
    ),
}

_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "enabled"})
_NOT_CREATED = frozenset({"", "not created", "unavailable", "none"})


def _enabled(environment_name: str, environment: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environment is None else environment
    return str(values.get(environment_name, "")).strip().lower() in _TRUE_VALUES


def _row_value(rows, label: str):
    target = label.strip().lower()
    for row in rows or []:
        item = dict(row)
        name = str(item.get("field") or item.get("check") or "").strip().lower()
        if name == target:
            return item.get("value") or item.get("detail")
    return None


def _latest_observed(rows):
    values = [
        str(dict(row).get("observed"))
        for row in (rows or [])
        if dict(row).get("observed") not in (None, "", "Not stored", "Not detected")
    ]
    return max(values) if values else None


def build_execution_source_gate(
    resolution: Mapping[str, object] | None,
    policy: StrategyGatePolicy,
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Evaluate a strategy-owned, read-only handoff gate."""
    result = dict(resolution or {})
    signal_state = str(result.get("signal_state") or "NOT AVAILABLE")
    bundle_state = str(result.get("bundle_state") or "NOT CREATED")
    section3_outcome = str(result.get("final_outcome") or "OBSERVE").upper()
    signal_id = str(result.get("signal_id") or "Not created")
    bundle_id = str(result.get("bundle_id") or "Not created")
    normalized_intent = str(result.get("normalized_intent") or "OBSERVE / WAIT")

    detected = signal_state.upper() not in {"NOT AVAILABLE", "NOT DETECTED", "UNAVAILABLE"}
    bundle_exists = bundle_id.strip().lower() not in _NOT_CREATED
    bundle_ready = section3_outcome == "FORWARD"
    execution_enabled = _enabled(policy.enable_environment, environment)
    side_ready = normalized_intent.upper() in {"BUY CE", "BUY PE"}

    checks = [
        {
            "check": "Strategy-owned signal detected",
            "status": "PASS" if detected else "BLOCK",
            "detail": signal_state,
        },
        {
            "check": "Strategy-owned bundle exists",
            "status": "PASS" if bundle_exists else "BLOCK",
            "detail": bundle_id,
        },
        {
            "check": "Section 3 lifecycle permits forward",
            "status": "PASS" if bundle_ready else "BLOCK",
            "detail": f"bundle={bundle_state}; outcome={section3_outcome}",
        },
        {
            "check": "Requested CE/PE side is explicit",
            "status": "PASS" if side_ready else "BLOCK",
            "detail": normalized_intent,
        },
        {
            "check": "Strategy enabled for execution",
            "status": "PASS" if execution_enabled else "BLOCK",
            "detail": f"{policy.enable_environment}={'enabled' if execution_enabled else 'disabled or unset'}",
        },
    ]

    eligible = all((detected, bundle_exists, bundle_ready, side_ready, execution_enabled))
    blockers = [row["detail"] for row in checks if row["status"] == "BLOCK"]
    final_outcome = "FORWARD_TO_CONTRACT_SELECTION" if eligible else "BLOCKED"

    return {
        "strategy_id": policy.strategy_id,
        "strategy_owner": policy.strategy_owner,
        "signal_id": signal_id,
        "bundle_id": bundle_id,
        "normalized_intent": normalized_intent,
        "signal_state": signal_state,
        "bundle_state": bundle_state,
        "section3_outcome": section3_outcome,
        "execution_enabled": execution_enabled,
        "lifecycle_ready": bundle_ready,
        "eligible": eligible,
        "forwarded": False,
        "final_outcome": final_outcome,
        "blocking_reason": "; ".join(blockers) if blockers else "None",
        "checks": checks,
        "authority": "READ_ONLY_OBSERVABILITY",
        "next_step": (
            "Evaluate strategy-owned CE/PE contracts in read-only shadow mode."
            if eligible
            else "Keep detection and diagnostics active; do not start contract selection."
        ),
    }


def build_cross_section_readiness(
    gate: Mapping[str, object],
    resolution: Mapping[str, object] | None,
    setup: Mapping[str, object] | None = None,
    option_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result = dict(resolution or {})
    setup_result = dict(setup or {})
    option_result = dict(option_context or {})
    bundle_state = str(gate.get("bundle_state") or "NOT CREATED").upper()

    if str(gate.get("signal_state") or "").upper() in {
        "NOT AVAILABLE", "NOT DETECTED", "UNAVAILABLE"
    }:
        overall = "NO_SETUP"
    elif bundle_state == "STALE":
        overall = "STALE"
    elif bundle_state == "CONSUMED":
        overall = "CONSUMED"
    elif bool(gate.get("eligible")):
        overall = "READY_FOR_CONTRACT_SELECTION"
    else:
        overall = "BLOCKED"

    contract_outcome = (
        "ELIGIBLE_READ_ONLY" if gate.get("eligible") else "NOT_ELIGIBLE"
    )
    setup_status = str(
        setup_result.get("status")
        or setup_result.get("signal_state")
        or gate.get("signal_state")
        or "Unavailable"
    )
    bundle_rows = result.get("bundle_rows") or []
    signal_rows = result.get("raw_rows") or result.get("signal_rows") or []
    bundle_created = (
        _row_value(bundle_rows, "Created at")
        or result.get("refreshed_at")
    )
    bundle_fresh_until = _row_value(bundle_rows, "Fresh until")
    signal_timestamp = (
        _row_value(signal_rows, "Detection timestamp")
        or _row_value(signal_rows, "Confirmation timestamp")
        or _row_value(signal_rows, "Cross timestamp")
        or result.get("refreshed_at")
    )
    option_timestamp = option_result.get("latest_timestamp")
    option_status = option_result.get("freshness") or option_result.get("status") or "Unavailable"
    setup_timestamp = _latest_observed(setup_result.get("rows") or [])

    evidence_rows = [
        {
            "evidence": "Option snapshot",
            "timestamp": str(option_timestamp or "Unavailable"),
            "status": str(option_status),
        },
        {
            "evidence": "Strategy setup",
            "timestamp": str(setup_timestamp or "Unavailable"),
            "status": setup_status,
        },
        {
            "evidence": "Strategy signal",
            "timestamp": str(signal_timestamp or "Unavailable"),
            "status": str(gate.get("signal_state") or "Unavailable"),
        },
        {
            "evidence": "Bundle created",
            "timestamp": str(bundle_created or "Unavailable"),
            "status": bundle_state,
        },
        {
            "evidence": "Bundle fresh until",
            "timestamp": str(bundle_fresh_until or "Unavailable"),
            "status": "EXPIRED" if bundle_state == "STALE" else "ACTIVE/UNKNOWN",
        },
    ]

    downstream = (
        "PASS — contract selection may be evaluated read-only"
        if gate.get("eligible")
        else f"BLOCKED — {gate.get('blocking_reason')}"
    )
    waiting_for = (
        "Read-only strategy-owned CE/PE contract selection"
        if gate.get("eligible")
        else "A new confirmed, fresh strategy-owned bundle"
    )

    return {
        "overall_status": overall,
        "detection_status": setup_status,
        "lifecycle_status": f"bundle={bundle_state}; outcome={gate.get('section3_outcome')}",
        "downstream_status": downstream,
        "contract_selection_outcome": contract_outcome,
        "waiting_for": waiting_for,
        "evidence_rows": evidence_rows,
    }


def render_execution_source_gate(gate: Mapping[str, object]) -> None:
    st.markdown("### 4. Execution-Source Gate")
    st.caption(
        "Read-only strategy-owned handoff. This section does not persist a gate "
        "decision, create a candidate, consume a bundle, start cooldown, or submit an order."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Strategy source", str(gate["strategy_owner"]))
    c2.metric("Strategy control", "ENABLED" if gate["execution_enabled"] else "DISABLED")
    c3.metric("Lifecycle gate", "PASS" if gate["lifecycle_ready"] else "BLOCKED")
    c4.metric("Source eligible", "YES" if gate["eligible"] else "NO")

    st.write(f"**Signal ID:** {gate['signal_id']}")
    st.write(f"**Bundle ID:** {gate['bundle_id']}")
    st.write(f"**Requested intent:** {gate['normalized_intent']}")
    st.write(f"**Lifecycle state:** bundle={gate['bundle_state']}; outcome={gate['section3_outcome']}")
    st.write(f"**Gate outcome:** {gate['final_outcome']}")
    st.write(f"**Forwarded:** NO — READ ONLY")
    st.write(f"**Blocking reason:** {gate['blocking_reason']}")
    st.write(f"**Next architectural step:** {gate['next_step']}")

    with st.expander("View execution-source checks"):
        st.dataframe(list(gate["checks"]), width="stretch", hide_index=True)

    if gate["eligible"]:
        st.success(
            "The strategy source is eligible for read-only strategy-owned contract selection. "
            "No handoff has been persisted or executed."
        )
    else:
        st.info(
            "Detection and diagnostics remain active, but this strategy source is not "
            "eligible to continue to contract selection."
        )


def render_cross_section_readiness(summary: Mapping[str, object]) -> None:
    st.markdown("#### Cross-Section Readiness Summary")
    st.caption(
        "Separates strategy detection from downstream lifecycle eligibility and shows "
        "the evidence timestamps that must remain aligned before contract selection."
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Current strategy status", str(summary["overall_status"]))
    c2.metric("Detection layer", str(summary["detection_status"]))
    c3.metric("Contract selection", str(summary["contract_selection_outcome"]))

    st.write(f"**Detection-layer blocker:** None when detection is confirmed; this does not override lifecycle checks.")
    st.write(f"**Downstream lifecycle status:** {summary['downstream_status']}")
    st.write(f"**Waiting for:** {summary['waiting_for']}")

    with st.expander("View evidence timestamp alignment"):
        st.dataframe(list(summary["evidence_rows"]), width="stretch", hide_index=True)


def build_execution_source_gate_page_wrapper(module: ModuleType, page: str):
    """Append Section 4 and cross-section readiness after Section 3."""
    policy = POLICIES[page]
    original_builder = getattr(module, policy.builder_name)
    original_render = module.render_page
    original_setup_builder = getattr(module, policy.setup_builder_name, None)
    original_option_builder = getattr(module, "build_option_behaviour_snapshot", None)
    captured: dict[str, object] = {}

    @wraps(original_builder)
    def capture_resolution(*args, **kwargs):
        resolution = original_builder(*args, **kwargs)
        captured["resolution"] = resolution
        return resolution

    if callable(original_setup_builder):
        @wraps(original_setup_builder)
        def capture_setup(*args, **kwargs):
            setup = original_setup_builder(*args, **kwargs)
            captured["setup"] = setup
            return setup

        setattr(module, policy.setup_builder_name, capture_setup)

    if callable(original_option_builder):
        @wraps(original_option_builder)
        def capture_option_context(*args, **kwargs):
            option_context = original_option_builder(*args, **kwargs)
            captured["option_context"] = option_context
            return option_context

        setattr(module, "build_option_behaviour_snapshot", capture_option_context)

    @wraps(original_render)
    def wrapped_render(*args, **kwargs):
        captured.clear()
        result = original_render(*args, **kwargs)
        resolution = captured.get("resolution") if isinstance(captured.get("resolution"), Mapping) else None
        setup = captured.get("setup") if isinstance(captured.get("setup"), Mapping) else None
        option_context = captured.get("option_context") if isinstance(captured.get("option_context"), Mapping) else None
        gate = build_execution_source_gate(resolution, policy)
        render_execution_source_gate(gate)
        summary = build_cross_section_readiness(gate, resolution, setup, option_context)
        render_cross_section_readiness(summary)
        return result

    setattr(module, policy.builder_name, capture_resolution)
    return wrapped_render
