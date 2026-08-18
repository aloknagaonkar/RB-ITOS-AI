from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import streamlit as st


@dataclass(frozen=True)
class ExecutionDecisionPolicy:
    policy_version: str = "EXECUTION-DECISION-GATE-V1"
    require_execution_source: bool = True
    allow_without_historical_support: bool = True


DEFAULT_POLICY = ExecutionDecisionPolicy()


def _text(value: object) -> str:
    return str(value or "").strip().upper()


def _check(name: str, status: str, detail: object) -> dict[str, object]:
    return {"check": name, "status": status, "detail": detail}


def build_execution_decision_gate(
    opportunity_result: Mapping[str, object],
    risk_result: Mapping[str, object],
    *,
    execution_source_gate: Mapping[str, object] | None = None,
    policy: ExecutionDecisionPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    """Combine Sections 7 and 8A without persistence, reservation or execution."""
    source = dict(execution_source_gate or {})
    source_enabled = source.get("execution_eligible")
    if source_enabled is None:
        source_enabled = source.get("execution_enabled")
    source_enabled = bool(source_enabled) if source_enabled is not None else None

    risk_by_candidate = {
        str(row.get("candidate_id") or ""): dict(row)
        for row in (risk_result.get("rows") or [])
        if row.get("candidate_id") not in (None, "")
    }

    rows: list[dict[str, object]] = []
    for raw in opportunity_result.get("rows") or []:
        candidate = dict(raw)
        candidate_id = str(candidate.get("candidate_id") or "Unavailable")
        combined = _text(candidate.get("combined_outcome"))
        risk = risk_by_candidate.get(candidate_id)
        risk_outcome = _text((risk or {}).get("risk_outcome"))
        checks: list[dict[str, object]] = []
        blockers: list[str] = []
        waits: list[str] = []
        observations: list[str] = []

        if combined in {"FORWARD", "FORWARD_WITHOUT_HISTORICAL_SUPPORT"}:
            checks.append(_check("Section 7 combined gate", "PASS", combined))
        elif combined == "WAIT":
            checks.append(_check("Section 7 combined gate", "WAIT", combined))
            waits.append("SECTION_7_WAIT")
        elif combined == "OBSERVE_ONLY":
            checks.append(_check("Section 7 combined gate", "OBSERVE", combined))
            observations.append("SECTION_7_OBSERVE_ONLY")
        else:
            checks.append(_check("Section 7 combined gate", "BLOCK", combined or "UNAVAILABLE"))
            blockers.append("SECTION_7_REJECTED_OR_UNAVAILABLE")

        historical_limited = combined == "FORWARD_WITHOUT_HISTORICAL_SUPPORT"
        if historical_limited:
            status = "OBSERVE" if policy.allow_without_historical_support else "BLOCK"
            checks.append(_check("Historical support authority", status, "NO_HISTORICAL_SUPPORT"))
            if policy.allow_without_historical_support:
                observations.append("LIMITED_HISTORICAL_EVIDENCE")
            else:
                blockers.append("HISTORICAL_SUPPORT_REQUIRED")
        elif combined == "FORWARD":
            checks.append(_check("Historical support authority", "PASS", "SUPPORTED"))

        if combined in {"FORWARD", "FORWARD_WITHOUT_HISTORICAL_SUPPORT"}:
            if risk is None:
                checks.append(_check("Section 8A risk readiness", "WAIT", "RISK_RESULT_UNAVAILABLE"))
                waits.append("RISK_RESULT_UNAVAILABLE")
            elif risk_outcome == "RISK_READY_READ_ONLY":
                checks.append(_check("Section 8A risk readiness", "PASS", risk_outcome))
            elif risk_outcome == "WAIT":
                checks.append(_check("Section 8A risk readiness", "WAIT", (risk or {}).get("exact_reason")))
                waits.append("SECTION_8A_RISK_WAIT")
            else:
                checks.append(_check("Section 8A risk readiness", "BLOCK", (risk or {}).get("exact_reason") or risk_outcome))
                blockers.append("SECTION_8A_RISK_BLOCKED")
        else:
            checks.append(_check("Section 8A risk readiness", "NOT_EVALUATED", "SECTION_7_NOT_FORWARD_ELIGIBLE"))

        if policy.require_execution_source:
            if source_enabled is None:
                checks.append(_check("Execution source", "WAIT", "EXECUTION_SOURCE_STATE_UNAVAILABLE"))
                waits.append("EXECUTION_SOURCE_STATE_UNAVAILABLE")
            elif source_enabled:
                checks.append(_check("Execution source", "PASS", "ENABLED"))
            else:
                checks.append(_check("Execution source", "BLOCK", "EXECUTION_SOURCE_DISABLED"))
                blockers.append("EXECUTION_SOURCE_DISABLED")
        else:
            checks.append(_check("Execution source", "INFO", "NOT_REQUIRED_BY_POLICY"))

        if blockers:
            decision = "EXECUTION_BLOCKED_READ_ONLY"
        elif waits:
            decision = "WAIT"
        elif observations and combined == "OBSERVE_ONLY":
            decision = "OBSERVE_ONLY"
        elif combined in {"FORWARD", "FORWARD_WITHOUT_HISTORICAL_SUPPORT"} and risk_outcome == "RISK_READY_READ_ONLY":
            decision = "READY_FOR_COMMITTEE_READ_ONLY"
        else:
            decision = "NOT_ELIGIBLE"

        rows.append({
            "candidate_id": candidate.get("candidate_id"),
            "strategy_id": candidate.get("strategy_id"),
            "bundle_id": candidate.get("bundle_id"),
            "signal_id": candidate.get("signal_id"),
            "role": candidate.get("role"),
            "contract_side": candidate.get("contract_side"),
            "trading_symbol": candidate.get("trading_symbol"),
            "section_7_outcome": combined or "UNAVAILABLE",
            "section_8a_risk_outcome": risk_outcome or "NOT_EVALUATED",
            "historical_authority": "LIMITED" if historical_limited else "SUPPORTED" if combined == "FORWARD" else "NOT_APPLICABLE",
            "execution_source_enabled": source_enabled,
            "execution_decision": decision,
            "exact_reason": ", ".join(blockers or waits or observations) if (blockers or waits or observations) else "ALL_EXECUTION_DECISION_CHECKS_PASSED",
            "checks": checks,
            "policy_version": policy.policy_version,
            "policy_action": "OBSERVE_ONLY",
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
            "next_step": (
                "Section 8C committee may inspect this read-only recommendation."
                if decision == "READY_FOR_COMMITTEE_READ_ONLY"
                else "Resolve the exact gate reason before committee or execution activity."
            ),
        })

    ready = sum(row["execution_decision"] == "READY_FOR_COMMITTEE_READ_ONLY" for row in rows)
    waiting = sum(row["execution_decision"] == "WAIT" for row in rows)
    blocked = sum(row["execution_decision"] == "EXECUTION_BLOCKED_READ_ONLY" for row in rows)
    observing = sum(row["execution_decision"] == "OBSERVE_ONLY" for row in rows)
    outcome = (
        "READY_FOR_COMMITTEE_READ_ONLY" if ready
        else "EXECUTION_BLOCKED_READ_ONLY" if blocked
        else "WAIT" if waiting
        else "OBSERVE_ONLY" if observing
        else "NOT_ELIGIBLE"
    )
    return {
        "outcome": outcome,
        "policy_version": policy.policy_version,
        "candidates_evaluated": len(rows),
        "ready_count": ready,
        "waiting_count": waiting,
        "blocked_count": blocked,
        "observe_only_count": observing,
        "execution_source_enabled": source_enabled,
        "rows": rows,
        "policy_action": "OBSERVE_ONLY",
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


def render_execution_decision_gate(result: Mapping[str, object]) -> None:
    st.markdown("#### 8B. Read-Only Execution Decision Gate")
    st.caption(
        "Combines Section 7 opportunity/history evidence, Section 8A risk readiness, "
        "and the strategy execution-source state. This panel cannot approve or submit an order."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(result.get("outcome") or "NOT_ELIGIBLE"))
    c2.metric("Committee ready", int(result.get("ready_count") or 0))
    c3.metric("Waiting", int(result.get("waiting_count") or 0))
    c4.metric("Blocked", int(result.get("blocked_count") or 0))
    st.write(f"**Policy:** {result.get('policy_version')}")
    st.write(f"**Execution source enabled:** {result.get('execution_source_enabled')}")
    st.write("**Policy action:** OBSERVE_ONLY — no persistence, reservation, bundle consumption or order submission")

    rows = [dict(row) for row in (result.get("rows") or [])]
    if not rows:
        st.info("No Section 7 candidate is available for the execution decision gate.")
        return
    st.dataframe(
        [{key: row.get(key) for key in (
            "candidate_id", "strategy_id", "bundle_id", "role", "contract_side",
            "trading_symbol", "section_7_outcome", "section_8a_risk_outcome",
            "historical_authority", "execution_source_enabled", "execution_decision",
            "exact_reason",
        )} for row in rows],
        width="stretch",
        hide_index=True,
    )
    for row in rows:
        with st.expander(f"Why did the execution gate evaluate {row.get('candidate_id')} this way?"):
            st.dataframe(row.get("checks") or [], width="stretch", hide_index=True)
            st.write(f"**Decision:** {row.get('execution_decision')}")
            st.write(f"**Exact reason:** {row.get('exact_reason')}")
            st.write(f"**Next step:** {row.get('next_step')}")
