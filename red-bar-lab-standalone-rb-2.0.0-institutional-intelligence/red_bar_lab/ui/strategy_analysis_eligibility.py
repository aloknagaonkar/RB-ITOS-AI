from __future__ import annotations

_INSTALLED = False


def _enrich_gate(gate):
    result = dict(gate)
    signal = str(result.get("signal_state") or "").upper()
    bundle = str(result.get("bundle_id") or "").strip().lower()
    detected = signal not in {"", "NOT AVAILABLE", "NOT DETECTED", "UNAVAILABLE"}
    bundle_exists = bundle not in {"", "not created", "unavailable", "none"}
    lifecycle_ready = bool(result.get("lifecycle_ready"))
    side_ready = str(result.get("normalized_intent") or "").upper() in {"BUY CE", "BUY PE"}
    analysis_eligible = all((detected, bundle_exists, lifecycle_ready, side_ready))
    execution_enabled = bool(result.get("execution_enabled"))
    execution_eligible = analysis_eligible and execution_enabled

    analysis_reasons = []
    if not detected:
        analysis_reasons.append(str(result.get("signal_state") or "Signal unavailable"))
    if not bundle_exists:
        analysis_reasons.append(str(result.get("bundle_id") or "Bundle unavailable"))
    if not lifecycle_ready:
        analysis_reasons.append(
            f"bundle={result.get('bundle_state')}; outcome={result.get('section3_outcome')}"
        )
    if not side_ready:
        analysis_reasons.append(str(result.get("normalized_intent") or "Intent unavailable"))
    execution_reasons = list(analysis_reasons)
    if not execution_enabled:
        execution_reasons.append("Strategy execution control is disabled or unset")

    checks = [dict(row) for row in (result.get("checks") or [])]
    for row in checks:
        execution_only = str(row.get("check")) == "Strategy enabled for execution"
        row["scope"] = "EXECUTION_ONLY" if execution_only else "ANALYSIS_AND_EXECUTION"
        if execution_only and not execution_enabled:
            row["status"] = "BLOCK_EXECUTION_ONLY"

    result.update(
        analysis_eligible=analysis_eligible,
        execution_eligible=execution_eligible,
        eligible=execution_eligible,
        analysis_mode="READ_ONLY" if analysis_eligible else "BLOCKED",
        execution_mode="ENABLED" if execution_enabled else "DISABLED",
        policy_action=(
            "EXECUTION_ELIGIBLE_READ_ONLY_GATE"
            if execution_eligible
            else "OBSERVE_ONLY" if analysis_eligible else "BLOCKED"
        ),
        final_outcome=(
            "FORWARD_TO_CONTRACT_SELECTION"
            if execution_eligible
            else "OBSERVE_ONLY_CONTRACT_SELECTION" if analysis_eligible else "BLOCKED"
        ),
        analysis_blocking_reason="; ".join(analysis_reasons) if analysis_reasons else "None",
        execution_blocking_reason="; ".join(execution_reasons) if execution_reasons else "None",
        blocking_reason="; ".join(execution_reasons) if execution_reasons else "None",
        checks=checks,
    )
    return result


def install_analysis_eligibility_separation():
    global _INSTALLED
    if _INSTALLED:
        return

    import red_bar_lab.ui.strategy_contract_readiness as readiness_module
    import red_bar_lab.ui.strategy_execution_source_gate as gate_module

    original_gate = gate_module.build_execution_source_gate
    original_summary = gate_module.build_cross_section_readiness
    original_readiness = readiness_module.build_contract_data_readiness

    def build_gate(*args, **kwargs):
        return _enrich_gate(original_gate(*args, **kwargs))

    def build_summary(gate, *args, **kwargs):
        result = dict(original_summary(gate, *args, **kwargs))
        analysis = bool(gate.get("analysis_eligible"))
        execution = bool(gate.get("execution_eligible"))
        result["analysis_eligibility"] = "ELIGIBLE" if analysis else "BLOCKED"
        result["execution_eligibility"] = "ELIGIBLE" if execution else "BLOCKED"
        if analysis and not execution:
            result["overall_status"] = "OBSERVE_ONLY_CONTRACT_SELECTION"
            result["contract_selection_outcome"] = "ELIGIBLE_OBSERVE_ONLY"
            result["downstream_status"] = (
                "OBSERVE_ONLY — contract selection remains visible; execution authority is blocked"
            )
            result["waiting_for"] = "Contract analysis now; execution enablement only before execution"
        return result

    def build_readiness(*, gate, **kwargs):
        analysis = bool(gate.get("analysis_eligible", gate.get("eligible")))
        analysis_gate = dict(gate)
        analysis_gate["eligible"] = analysis
        result = original_readiness(gate=analysis_gate, **kwargs)
        result["analysis_mode"] = "READ_ONLY" if analysis else "BLOCKED"
        result["execution_enabled"] = bool(gate.get("execution_enabled"))
        result["execution_eligible"] = bool(gate.get("execution_eligible", gate.get("eligible")))
        result["policy_action"] = str(gate.get("policy_action") or "BLOCKED")
        return result

    gate_module.build_execution_source_gate = build_gate
    gate_module.build_cross_section_readiness = build_summary
    readiness_module.build_contract_data_readiness = build_readiness
    _INSTALLED = True
