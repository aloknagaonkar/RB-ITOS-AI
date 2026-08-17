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
    enable_environment: str


POLICIES: Mapping[str, StrategyGatePolicy] = {
    "Red Bar Strategy": StrategyGatePolicy(
        page="Red Bar Strategy",
        strategy_id="RED_BAR",
        strategy_owner="Red Bar",
        builder_name="build_red_bar_bundle_resolution",
        enable_environment="RB_ENABLE_RED_BAR_STRATEGY",
    ),
    "Directional Regime Intelligence": StrategyGatePolicy(
        page="Directional Regime Intelligence",
        strategy_id="DIRECTIONAL_REGIME_INTELLIGENCE",
        strategy_owner="Directional Regime Intelligence",
        builder_name="build_dri_bundle_resolution",
        enable_environment="RB_ENABLE_DRI_STRATEGY",
    ),
    "RSI Extreme Reversal": StrategyGatePolicy(
        page="RSI Extreme Reversal",
        strategy_id="RSI_EXTREME_REVERSAL",
        strategy_owner="RSI Extreme Reversal",
        builder_name="build_rsi_signal_resolution",
        enable_environment="RB_ENABLE_RSI_STRATEGY",
    ),
}

_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "enabled"})
_NOT_CREATED = frozenset({"", "not created", "unavailable", "none"})


def _enabled(environment_name: str, environment: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environment is None else environment
    return str(values.get(environment_name, "")).strip().lower() in _TRUE_VALUES


def build_execution_source_gate(
    resolution: Mapping[str, object] | None,
    policy: StrategyGatePolicy,
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Evaluate a strategy-owned, read-only handoff gate.

    The gate does not create candidates, persist decisions, consume bundles,
    start cooldowns, submit orders, or alter production strategy controls.
    It only explains whether the strategy's own Section 3 result would be
    eligible to continue to strategy-owned contract selection.
    """
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

    eligible = all(
        (detected, bundle_exists, bundle_ready, side_ready, execution_enabled)
    )
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
        "execution_enabled": execution_enabled,
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


def render_execution_source_gate(gate: Mapping[str, object]) -> None:
    st.markdown("### 4. Execution-Source Gate")
    st.caption(
        "Read-only strategy-owned handoff. This section does not persist a gate "
        "decision, create a candidate, consume a bundle, start cooldown, or submit an order."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Strategy source", str(gate["strategy_owner"]))
    c2.metric("Execution enabled", "YES" if gate["execution_enabled"] else "NO")
    c3.metric("Source eligible", "YES" if gate["eligible"] else "NO")
    c4.metric("Forwarded", "NO — READ ONLY")

    st.write(f"**Signal ID:** {gate['signal_id']}")
    st.write(f"**Bundle ID:** {gate['bundle_id']}")
    st.write(f"**Requested intent:** {gate['normalized_intent']}")
    st.write(f"**Gate outcome:** {gate['final_outcome']}")
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


def build_execution_source_gate_page_wrapper(
    module: ModuleType,
    page: str,
):
    """Append Section 4 after the page's existing Section 3 resolution."""
    policy = POLICIES[page]
    original_builder = getattr(module, policy.builder_name)
    original_render = module.render_page
    captured: dict[str, object] = {}

    @wraps(original_builder)
    def capture_resolution(*args, **kwargs):
        resolution = original_builder(*args, **kwargs)
        captured["resolution"] = resolution
        return resolution

    @wraps(original_render)
    def wrapped_render(*args, **kwargs):
        captured.clear()
        result = original_render(*args, **kwargs)
        gate = build_execution_source_gate(
            captured.get("resolution") if isinstance(captured.get("resolution"), Mapping) else None,
            policy,
        )
        render_execution_source_gate(gate)
        return result

    setattr(module, policy.builder_name, capture_resolution)
    return wrapped_render
