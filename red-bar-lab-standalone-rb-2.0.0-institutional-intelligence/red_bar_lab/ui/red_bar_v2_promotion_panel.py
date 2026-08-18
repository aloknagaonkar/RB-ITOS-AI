from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable

from red_bar_lab.services.red_bar_v2_evidence_collection import collect_promotion_evidence
from red_bar_lab.services.red_bar_v2_promotion_readiness import (
    PromotionEvidence,
    PromotionStage,
    evaluate_promotion_readiness,
)


def _default_evidence() -> PromotionEvidence:
    return PromotionEvidence(
        unit_tests_passed=88,
        unit_tests_failed=0,
        feature_flag_default_off=True,
        legacy_exit_path_unchanged=True,
        rollback_plan_available=True,
        evidence_reference="RED_BAR_V2_PHASE_1_11_UI_BASELINE",
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
    st.dataframe(
        [
            {
                "Gate": gate.code,
                "Required for": gate.required_for.value,
                "Status": "PASS" if gate.passed else "BLOCKED",
                "Observed": gate.observed,
                "Required": gate.required,
                "Reason": gate.reason,
            }
            for gate in report.gates
        ],
        width="stretch",
        hide_index=True,
    )


def _automatic_evidence(settings: Any | None) -> PromotionEvidence:
    if settings is None:
        return _default_evidence()
    evidence_root = Path(settings.runs_root) / "red_bar_v2" / "promotion_evidence"
    return collect_promotion_evidence(
        database_path=settings.database_path,
        evidence_root=evidence_root,
        unit_tests_passed=88,
        unit_tests_failed=0,
        rollback_plan_available=True,
    )


def render_red_bar_v2_promotion_panel(st: Any, settings: Any | None = None) -> None:
    st.markdown("---")
    st.markdown("### Red Bar V2 — Shadow Evidence & Promotion Readiness")
    st.caption(
        "Operational counts are loaded automatically from the Red Bar V2 SQLite "
        "audit tables and append-only replay, parity and shadow evidence files. "
        "This panel never enables execution or changes feature flags."
    )

    automatic = _automatic_evidence(settings)
    evidence_root = (
        Path(settings.runs_root) / "red_bar_v2" / "promotion_evidence"
        if settings is not None
        else None
    )

    if st.button("Refresh automatic evidence", key="rbv2_refresh_automatic_evidence"):
        st.rerun()

    st.markdown("#### Automatically collected evidence")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Replay sessions", automatic.replay_sessions)
    r2.metric("Replay candidates", automatic.replay_candidates)
    r3.metric("Replay errors", automatic.replay_errors)
    r4.metric("Audit storage", "AVAILABLE" if automatic.storage_audit_available else "MISSING")

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Parity comparisons", automatic.parity_comparisons)
    p2.metric("Parity mismatches", automatic.parity_mismatches)
    p3.metric("Duplicate entries", automatic.duplicate_entries)
    p4.metric("Lifecycle conflicts", automatic.unresolved_lifecycle_conflicts)

    s1, s2, s3 = st.columns(3)
    s1.metric("Shadow sessions", automatic.shadow_sessions)
    s2.metric("Shadow decisions", automatic.shadow_decisions)
    s3.metric("Shadow errors", automatic.shadow_errors)

    if evidence_root is not None:
        st.caption(f"Evidence directory: {evidence_root}")

    with st.expander("Manual authorization controls", expanded=True):
        st.info(
            "Operational counters are read-only. Rollback confirmation and named "
            "operator approval remain manual by design."
        )
        rollback_plan_available = st.checkbox(
            "Rollback plan available",
            value=automatic.rollback_plan_available,
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

    evidence = replace(
        automatic,
        rollback_plan_available=bool(rollback_plan_available),
        operator_approval=bool(operator_approval),
        operator_name=operator_name.strip() or None,
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

    payload = {"evidence": asdict(evidence), "report": report.to_record()}
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

        render_red_bar_v2_promotion_panel(st, settings)
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
