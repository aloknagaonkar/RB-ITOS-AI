from __future__ import annotations

from dataclasses import replace
from typing import Any

RSI_STRATEGY_SOURCE = "RSI_EXTREME_REVERSAL_V1"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def apply_rsi_approval_policy(
    committee,
    *,
    candidate,
    strategy_source: str,
    duplicate: bool,
):
    if str(strategy_source or "") != RSI_STRATEGY_SOURCE:
        return committee

    reasons: list[str] = []
    ltp = _num(getattr(candidate, "ltp", None))
    bid = _num(getattr(candidate, "best_bid", None))
    ask = _num(getattr(candidate, "best_ask", None))
    liquidity_score = _num(
        getattr(candidate, "liquidity_score", None)
    )

    contract = getattr(candidate, "contract", None)
    token = _num(getattr(contract, "instrument_token", None))
    lot_size = _num(getattr(contract, "lot_size", None))
    symbol = str(getattr(contract, "tradingsymbol", "") or "")

    if token <= 0 or lot_size <= 0 or not symbol:
        reasons.append("INVALID_CONTRACT")
    if ltp <= 0:
        reasons.append("NON_EXECUTABLE_PRICE")
    if bid <= 0 or ask <= 0 or ask < bid:
        reasons.append("INVALID_BID_ASK")
    else:
        spread_pct = (
            (ask - bid) / ltp * 100.0
            if ltp > 0 else 999.0
        )
        if spread_pct > 4.0:
            reasons.append(
                f"SPREAD_TOO_WIDE:{spread_pct:.2f}%"
            )
    if liquidity_score < 10.0:
        reasons.append("INSUFFICIENT_LIQUIDITY")
    if duplicate:
        reasons.append("DUPLICATE_CANDIDATE")

    eligible = not reasons
    decision = "EXECUTE" if eligible else "REJECT"
    reason = (
        "RSI_HARD_GATES_PASS | "
        "OBSERVATIONAL_COMMITTEE_BYPASSED"
        if eligible
        else "RSI_HARD_GATE_FAIL | " + " | ".join(reasons)
    )

    return replace(
        committee,
        eligible=eligible,
        decision=decision,
        reason=reason,
        primary_decision=decision,
        primary_confidence_pct=100.0,
    )
