from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Callable

from red_bar_lab.services.red_bar_v2_promotion_readiness import (
    PromotionEvidence,
    PromotionStage,
    evaluate_promotion_readiness,
)


def _default_evidence() -> PromotionEvidence:
    return PromotionEvidence(
        unit_tests_passed=84,
        unit_tests_failed=0,
        feature_flag_default_off=True,
        legacy_exit_path_unchanged=True,
        rollback_plan_available=True,
        evidence_reference="RED_BAR_V2_PHASE_1_11_BASELINE",
    )


def _stage_message(stage: PromotionStage) -> tuple[str, str]:
    if stage == PromotionStage.PAPER_READY:
        return (
            "success",
            "PAPER_READY: controlled paper execution may be enabled separately by the named operator. Live broker execution is not authorized.",
        )
    if stage == PromotionStage.SHADOW_READY:
        return (
            "info",
            "SHADOW_READY: run observation-only shadow sessions. Paper execution must remain disabled.",
        )
    return (
        "warning",
        "NOT_READY: keep Red Bar V2 disabled while the blocking evidence is collected.",
    )


def _render_gate_table(st: Any, report: Any) -> None:
    rows = []
    for gate in report.gates:
        rows.append(
            {
                "Gate": gate.code,
                "Required for": gate.required_for.value,
                "Status": "PASS" if gate.passed else "BLOCKED",
                "Observed": gate.observed,
                "Required": gate.required,
                "Reason": gate.reason,
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)


def render_red_bar_v2_promotion_panel(st: Any) -> None:
    st.markdown("---")
    st.markdown("### Red Bar V2 — Shadow Evidence & Promotion Readiness")
    st.caption(
        "Fail-closed readiness view for historical replay, architecture parity, "
        "shadow observation and controlled paper promotion. This panel never "
        "enables execution or changes feature flags."
    )

    defaults = _default_evidence()
    with st.expander("Promotion evidence", expanded=True):
        test_col, replay_col, parity_col = st.columns(3)
        with test_col:
            unit_tests_passed = st.number_input(
                "Unit tests passed",
                min_value=0,
                value=defaults.unit_tests_passed,
                step=1,
                key="rbv2_unit_tests_passed",
            )
            unit_tests_failed = st.number_input(
                "Unit tests failed",
                min_value=0,
                value=defaults.unit_tests_failed,
                step=1,
                key="rbv2_unit_tests_failed",
            )
        with replay_col:
            replay_sessions = st.number_input(
                "Historical replay sessions",
                min_value=0,
                value=0,
                step=1,
                key="rbv2_replay_sessions",
            )
            replay_candidates = st.number_input(
                "Historical replay candidates",
                min_value=0,
                value=0,
                step=1,
                key="rbv2_replay_candidates",
            )
            replay_errors = st.number_input(
                "Historical replay errors",
                min_value=0,
                value=0,
                step=1,
                key="rbv2_replay_errors",
            )
        with parity_col:
            parity_comparisons = st.number_input(
                "Parity comparisons",
                min_value=0,
                value=0,
                step=1,
                key="rbv2_parity_comparisons",
            )
            parity_mismatches = st.number_input(
                "Parity mismatches",
                min_value=0,
                value=0,
                step=1,
                key="rbv2_parity_mismatches",
            )

        shadow_col, safety_col, approval_col = st.columns(3)
        with shadow_col:
            shadow_sessions = st.number_input(
                "Shadow sessions",
                min_value=0,
                value=0,
                step=1,
                key="rbv2_shadow_sessions",
            )
            shadow_decisions = st.number_input(
                "Shadow decisions",
                min_value=0,
                value=0,
                step=1,
                key="rbv2_shadow_decisions",
            )
            shadow_errors = st.number_input(
                "Shadow runtime errors",
                min_value=0,
                value=0,
                step=1,
                key="rbv2_shadow_errors",
            )
        with safety_col:
            duplicate_entries = st.number_input(
                "Duplicate entries",
                min_value=0,
                value=0,
                step=1,
                key="rbv2_duplicate_entries",
            )
            lifecycle_conflicts = st.number_input(
                "Unresolved lifecycle conflicts",
                min_value=0,
                value=0,
                step=1,
                key="rbv2_lifecycle_conflicts",
            )
            storage_audit_available = st.checkbox(
                "Storage/audit evidence available",
                value=False,
                key="rbv2_storage_audit_available",
            )
        with approval_col:
            rollback_plan_available = st.checkbox(
                "Rollback plan available",
                value=defaults.rollback_plan_available,
                key="rbv2_rollback_plan_available",
            )
            operator_approval = st.checkbox(
                "Operator approves controlled paper promotion",
                value=False,
                key="rbv2_operator_approval",
            )
            operator_name = st.text_input(
                "Operator name",
                value="",
                key="rbv2_operator_name",
            )

        evidence_reference = st.text_input(
            "Evidence reference",
            value=defaults.evidence_reference or "",
            key="rbv2_evidence_reference",
        )

    evidence = PromotionEvidence(
        unit_tests_passed=int(unit_tests_passed),
        unit_tests_failed=int(unit_tests_failed),
        replay_sessions=int(replay_sessions),
        replay_candidates=int(replay_candidates),
        replay_errors=int(replay_errors),
        shadow_sessions=int(shadow_sessions),
        shadow_decisions=int(shadow_decisions),
        shadow_errors=int(shadow_errors),
        parity_comparisons=int(parity_comparisons),
        parity_mismatches=int(parity_mismatches),
        duplicate_entries=int(duplicate_entries),
        unresolved_lifecycle_conflicts=int(lifecycle_conflicts),
        storage_audit_available=bool(storage_audit_available),
        rollback_plan_available=bool(rollback_plan_available),
        feature_flag_default_off=True,
        legacy_exit_path_unchanged=True,
        operator_approval=bool(operator_approval),
        operator_name=operator_name.strip() or None,
        evidence_reference=evidence_reference.strip() or None,
    )
    report = evaluate_promotion_readiness(evidence)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Promotion stage", report.stage.value)
    c2.metric("Shadow ready", "YES" if report.shadow_ready else "NO")
    c3.metric("Paper ready", "YES" if report.paper_ready else "NO")
    c4.metric("Blocking gates", len(report.blocking_codes))

    message_method, message = _stage_message(report.stage)
    getattr(st, message_method)(message)

    if report.blocking_codes:
        st.write("Blocking codes: " + ", ".join(report.blocking_codes))
    _render_gate_table(st, report)

    payload = {
        "evidence": asdict(evidence),
        "report": report.to_record(),
    }
    st.download_button(
        "Download Red Bar V2 readiness JSON",
        data=json.dumps(payload, indent=2, default=str),
        file_name="red_bar_v2_promotion_readiness.json",
        mime="application/json",
        key="rbv2_download_readiness",
    )


def build_red_bar_v2_promotion_wrapper(
    original_render_page: Callable[..., Any],
) -> Callable[..., Any]:
    def wrapped(settings, layout, database, token, underlying_name, instrument_key, interval):
        import streamlit as st

        render_red_bar_v2_promotion_panel(st)
        return original_render_page(
            settings,
            layout,
            database,
            token,
            underlying_name,
            instrument_key,
            interval,
        )

    return wrapped
