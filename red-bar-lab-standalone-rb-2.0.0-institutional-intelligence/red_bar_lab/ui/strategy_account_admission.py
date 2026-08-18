from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import streamlit as st


@dataclass(frozen=True)
class AccountAdmissionPolicy:
    policy_version: str = "ACCOUNT-ADMISSION-V1"
    maximum_same_direction_positions: int = 3
    maximum_same_expiry_positions: int = 3
    require_broker_ready: bool = True
    require_account_ready: bool = True


DEFAULT_POLICY = AccountAdmissionPolicy()


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "ready", "active"}:
        return True
    if text in {"0", "false", "no", "off", "not_ready", "inactive"}:
        return False
    return None


def _key(row: Mapping[str, object]) -> str:
    return str(row.get("instrument_key") or row.get("instrument_token") or row.get("trading_symbol") or "")


def _risk_rows(result: Mapping[str, object]) -> dict[str, dict[str, object]]:
    return {
        str(row.get("candidate_id")): dict(row)
        for row in result.get("rows") or []
        if row.get("candidate_id") not in (None, "")
    }


def build_portfolio_admission(
    opportunity_result: Mapping[str, object],
    risk_result: Mapping[str, object],
    *,
    account_context: Mapping[str, object] | None = None,
    policy: AccountAdmissionPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    """Evaluate shared-account conflicts without merging strategy signals."""
    context = dict(account_context or {})
    risk_by_id = _risk_rows(risk_result)
    active = [dict(row) for row in context.get("active_positions") or [] if isinstance(row, Mapping)]
    admitted = [dict(row) for row in context.get("admitted_candidates") or [] if isinstance(row, Mapping)]
    reserved_capital = _number(context.get("reserved_capital")) or 0.0
    max_positions = _number(context.get("maximum_open_positions"))
    current_positions = int(_number(context.get("open_positions")) or len(active))

    active_keys = {_key(row) for row in active + admitted if _key(row)}
    active_identity = {
        str(row.get("identity_key") or "") for row in active + admitted
        if row.get("identity_key") not in (None, "")
    }
    direction_counts: dict[str, int] = {}
    expiry_counts: dict[str, int] = {}
    for row in active + admitted:
        side = str(row.get("contract_side") or row.get("side") or "").upper()
        expiry = str(row.get("expiry") or "")
        if side:
            direction_counts[side] = direction_counts.get(side, 0) + 1
        if expiry:
            expiry_counts[expiry] = expiry_counts.get(expiry, 0) + 1

    proposed_keys: set[str] = set()
    proposed_identity: set[str] = set()
    proposed_direction: dict[str, int] = {}
    proposed_expiry: dict[str, int] = {}
    rows = []

    for raw in opportunity_result.get("rows") or []:
        candidate = dict(raw)
        cid = str(candidate.get("candidate_id") or "Unavailable")
        section7 = str(candidate.get("combined_outcome") or "").upper()
        risk = risk_by_id.get(cid, {})
        risk_outcome = str(risk.get("risk_outcome") or "NOT_EVALUATED").upper()
        checks = []
        waits: list[str] = []
        rejects: list[str] = []

        eligible = section7 in {"FORWARD", "FORWARD_WITHOUT_HISTORICAL_SUPPORT"} and risk_outcome == "RISK_READY_READ_ONLY"
        checks.append({"check": "Individual eligibility", "status": "PASS" if eligible else "WAIT", "detail": f"section7={section7}; risk={risk_outcome}"})
        if not eligible:
            waits.append("INDIVIDUAL_ACCOUNT_RISK_NOT_READY")

        contract_key = _key(candidate)
        identity = str(candidate.get("identity_key") or "")
        duplicate_active = bool(contract_key and contract_key in active_keys) or bool(identity and identity in active_identity)
        duplicate_proposed = bool(contract_key and contract_key in proposed_keys) or bool(identity and identity in proposed_identity)
        if duplicate_active:
            checks.append({"check": "Duplicate exposure", "status": "REJECT", "detail": "SAME_CONTRACT_OR_IDENTITY_ALREADY_ACTIVE"})
            rejects.append("REJECT_DUPLICATE_EXPOSURE")
        elif duplicate_proposed:
            checks.append({"check": "Duplicate exposure", "status": "WAIT", "detail": "SAME_CONTRACT_OR_IDENTITY_ALREADY_PROPOSED"})
            waits.append("WAIT_PORTFOLIO_CONFLICT")
        else:
            checks.append({"check": "Duplicate exposure", "status": "PASS", "detail": "UNIQUE"})

        projected_positions = current_positions + len(proposed_keys) + 1
        if max_positions is None:
            checks.append({"check": "Position slots", "status": "WAIT", "detail": "MAXIMUM_OPEN_POSITIONS_UNAVAILABLE"})
            waits.append("WAIT_FOR_POSITION_SLOT")
        elif projected_positions > int(max_positions):
            checks.append({"check": "Position slots", "status": "WAIT", "detail": f"projected={projected_positions}; limit={int(max_positions)}"})
            waits.append("WAIT_FOR_POSITION_SLOT")
        else:
            checks.append({"check": "Position slots", "status": "PASS", "detail": f"projected={projected_positions}; limit={int(max_positions)}"})

        side = str(candidate.get("contract_side") or "").upper()
        side_count = direction_counts.get(side, 0) + proposed_direction.get(side, 0) + 1 if side else 0
        if side and side_count > policy.maximum_same_direction_positions:
            checks.append({"check": "Directional concentration", "status": "WAIT", "detail": f"{side} projected={side_count}"})
            waits.append("WAIT_DIRECTIONAL_CONCENTRATION")
        else:
            checks.append({"check": "Directional concentration", "status": "PASS", "detail": f"{side or 'UNKNOWN'} projected={side_count}"})

        expiry = str(candidate.get("expiry") or "")
        expiry_count = expiry_counts.get(expiry, 0) + proposed_expiry.get(expiry, 0) + 1 if expiry else 0
        if expiry and expiry_count > policy.maximum_same_expiry_positions:
            checks.append({"check": "Expiry concentration", "status": "WAIT", "detail": f"{expiry} projected={expiry_count}"})
            waits.append("WAIT_EXPIRY_CONCENTRATION")
        else:
            checks.append({"check": "Expiry concentration", "status": "PASS" if expiry else "INFO", "detail": f"{expiry or 'UNAVAILABLE'} projected={expiry_count}"})

        outcome = "REJECT" if rejects else "WAIT" if waits else "PORTFOLIO_READY_READ_ONLY"
        if outcome == "PORTFOLIO_READY_READ_ONLY":
            if contract_key:
                proposed_keys.add(contract_key)
            if identity:
                proposed_identity.add(identity)
            if side:
                proposed_direction[side] = proposed_direction.get(side, 0) + 1
            if expiry:
                proposed_expiry[expiry] = proposed_expiry.get(expiry, 0) + 1

        rows.append({
            **candidate,
            "section_8a_risk_outcome": risk_outcome,
            "portfolio_outcome": outcome,
            "portfolio_reason": ", ".join(rejects or waits) if (rejects or waits) else "ALL_PORTFOLIO_CHECKS_PASSED",
            "current_positions": current_positions,
            "maximum_open_positions": int(max_positions) if max_positions is not None else None,
            "reserved_capital": reserved_capital,
            "checks": checks,
            "policy_action": "OBSERVE_ONLY",
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
        })

    return {
        "outcome": "PORTFOLIO_READY_READ_ONLY" if any(r["portfolio_outcome"] == "PORTFOLIO_READY_READ_ONLY" for r in rows) else "REJECT" if any(r["portfolio_outcome"] == "REJECT" for r in rows) else "WAIT" if rows else "NOT_ELIGIBLE",
        "rows": rows,
        "policy_version": policy.policy_version,
        "policy_action": "OBSERVE_ONLY",
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


def build_capital_reservation_proposal(
    portfolio_result: Mapping[str, object],
    *,
    account_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build sequential read-only quantity and capital proposals."""
    context = dict(account_context or {})
    available_cash = _number(context.get("available_cash"))
    reserved_capital = _number(context.get("reserved_capital")) or 0.0
    remaining = available_cash - reserved_capital if available_cash is not None else None
    default_lots = int(_number(context.get("proposed_lots")) or 1)
    max_risk_per_trade = _number(context.get("maximum_risk_per_trade"))
    rows = []

    for raw in portfolio_result.get("rows") or []:
        candidate = dict(raw)
        opportunity = dict(candidate.get("opportunity") or {})
        lots = int(_number(candidate.get("proposed_lots")) or default_lots)
        lot_size = _number(candidate.get("lot_size"))
        entry = _number(candidate.get("ltp") or opportunity.get("entry_premium"))
        stop = _number(opportunity.get("initial_option_stop"))
        slippage = _number(opportunity.get("estimated_slippage"))
        charges = _number(opportunity.get("estimated_charges"))
        quantity = int(lot_size * lots) if lot_size is not None else None
        required_capital = entry * quantity if entry is not None and quantity is not None else None
        initial_risk = (entry - stop) * quantity if None not in (entry, stop, quantity) else None
        slippage_reserve = slippage * quantity if slippage is not None and quantity is not None else None
        charges_reserve = charges * quantity if charges is not None and quantity is not None else None
        total_risk = sum(v for v in (initial_risk, slippage_reserve, charges_reserve) if v is not None) if None not in (initial_risk, slippage_reserve, charges_reserve) else None

        waits = []
        rejects = []
        if candidate.get("portfolio_outcome") != "PORTFOLIO_READY_READ_ONLY":
            waits.append("PORTFOLIO_NOT_READY")
        if None in (quantity, required_capital, total_risk):
            waits.append("RESERVATION_INPUTS_UNAVAILABLE")
        if remaining is None:
            waits.append("AVAILABLE_CAPITAL_UNAVAILABLE")
        elif required_capital is not None and required_capital > remaining:
            waits.append("WAIT_FOR_CAPITAL")
        if max_risk_per_trade is not None and total_risk is not None and total_risk > max_risk_per_trade:
            rejects.append("REJECT_RISK_LIMIT")

        outcome = "REJECT" if rejects else "WAIT" if waits else "PROPOSED_READ_ONLY"
        capital_before = remaining
        capital_after = remaining - required_capital if outcome == "PROPOSED_READ_ONLY" and remaining is not None and required_capital is not None else remaining
        if outcome == "PROPOSED_READ_ONLY":
            remaining = capital_after

        rows.append({
            **candidate,
            "proposed_lots": lots,
            "quantity": quantity,
            "required_capital": round(required_capital, 2) if required_capital is not None else None,
            "initial_option_risk": round(initial_risk, 2) if initial_risk is not None else None,
            "slippage_reserve": round(slippage_reserve, 2) if slippage_reserve is not None else None,
            "charges_reserve": round(charges_reserve, 2) if charges_reserve is not None else None,
            "total_proposed_risk": round(total_risk, 2) if total_risk is not None else None,
            "capital_before_proposal": round(capital_before, 2) if capital_before is not None else None,
            "capital_remaining_after_proposal": round(capital_after, 2) if capital_after is not None else None,
            "reservation_outcome": outcome,
            "reservation_reason": ", ".join(rejects or waits) if (rejects or waits) else "CAPITAL_RESERVATION_PROPOSAL_READY",
            "reservation_state": "PROPOSED_READ_ONLY" if outcome == "PROPOSED_READ_ONLY" else "NOT_PROPOSED",
            "policy_action": "OBSERVE_ONLY",
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
        })

    return {
        "outcome": "PROPOSED_READ_ONLY" if any(r["reservation_outcome"] == "PROPOSED_READ_ONLY" for r in rows) else "REJECT" if any(r["reservation_outcome"] == "REJECT" for r in rows) else "WAIT" if rows else "NOT_ELIGIBLE",
        "rows": rows,
        "capital_remaining_after_all_proposals": round(remaining, 2) if remaining is not None else None,
        "policy_action": "OBSERVE_ONLY",
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


def build_final_admission(
    reservation_result: Mapping[str, object],
    *,
    execution_source_gate: Mapping[str, object] | None = None,
    account_context: Mapping[str, object] | None = None,
    policy: AccountAdmissionPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    source = dict(execution_source_gate or {})
    context = dict(account_context or {})
    source_enabled = source.get("execution_eligible")
    if source_enabled is None:
        source_enabled = source.get("execution_enabled")
    source_enabled = bool(source_enabled) if source_enabled is not None else None
    broker_ready = _bool(context.get("broker_ready"))
    account_ready = _bool(context.get("account_ready"))
    kill_switch = _bool(context.get("emergency_stop"))
    rows = []

    for raw in reservation_result.get("rows") or []:
        row = dict(raw)
        reason = str(row.get("reservation_reason") or "")
        if kill_switch is True:
            decision = "REJECT_KILL_SWITCH"
        elif row.get("portfolio_outcome") == "REJECT":
            decision = "REJECT_DUPLICATE_EXPOSURE"
        elif row.get("section_8a_risk_outcome") == "RISK_BLOCKED":
            risk_reason = str(row.get("exact_reason") or "")
            decision = "REJECT_DAILY_LOSS_LIMIT" if "DAILY_LOSS" in risk_reason else "REJECT_RISK_LIMIT"
        elif row.get("reservation_outcome") == "REJECT":
            decision = "REJECT_RISK_LIMIT"
        elif "WAIT_FOR_CAPITAL" in reason:
            decision = "WAIT_FOR_CAPITAL"
        elif "POSITION_SLOT" in str(row.get("portfolio_reason") or ""):
            decision = "WAIT_FOR_POSITION_SLOT"
        elif row.get("reservation_outcome") != "PROPOSED_READ_ONLY":
            decision = "WAIT"
        elif policy.require_broker_ready and broker_ready is None:
            decision = "WAIT"
        elif policy.require_broker_ready and not broker_ready:
            decision = "WAIT_BROKER_NOT_READY"
        elif policy.require_account_ready and account_ready is None:
            decision = "WAIT"
        elif policy.require_account_ready and not account_ready:
            decision = "WAIT_ACCOUNT_NOT_READY"
        elif source_enabled is None:
            decision = "WAIT"
        elif not source_enabled:
            decision = "WAIT_EXECUTION_SOURCE_DISABLED"
        else:
            decision = "ADMISSION_READY_READ_ONLY"

        exact = {
            "ADMISSION_READY_READ_ONLY": "ALL_ACCOUNT_ADMISSION_CHECKS_PASSED",
            "REJECT_KILL_SWITCH": "EMERGENCY_KILL_SWITCH_ACTIVE",
            "REJECT_DUPLICATE_EXPOSURE": str(row.get("portfolio_reason") or "DUPLICATE_EXPOSURE"),
            "REJECT_DAILY_LOSS_LIMIT": str(row.get("exact_reason") or "DAILY_LOSS_LIMIT_REACHED"),
            "REJECT_RISK_LIMIT": reason or str(row.get("exact_reason") or "RISK_LIMIT_REACHED"),
            "WAIT_FOR_CAPITAL": reason,
            "WAIT_FOR_POSITION_SLOT": str(row.get("portfolio_reason") or "POSITION_SLOT_UNAVAILABLE"),
            "WAIT_BROKER_NOT_READY": "BROKER_NOT_READY",
            "WAIT_ACCOUNT_NOT_READY": "ACCOUNT_NOT_READY",
            "WAIT_EXECUTION_SOURCE_DISABLED": "EXECUTION_SOURCE_DISABLED",
            "WAIT": reason or "ADMISSION_INPUT_UNAVAILABLE",
        }[decision]
        rows.append({
            **row,
            "broker_ready": broker_ready,
            "account_ready": account_ready,
            "kill_switch": kill_switch,
            "execution_source_enabled": source_enabled,
            "final_admission_decision": decision,
            "final_admission_reason": exact,
            "next_step": "Section 9 committee and order preparation may inspect this read-only admission." if decision == "ADMISSION_READY_READ_ONLY" else "Resolve the exact account-admission blocker before Section 9.",
            "policy_version": policy.policy_version,
            "policy_action": "OBSERVE_ONLY",
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
        })

    return {
        "outcome": "ADMISSION_READY_READ_ONLY" if any(r["final_admission_decision"] == "ADMISSION_READY_READ_ONLY" for r in rows) else "REJECT" if any(str(r["final_admission_decision"]).startswith("REJECT") for r in rows) else "WAIT" if rows else "NOT_ELIGIBLE",
        "rows": rows,
        "policy_version": policy.policy_version,
        "policy_action": "OBSERVE_ONLY",
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


def render_account_admission(
    portfolio_result: Mapping[str, object],
    reservation_result: Mapping[str, object],
    final_result: Mapping[str, object],
) -> None:
    st.markdown("#### 8B. Portfolio Conflict and Exposure Admission")
    st.caption("Shared account-risk checks only. Strategy signals remain independent and are never merged.")
    st.dataframe([{k: row.get(k) for k in ("candidate_id", "strategy_id", "role", "contract_side", "portfolio_outcome", "portfolio_reason", "current_positions", "maximum_open_positions")} for row in portfolio_result.get("rows") or []], width="stretch", hide_index=True)

    st.markdown("#### 8C. Quantity and Capital Reservation Proposal")
    st.caption("PROPOSED_READ_ONLY only. No funds or contracts are actually reserved.")
    st.dataframe([{k: row.get(k) for k in ("candidate_id", "role", "proposed_lots", "quantity", "required_capital", "initial_option_risk", "slippage_reserve", "charges_reserve", "total_proposed_risk", "capital_remaining_after_proposal", "reservation_outcome", "reservation_reason")} for row in reservation_result.get("rows") or []], width="stretch", hide_index=True)

    st.markdown("#### 8D. Final Admission Decision")
    st.caption("Final read-only account admission. Section 9 remains the committee and order-preparation boundary.")
    rows = [dict(row) for row in final_result.get("rows") or []]
    st.dataframe([{k: row.get(k) for k in ("candidate_id", "strategy_id", "bundle_id", "role", "required_capital", "total_proposed_risk", "current_positions", "maximum_open_positions", "broker_ready", "account_ready", "kill_switch", "final_admission_decision", "final_admission_reason")} for row in rows], width="stretch", hide_index=True)
    for row in rows:
        with st.expander(f"Why was {row.get('candidate_id')} admitted or blocked by account risk?"):
            st.write(f"**Portfolio:** {row.get('portfolio_outcome')} — {row.get('portfolio_reason')}")
            st.write(f"**Reservation:** {row.get('reservation_outcome')} — {row.get('reservation_reason')}")
            st.write(f"**Final admission:** {row.get('final_admission_decision')}")
            st.write(f"**Exact blocker:** {row.get('final_admission_reason')}")
            st.write(f"**Next step:** {row.get('next_step')}")
