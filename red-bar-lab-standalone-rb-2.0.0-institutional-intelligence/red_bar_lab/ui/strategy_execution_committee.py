from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping

import streamlit as st


COMMITTEE_VERSION = "EXECUTION-COMMITTEE-V1"


@dataclass(frozen=True)
class ExecutionCommitteePolicy:
    policy_version: str = COMMITTEE_VERSION
    require_supported_contract_identity: bool = True
    require_positive_quantity: bool = True
    require_positive_risk: bool = True


DEFAULT_POLICY = ExecutionCommitteePolicy()


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _present(value: object) -> bool:
    return value not in (None, "", "Unavailable", "UNAVAILABLE", "Not created")


def _check(authority: str, passed: bool, detail: str, *, wait: bool = False) -> dict[str, object]:
    return {
        "authority": authority,
        "status": "PASS" if passed else ("WAIT" if wait else "BLOCK"),
        "detail": detail,
    }


def _committee_id(row: Mapping[str, object]) -> str:
    raw = "|".join(str(row.get(name) or "") for name in (
        "strategy_id", "bundle_id", "signal_id", "candidate_id",
        "instrument_token", "instrument_key", "trading_symbol",
        "admission_priority_rank",
    ))
    return f"COM-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20].upper()}"


def build_execution_committee(
    final_admission: Mapping[str, object],
    *,
    policy: ExecutionCommitteePolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    """Verify Section 8D handoff integrity without creating or submitting an order."""
    rows: list[dict[str, object]] = []
    for raw in final_admission.get("rows") or []:
        row = dict(raw)
        checks: list[dict[str, object]] = []
        waits: list[str] = []
        blocks: list[str] = []

        admitted = str(row.get("final_admission_decision") or "") == "ADMISSION_READY_READ_ONLY"
        checks.append(_check(
            "Section 8D final admission",
            admitted,
            str(row.get("final_admission_reason") or row.get("final_admission_decision") or "NOT_EVALUATED"),
            wait=not admitted and not str(row.get("final_admission_decision") or "").startswith("REJECT"),
        ))
        if not admitted:
            reason = "SECTION_8D_NOT_ADMISSION_READY"
            if str(row.get("final_admission_decision") or "").startswith("REJECT"):
                blocks.append(reason)
            else:
                waits.append(reason)

        strategy_ok = all(_present(row.get(name)) for name in ("strategy_id", "bundle_id", "signal_id", "candidate_id", "role"))
        checks.append(_check(
            "Strategy ownership and event identity",
            strategy_ok,
            "STRATEGY_BUNDLE_SIGNAL_CANDIDATE_ROLE_PRESENT" if strategy_ok else "STRATEGY_EVENT_IDENTITY_INCOMPLETE",
            wait=not strategy_ok,
        ))
        if not strategy_ok:
            waits.append("STRATEGY_EVENT_IDENTITY_INCOMPLETE")

        identity_confidence = str(row.get("contract_identity_confidence") or "")
        contract_identity = _present(row.get("contract_exposure_key")) or _present(row.get("instrument_token")) or _present(row.get("instrument_key"))
        identity_supported = contract_identity and (
            not policy.require_supported_contract_identity
            or identity_confidence not in {"", "UNAVAILABLE"}
            or _present(row.get("instrument_token"))
            or _present(row.get("instrument_key"))
        )
        metadata_ok = identity_supported and all(_present(row.get(name)) for name in ("trading_symbol", "exchange", "expiry", "strike", "lot_size", "tick_size"))
        checks.append(_check(
            "Contract and market-data authority",
            metadata_ok,
            f"identity_confidence={identity_confidence or 'UNAVAILABLE'}" if metadata_ok else "EXECUTION_CONTRACT_METADATA_INCOMPLETE",
            wait=not metadata_ok,
        ))
        if not metadata_ok:
            waits.append("EXECUTION_CONTRACT_METADATA_INCOMPLETE")

        opportunity = dict(row.get("opportunity") or {})
        entry = _number(row.get("ltp") if row.get("ltp") is not None else opportunity.get("entry_premium"))
        stop = _number(opportunity.get("initial_option_stop"))
        opportunity_ok = str(row.get("opportunity_outcome") or "") == "PASS" and entry is not None and stop is not None and 0 < stop < entry
        checks.append(_check(
            "Opportunity and stop authority",
            opportunity_ok,
            f"entry={entry}; stop={stop}; outcome={row.get('opportunity_outcome')}" if opportunity_ok else "OPPORTUNITY_OR_STOP_NOT_READY",
            wait=not opportunity_ok,
        ))
        if not opportunity_ok:
            waits.append("OPPORTUNITY_OR_STOP_NOT_READY")

        quantity = _number(row.get("quantity"))
        total_risk = _number(row.get("total_proposed_risk"))
        proposal_ok = str(row.get("reservation_outcome") or "") == "PROPOSED_READ_ONLY"
        if policy.require_positive_quantity:
            proposal_ok = proposal_ok and quantity is not None and quantity > 0
        if policy.require_positive_risk:
            proposal_ok = proposal_ok and total_risk is not None and total_risk > 0
        checks.append(_check(
            "Quantity and risk proposal authority",
            proposal_ok,
            f"quantity={quantity}; total_risk={total_risk}" if proposal_ok else "QUANTITY_OR_RISK_PROPOSAL_NOT_READY",
            wait=not proposal_ok,
        ))
        if not proposal_ok:
            waits.append("QUANTITY_OR_RISK_PROPOSAL_NOT_READY")

        execution_ready = (
            row.get("broker_ready") is True
            and row.get("account_ready") is True
            and row.get("kill_switch") is False
            and row.get("execution_source_enabled") is True
        )
        checks.append(_check(
            "Execution readiness authority",
            execution_ready,
            (
                f"broker={row.get('broker_ready')}; account={row.get('account_ready')}; "
                f"kill_switch={row.get('kill_switch')}; source={row.get('execution_source_enabled')}"
            ),
            wait=not execution_ready,
        ))
        if not execution_ready:
            waits.append("EXECUTION_READINESS_NOT_CONFIRMED")

        if blocks:
            outcome = "COMMITTEE_BLOCKED_READ_ONLY"
        elif waits:
            outcome = "WAIT"
        else:
            outcome = "COMMITTEE_READY_READ_ONLY"

        exact_reason = ", ".join(blocks or waits) if (blocks or waits) else "ALL_COMMITTEE_AUTHORITIES_PASSED"
        rows.append({
            **row,
            "committee_id": _committee_id(row),
            "committee_outcome": outcome,
            "committee_reason": exact_reason,
            "committee_checks": checks,
            "committee_policy_version": policy.policy_version,
            "order_preparation_allowed": outcome == "COMMITTEE_READY_READ_ONLY",
            "order_created": False,
            "order_submitted": False,
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
            "policy_action": "OBSERVE_ONLY",
            "next_step": (
                "Section 9B may prepare a read-only order specification."
                if outcome == "COMMITTEE_READY_READ_ONLY"
                else "Resolve the exact committee blocker before order preparation."
            ),
        })

    ready = sum(row["committee_outcome"] == "COMMITTEE_READY_READ_ONLY" for row in rows)
    waiting = sum(row["committee_outcome"] == "WAIT" for row in rows)
    blocked = sum(row["committee_outcome"] == "COMMITTEE_BLOCKED_READ_ONLY" for row in rows)
    return {
        "outcome": (
            "COMMITTEE_READY_READ_ONLY" if ready
            else "COMMITTEE_BLOCKED_READ_ONLY" if blocked
            else "WAIT" if waiting
            else "NOT_ELIGIBLE"
        ),
        "rows": rows,
        "ready_count": ready,
        "waiting_count": waiting,
        "blocked_count": blocked,
        "committee_policy_version": policy.policy_version,
        "policy_action": "OBSERVE_ONLY",
        "order_created": False,
        "order_submitted": False,
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


def render_execution_committee(result: Mapping[str, object]) -> None:
    st.markdown("### 9. Execution Committee and Order Preparation")
    st.markdown("#### 9A. Read-Only Execution Committee Admission")
    st.caption(
        "Consumes only Section 8D admission results. It verifies authority and handoff integrity; "
        "it does not create, persist, reserve, consume, or submit an order."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(result.get("outcome") or "NOT_ELIGIBLE"))
    c2.metric("Ready", int(result.get("ready_count") or 0))
    c3.metric("Waiting", int(result.get("waiting_count") or 0))
    c4.metric("Blocked", int(result.get("blocked_count") or 0))
    rows = [dict(row) for row in result.get("rows") or []]
    if not rows:
        st.info("No Section 8D candidate is available for committee inspection.")
        return
    st.dataframe([
        {key: row.get(key) for key in (
            "committee_id", "candidate_id", "strategy_id", "bundle_id", "role",
            "trading_symbol", "quantity", "required_capital", "total_proposed_risk",
            "final_admission_decision", "committee_outcome", "committee_reason",
            "order_preparation_allowed",
        )}
        for row in rows
    ], width="stretch", hide_index=True)
    for row in rows:
        with st.expander(f"Why did the committee evaluate {row.get('candidate_id')} this way?"):
            st.dataframe(list(row.get("committee_checks") or []), width="stretch", hide_index=True)
            st.write(f"**Committee outcome:** {row.get('committee_outcome')}")
            st.write(f"**Exact reason:** {row.get('committee_reason')}")
            st.write(f"**Next step:** {row.get('next_step')}")
            st.write("**Safety:** No order was created or submitted.")


__all__ = [
    "ExecutionCommitteePolicy",
    "DEFAULT_POLICY",
    "COMMITTEE_VERSION",
    "build_execution_committee",
    "render_execution_committee",
]
