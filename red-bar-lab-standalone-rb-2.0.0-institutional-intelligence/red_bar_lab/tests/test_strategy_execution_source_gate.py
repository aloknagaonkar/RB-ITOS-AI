from __future__ import annotations

from types import ModuleType

from red_bar_lab.ui.strategy_execution_source_gate import (
    POLICIES,
    build_execution_source_gate,
    build_execution_source_gate_page_wrapper,
)


def _resolution(**overrides):
    value = {
        "signal_state": "CONFIRMED",
        "normalized_intent": "BUY CE",
        "bundle_state": "FRESH",
        "final_outcome": "FORWARD",
        "signal_id": "SIG-1",
        "bundle_id": "BUNDLE-1",
    }
    value.update(overrides)
    return value


def test_each_strategy_has_an_independent_enable_flag():
    assert POLICIES["Red Bar Strategy"].enable_environment == "RB_ENABLE_RED_BAR_STRATEGY"
    assert POLICIES["Directional Regime Intelligence"].enable_environment == "RB_ENABLE_DRI_STRATEGY"
    assert POLICIES["RSI Extreme Reversal"].enable_environment == "RB_ENABLE_RSI_STRATEGY"
    assert len({policy.enable_environment for policy in POLICIES.values()}) == 3


def test_ready_red_bar_bundle_is_eligible_only_when_red_bar_is_enabled():
    policy = POLICIES["Red Bar Strategy"]

    disabled = build_execution_source_gate(_resolution(), policy, environment={})
    enabled = build_execution_source_gate(
        _resolution(),
        policy,
        environment={"RB_ENABLE_RED_BAR_STRATEGY": "true"},
    )

    assert disabled["eligible"] is False
    assert disabled["final_outcome"] == "BLOCKED"
    assert "disabled or unset" in disabled["blocking_reason"]
    assert enabled["eligible"] is True
    assert enabled["final_outcome"] == "FORWARD_TO_CONTRACT_SELECTION"
    assert enabled["forwarded"] is False
    assert enabled["authority"] == "READ_ONLY_OBSERVABILITY"


def test_enabling_one_strategy_does_not_enable_another():
    environment = {"RB_ENABLE_RSI_STRATEGY": "1"}
    rsi = build_execution_source_gate(
        _resolution(bundle_id="RSI-BUNDLE"),
        POLICIES["RSI Extreme Reversal"],
        environment=environment,
    )
    dri = build_execution_source_gate(
        _resolution(bundle_id="DRI-BUNDLE"),
        POLICIES["Directional Regime Intelligence"],
        environment=environment,
    )

    assert rsi["execution_enabled"] is True
    assert rsi["eligible"] is True
    assert dri["execution_enabled"] is False
    assert dri["eligible"] is False


def test_stale_consumed_or_missing_bundle_never_passes_gate():
    policy = POLICIES["RSI Extreme Reversal"]
    environment = {"RB_ENABLE_RSI_STRATEGY": "yes"}

    stale = build_execution_source_gate(
        _resolution(bundle_state="STALE", final_outcome="HOLD"),
        policy,
        environment=environment,
    )
    consumed = build_execution_source_gate(
        _resolution(bundle_state="CONSUMED", final_outcome="HOLD"),
        policy,
        environment=environment,
    )
    missing = build_execution_source_gate(
        _resolution(bundle_id="Not created", final_outcome="OBSERVE"),
        policy,
        environment=environment,
    )

    assert stale["eligible"] is False
    assert consumed["eligible"] is False
    assert missing["eligible"] is False


def test_gate_requires_explicit_ce_or_pe_intent():
    gate = build_execution_source_gate(
        _resolution(normalized_intent="OBSERVE / WAIT"),
        POLICIES["Directional Regime Intelligence"],
        environment={"RB_ENABLE_DRI_STRATEGY": "on"},
    )

    assert gate["eligible"] is False
    assert "OBSERVE / WAIT" in gate["blocking_reason"]


def test_page_wrapper_captures_only_its_strategy_resolution(monkeypatch):
    module = ModuleType("red_bar_test_page")
    rendered = []

    def build_red_bar_bundle_resolution(*args, **kwargs):
        return _resolution(bundle_id="RB-BUNDLE")

    def render_page(*args, **kwargs):
        module.build_red_bar_bundle_resolution()
        return "rendered"

    module.build_red_bar_bundle_resolution = build_red_bar_bundle_resolution
    module.render_page = render_page

    captured_gates = []
    monkeypatch.setattr(
        "red_bar_lab.ui.strategy_execution_source_gate.render_execution_source_gate",
        lambda gate: captured_gates.append(gate),
    )

    wrapped = build_execution_source_gate_page_wrapper(module, "Red Bar Strategy")
    assert wrapped() == "rendered"
    assert captured_gates[0]["strategy_id"] == "RED_BAR"
    assert captured_gates[0]["bundle_id"] == "RB-BUNDLE"
    assert captured_gates[0]["forwarded"] is False


def test_gate_module_contains_no_write_or_execution_action():
    import red_bar_lab.ui.strategy_execution_source_gate as gate_module

    source = open(gate_module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "database." not in source
