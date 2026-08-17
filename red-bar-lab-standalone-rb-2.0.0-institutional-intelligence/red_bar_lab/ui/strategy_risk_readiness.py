from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import streamlit as st


@dataclass(frozen=True)
class RiskReadinessPolicy:
    policy_version: str = "ACCOUNT-RISK-READINESS-V1"
    default_lots: int = 1
    require_available_cash: bool = True
    require_daily_loss_limit: bool = True
    require_portfolio_exposure_limit: bool = True


DEFAULT_POLICY = RiskReadinessPolicy()


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "active"}:
        return True
    if text in {"0", "false", "no", "off", "inactive"}:
        return False
    return None


def _position_keys(context: Mapping[str, object]) -> set[str]:
    values = context.get("open_position_identity_keys") or []
    return {str(value) for value in values if value not in (None, "")}


def _check(name: str, status: str, detail: str) -> dict[str, object]:
    return {"check": name, "status": status, "detail": detail}


def build_risk_readiness(
    candidate_result: Mapping[str, object],
    *,
    risk_context: Mapping[str, object] | None = None,
    policy: RiskReadinessPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    """Evaluate account and risk readiness without reservation, persistence or execution."""
    context = dict(risk_context or {})
    available_cash = _number(context.get("available_cash"))
    daily_realized_pnl = _number(context.get("daily_realized_pnl"))
    daily_unrealized_pnl = _number(context.get("daily_unrealized_pnl"))
    daily_loss_limit = _number(context.get("daily_loss_limit"))
    strategy_loss_consumed = _number(context.get("strategy_loss_consumed"))
    strategy_loss_limit = _number(context.get("strategy_loss_limit"))
    portfolio_exposure = _number(context.get("portfolio_exposure"))
    maximum_portfolio_exposure = _number(context.get("maximum_portfolio_exposure"))
    cooldown_active = _bool(context.get("cooldown_active"))
    emergency_stop = _bool(context.get("emergency_stop"))
    open_positions = int(_number(context.get("open_positions")) or 0)
    maximum_open_positions = _number(context.get("maximum_open_positions"))
    proposed_lots = int(_number(context.get("proposed_lots")) or policy.default_lots)
    existing_position_keys = _position_keys(context)

    rows: list[dict[str, object]] = []
    for raw in candidate_result.get("candidates") or []:
        candidate = dict(raw)
        checks: list[dict[str, object]] = []
        wait_reasons: list[str] = []
        block_reasons: list[str] = []

        candidate_ready = str(candidate.get("validation_outcome")) == "HANDOFF_READY"
        checks.append(_check(
            "Candidate handoff readiness",
            "PASS" if candidate_ready else "BLOCK",
            str(candidate.get("exact_reason") or candidate.get("validation_outcome")),
        ))
        if not candidate_ready:
            block_reasons.append("CANDIDATE_NOT_HANDOFF_READY")

        ltp = _number(candidate.get("ltp"))
        lot_size = _number(candidate.get("lot_size"))
        premium_per_lot = ltp * lot_size if ltp is not None and lot_size is not None else None
        required_premium = premium_per_lot * proposed_lots if premium_per_lot is not None else None

        if required_premium is None:
            checks.append(_check("Premium requirement", "WAIT", "MISSING_LTP_OR_LOT_SIZE"))
            wait_reasons.append("MISSING_LTP_OR_LOT_SIZE")
        else:
            checks.append(_check("Premium requirement", "PASS", f"required={required_premium:.2f}"))

        if available_cash is None:
            status = "WAIT" if policy.require_available_cash else "INFO"
            checks.append(_check("Available cash", status, "ACCOUNT_CASH_UNAVAILABLE"))
            if policy.require_available_cash:
                wait_reasons.append("ACCOUNT_CASH_UNAVAILABLE")
        elif required_premium is not None and available_cash < required_premium:
            checks.append(_check("Available cash", "BLOCK", f"available={available_cash:.2f}; required={required_premium:.2f}"))
            block_reasons.append("INSUFFICIENT_CAPITAL")
        else:
            checks.append(_check("Available cash", "PASS", f"available={available_cash:.2f}"))

        total_daily_pnl = None
        if daily_realized_pnl is not None or daily_unrealized_pnl is not None:
            total_daily_pnl = (daily_realized_pnl or 0.0) + (daily_unrealized_pnl or 0.0)
        if daily_loss_limit is None:
            status = "WAIT" if policy.require_daily_loss_limit else "INFO"
            checks.append(_check("Daily loss limit", status, "DAILY_LOSS_LIMIT_UNAVAILABLE"))
            if policy.require_daily_loss_limit:
                wait_reasons.append("DAILY_LOSS_LIMIT_UNAVAILABLE")
        elif total_daily_pnl is None:
            checks.append(_check("Daily loss consumed", "WAIT", "DAILY_PNL_UNAVAILABLE"))
            wait_reasons.append("DAILY_PNL_UNAVAILABLE")
        elif total_daily_pnl <= -abs(daily_loss_limit):
            checks.append(_check("Daily loss consumed", "BLOCK", f"daily_pnl={total_daily_pnl:.2f}; limit={daily_loss_limit:.2f}"))
            block_reasons.append("DAILY_LOSS_LIMIT_REACHED")
        else:
            checks.append(_check("Daily loss consumed", "PASS", f"daily_pnl={total_daily_pnl:.2f}; limit={daily_loss_limit:.2f}"))

        if strategy_loss_limit is None or strategy_loss_consumed is None:
            checks.append(_check("Strategy loss limit", "WAIT", "STRATEGY_LOSS_CONTEXT_UNAVAILABLE"))
            wait_reasons.append("STRATEGY_LOSS_CONTEXT_UNAVAILABLE")
        elif strategy_loss_consumed >= abs(strategy_loss_limit):
            checks.append(_check("Strategy loss limit", "BLOCK", f"consumed={strategy_loss_consumed:.2f}; limit={strategy_loss_limit:.2f}"))
            block_reasons.append("STRATEGY_LOSS_LIMIT_REACHED")
        else:
            checks.append(_check("Strategy loss limit", "PASS", f"consumed={strategy_loss_consumed:.2f}; limit={strategy_loss_limit:.2f}"))

        projected_exposure = portfolio_exposure + required_premium if portfolio_exposure is not None and required_premium is not None else None
        if maximum_portfolio_exposure is None:
            status = "WAIT" if policy.require_portfolio_exposure_limit else "INFO"
            checks.append(_check("Portfolio exposure limit", status, "PORTFOLIO_EXPOSURE_LIMIT_UNAVAILABLE"))
            if policy.require_portfolio_exposure_limit:
                wait_reasons.append("PORTFOLIO_EXPOSURE_LIMIT_UNAVAILABLE")
        elif projected_exposure is None:
            checks.append(_check("Projected portfolio exposure", "WAIT", "PORTFOLIO_EXPOSURE_UNAVAILABLE"))
            wait_reasons.append("PORTFOLIO_EXPOSURE_UNAVAILABLE")
        elif projected_exposure > maximum_portfolio_exposure:
            checks.append(_check("Projected portfolio exposure", "BLOCK", f"projected={projected_exposure:.2f}; limit={maximum_portfolio_exposure:.2f}"))
            block_reasons.append("PORTFOLIO_EXPOSURE_LIMIT")
        else:
            checks.append(_check("Projected portfolio exposure", "PASS", f"projected={projected_exposure:.2f}; limit={maximum_portfolio_exposure:.2f}"))

        if maximum_open_positions is None:
            checks.append(_check("Open-position capacity", "WAIT", "MAXIMUM_OPEN_POSITIONS_UNAVAILABLE"))
            wait_reasons.append("MAXIMUM_OPEN_POSITIONS_UNAVAILABLE")
        elif open_positions >= maximum_open_positions:
            checks.append(_check("Open-position capacity", "BLOCK", f"open={open_positions}; limit={int(maximum_open_positions)}"))
            block_reasons.append("OPEN_POSITION_LIMIT")
        else:
            checks.append(_check("Open-position capacity", "PASS", f"open={open_positions}; limit={int(maximum_open_positions)}"))

        identity_key = str(candidate.get("identity_key") or "")
        duplicate_position = bool(identity_key and identity_key in existing_position_keys)
        checks.append(_check(
            "Duplicate-position risk",
            "BLOCK" if duplicate_position else "PASS" if existing_position_keys else "WAIT",
            "DUPLICATE_OPEN_POSITION" if duplicate_position else "UNIQUE" if existing_position_keys else "OPEN_POSITION_IDENTITIES_UNAVAILABLE",
        ))
        if duplicate_position:
            block_reasons.append("DUPLICATE_OPEN_POSITION")
        elif not existing_position_keys:
            wait_reasons.append("OPEN_POSITION_IDENTITIES_UNAVAILABLE")

        if cooldown_active is None:
            checks.append(_check("Cooldown", "WAIT", "COOLDOWN_STATE_UNAVAILABLE"))
            wait_reasons.append("COOLDOWN_STATE_UNAVAILABLE")
        elif cooldown_active:
            checks.append(_check("Cooldown", "BLOCK", "COOLDOWN_ACTIVE"))
            block_reasons.append("COOLDOWN_ACTIVE")
        else:
            checks.append(_check("Cooldown", "PASS", "INACTIVE"))

        if emergency_stop is None:
            checks.append(_check("Emergency stop", "WAIT", "EMERGENCY_STOP_STATE_UNAVAILABLE"))
            wait_reasons.append("EMERGENCY_STOP_STATE_UNAVAILABLE")
        elif emergency_stop:
            checks.append(_check("Emergency stop", "BLOCK", "EMERGENCY_STOP_ACTIVE"))
            block_reasons.append("EMERGENCY_STOP_ACTIVE")
        else:
            checks.append(_check("Emergency stop", "PASS", "INACTIVE"))

        if block_reasons:
            outcome = "RISK_BLOCKED"
        elif wait_reasons:
            outcome = "WAIT"
        else:
            outcome = "RISK_READY_READ_ONLY"

        rows.append({
            "candidate_id": candidate.get("candidate_id"),
            "strategy_id": candidate.get("strategy_id"),
            "bundle_id": candidate.get("bundle_id"),
            "role": candidate.get("role"),
            "contract_side": candidate.get("contract_side"),
            "trading_symbol": candidate.get("trading_symbol"),
            "lot_size": lot_size,
            "proposed_lots": proposed_lots,
            "ltp": ltp,
            "premium_per_lot": round(premium_per_lot, 2) if premium_per_lot is not None else None,
            "required_premium": round(required_premium, 2) if required_premium is not None else None,
            "available_cash": available_cash,
            "projected_portfolio_exposure": round(projected_exposure, 2) if projected_exposure is not None else None,
            "risk_outcome": outcome,
            "exact_reason": ", ".join(block_reasons or wait_reasons) if (block_reasons or wait_reasons) else "ALL_ACCOUNT_AND_RISK_CHECKS_PASSED",
            "checks": checks,
            "policy_action": "OBSERVE_ONLY",
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
            "next_step": "Execution decision gate may inspect this read-only result." if outcome == "RISK_READY_READ_ONLY" else "Resolve the exact account/risk reason before execution gating.",
        })

    ready = sum(row["risk_outcome"] == "RISK_READY_READ_ONLY" for row in rows)
    waiting = sum(row["risk_outcome"] == "WAIT" for row in rows)
    blocked = sum(row["risk_outcome"] == "RISK_BLOCKED" for row in rows)
    return {
        "outcome": "RISK_READY_READ_ONLY" if ready and not waiting and not blocked else "RISK_BLOCKED" if blocked else "WAIT" if waiting else "NOT_ELIGIBLE",
        "policy_version": policy.policy_version,
        "candidates_evaluated": len(rows),
        "risk_ready_count": ready,
        "waiting_count": waiting,
        "blocked_count": blocked,
        "risk_context_available": bool(context),
        "rows": rows,
        "policy_action": "OBSERVE_ONLY",
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


def render_risk_readiness(result: Mapping[str, object]) -> None:
    st.markdown("### 7. Account and Risk Readiness")
    st.caption(
        "Read-only affordability, exposure and loss-limit evaluation. No funds, contracts, "
        "positions or bundles are reserved or mutated."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(result.get("outcome") or "NOT_ELIGIBLE"))
    c2.metric("Risk ready", int(result.get("risk_ready_count") or 0))
    c3.metric("Waiting", int(result.get("waiting_count") or 0))
    c4.metric("Blocked", int(result.get("blocked_count") or 0))
    st.write(f"**Risk policy:** {result.get('policy_version')}")
    st.write(f"**Risk context available:** {'YES' if result.get('risk_context_available') else 'NO'}")
    st.write("**Policy action:** OBSERVE_ONLY — no persistence, reservation, bundle consumption or order submission")

    rows = list(result.get("rows") or [])
    if not rows:
        st.info("No Section 6 candidate is available for account/risk evaluation.")
        return

    summary = [
        {key: row.get(key) for key in (
            "candidate_id", "strategy_id", "bundle_id", "role", "contract_side",
            "trading_symbol", "lot_size", "proposed_lots", "ltp", "required_premium",
            "available_cash", "projected_portfolio_exposure", "risk_outcome", "exact_reason"
        )}
        for row in rows
    ]
    st.dataframe(summary, width="stretch", hide_index=True)
    for row in rows:
        with st.expander(f"Why is {row.get('candidate_id')} risk-ready, waiting, or blocked?"):
            st.dataframe(list(row.get("checks") or []), width="stretch", hide_index=True)
            st.write(f"**Outcome:** {row.get('risk_outcome')}")
            st.write(f"**Exact reason:** {row.get('exact_reason')}")
            st.write(f"**Next step:** {row.get('next_step')}")
