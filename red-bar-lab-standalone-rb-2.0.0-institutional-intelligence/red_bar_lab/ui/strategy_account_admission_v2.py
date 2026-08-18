from __future__ import annotations

from typing import Mapping

import streamlit as st

from red_bar_lab.ui.strategy_account_admission import (
    AccountAdmissionPolicy,
    DEFAULT_POLICY,
    _number,
    build_final_admission,
    build_portfolio_admission as _build_portfolio_admission_v1,
    render_account_admission as _render_account_admission_v1,
)
from red_bar_lab.ui.strategy_admission_priority import prioritize_admission_rows
from red_bar_lab.ui.strategy_monetary_exposure import apply_monetary_exposure_admission


STRATEGY_RISK_PROPOSAL_VERSION = "STRATEGY-RISK-PROPOSAL-V1"


def build_portfolio_admission(
    opportunity_result: Mapping[str, object],
    risk_result: Mapping[str, object],
    *,
    account_context: Mapping[str, object] | None = None,
    policy: AccountAdmissionPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    """Run stable conflict admission, then add monetary concentration controls."""
    base = _build_portfolio_admission_v1(
        opportunity_result,
        risk_result,
        account_context=account_context,
        policy=policy,
    )
    return apply_monetary_exposure_admission(base, account_context=account_context)


def _strategy_limits(context: Mapping[str, object]) -> dict[str, dict[str, float | None]]:
    raw = context.get("strategy_risk")
    result: dict[str, dict[str, float | None]] = {}
    if not isinstance(raw, Mapping):
        return result
    for strategy_id, value in raw.items():
        if not isinstance(value, Mapping):
            continue
        consumed = _number(value.get("consumed"))
        if consumed is None:
            consumed = _number(value.get("risk_consumed"))
        limit = _number(value.get("limit"))
        if limit is None:
            limit = _number(value.get("risk_limit"))
        result[str(strategy_id)] = {"consumed": consumed, "limit": limit}
    return result


def build_capital_reservation_proposal(
    portfolio_result: Mapping[str, object],
    *,
    account_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build prioritized sequential capital proposals with independent strategy-risk budgets."""
    context = dict(account_context or {})
    available_cash = _number(context.get("available_cash"))
    reserved_capital = _number(context.get("reserved_capital")) or 0.0
    remaining = available_cash - reserved_capital if available_cash is not None else None
    default_lots = int(_number(context.get("proposed_lots")) or 1)
    max_risk_per_trade = _number(context.get("maximum_risk_per_trade"))
    strategy_limits = _strategy_limits(context)
    proposed_strategy_risk: dict[str, float] = {}
    rows: list[dict[str, object]] = []
    prioritized = prioritize_admission_rows(portfolio_result.get("rows") or [])

    for raw in prioritized:
        candidate = dict(raw)
        opportunity = dict(candidate.get("opportunity") or {})
        strategy_id = str(candidate.get("strategy_id") or "")
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
        total_risk = (
            initial_risk + slippage_reserve + charges_reserve
            if None not in (initial_risk, slippage_reserve, charges_reserve)
            else None
        )

        strategy = strategy_limits.get(strategy_id, {})
        consumed = _number(strategy.get("consumed"))
        limit = _number(strategy.get("limit"))
        proposed_before = proposed_strategy_risk.get(strategy_id, 0.0)
        projected_strategy_risk = (
            (consumed or 0.0) + proposed_before + total_risk
            if total_risk is not None and (consumed is not None or limit is not None)
            else None
        )

        waits: list[str] = []
        rejects: list[str] = []
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
        if strategy_id not in strategy_limits:
            waits.append("STRATEGY_RISK_SCOPE_UNAVAILABLE")
        elif consumed is None or limit is None:
            waits.append("STRATEGY_RISK_SCOPE_INCOMPLETE")
        elif projected_strategy_risk is not None and projected_strategy_risk > limit:
            rejects.append("REJECT_STRATEGY_RISK_LIMIT")

        outcome = "REJECT" if rejects else "WAIT" if waits else "PROPOSED_READ_ONLY"
        capital_before = remaining
        capital_after = (
            remaining - required_capital
            if outcome == "PROPOSED_READ_ONLY" and remaining is not None and required_capital is not None
            else remaining
        )
        if outcome == "PROPOSED_READ_ONLY":
            remaining = capital_after
            proposed_strategy_risk[strategy_id] = proposed_before + float(total_risk or 0.0)

        rows.append({
            **candidate,
            "proposed_lots": lots,
            "quantity": quantity,
            "required_capital": round(required_capital, 2) if required_capital is not None else None,
            "initial_option_risk": round(initial_risk, 2) if initial_risk is not None else None,
            "slippage_reserve": round(slippage_reserve, 2) if slippage_reserve is not None else None,
            "charges_reserve": round(charges_reserve, 2) if charges_reserve is not None else None,
            "total_proposed_risk": round(total_risk, 2) if total_risk is not None else None,
            "strategy_risk_consumed_before": consumed,
            "strategy_risk_proposed_before": round(proposed_before, 2),
            "strategy_risk_limit": limit,
            "projected_strategy_risk": round(projected_strategy_risk, 2) if projected_strategy_risk is not None else None,
            "capital_before_proposal": round(capital_before, 2) if capital_before is not None else None,
            "capital_remaining_after_proposal": round(capital_after, 2) if capital_after is not None else None,
            "reservation_outcome": outcome,
            "reservation_reason": ", ".join(rejects or waits) if (rejects or waits) else "CAPITAL_AND_STRATEGY_RISK_PROPOSAL_READY",
            "reservation_state": "PROPOSED_READ_ONLY" if outcome == "PROPOSED_READ_ONLY" else "NOT_PROPOSED",
            "strategy_risk_proposal_version": STRATEGY_RISK_PROPOSAL_VERSION,
            "policy_action": "OBSERVE_ONLY",
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
        })

    return {
        "outcome": (
            "PROPOSED_READ_ONLY" if any(r["reservation_outcome"] == "PROPOSED_READ_ONLY" for r in rows)
            else "REJECT" if any(r["reservation_outcome"] == "REJECT" for r in rows)
            else "WAIT" if rows
            else "NOT_ELIGIBLE"
        ),
        "rows": rows,
        "capital_remaining_after_all_proposals": round(remaining, 2) if remaining is not None else None,
        "proposed_strategy_risk": {key: round(value, 2) for key, value in proposed_strategy_risk.items()},
        "strategy_risk_proposal_version": STRATEGY_RISK_PROPOSAL_VERSION,
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
    _render_account_admission_v1(portfolio_result, reservation_result, final_result)
    st.markdown("#### 8B.1 Monetary Exposure and Concentration")
    st.caption(
        "Read-only CE/PE, expiry and strike concentration. Limits affect admission only when explicitly configured."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CE capital", float(portfolio_result.get("ce_capital_exposure") or 0.0))
    c2.metric("PE capital", float(portfolio_result.get("pe_capital_exposure") or 0.0))
    c3.metric("CE risk", float(portfolio_result.get("ce_risk_exposure") or 0.0))
    c4.metric("PE risk", float(portfolio_result.get("pe_risk_exposure") or 0.0))
    rows = [dict(row) for row in portfolio_result.get("rows") or []]
    if rows:
        st.dataframe(
            [{key: row.get(key) for key in (
                "candidate_id", "strategy_id", "role", "contract_side",
                "contract_exposure_key", "contract_identity_confidence",
                "candidate_capital_exposure", "candidate_risk_exposure",
                "projected_side_capital_exposure", "projected_side_risk_exposure",
                "projected_expiry_capital_exposure", "projected_expiry_risk_exposure",
                "projected_same_strike_positions", "portfolio_outcome", "portfolio_reason",
            )} for row in rows],
            width="stretch",
            hide_index=True,
        )


__all__ = [
    "AccountAdmissionPolicy",
    "DEFAULT_POLICY",
    "build_portfolio_admission",
    "build_capital_reservation_proposal",
    "build_final_admission",
    "render_account_admission",
]
