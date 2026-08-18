from __future__ import annotations

from typing import Mapping

from red_bar_lab.ui.strategy_contract_safeguards import (
    ContractSafeguardPolicy,
    POLICIES,
    apply_contract_safeguards as _apply_contract_safeguards_v1,
    render_contract_safeguards,
)


MARKET_CONTEXT_POLICY_VERSION = "MARKET-CONTEXT-REQUIRED-V1"


def apply_contract_safeguards(
    readiness: Mapping[str, object],
    *,
    policy: ContractSafeguardPolicy,
) -> dict[str, object]:
    """Require point-in-time spot and ATM before strike-distance admission."""
    base = _apply_contract_safeguards_v1(readiness, policy=policy)
    market_status = str(readiness.get("market_context_status") or "UNAVAILABLE").upper()
    spot = readiness.get("spot_price")
    atm = readiness.get("atm_strike")
    if market_status == "READY" and spot not in (None, "", "Unavailable") and atm not in (None, "", "Unavailable"):
        return {
            **base,
            "market_context_policy_version": MARKET_CONTEXT_POLICY_VERSION,
            "market_context_required": True,
        }

    rows = []
    safeguard_rows = []
    for raw in readiness.get("contract_rows") or []:
        row = dict(raw)
        existing = str(row.get("safeguard_reasons") or "NONE")
        reasons = [] if existing in {"", "NONE"} else [existing]
        reasons.append("MISSING_POINT_IN_TIME_SPOT_OR_ATM")
        row.update({
            "hard_safeguard_pass": False,
            "liquidity_ready": False,
            "decision": "WAIT",
            "strike_safeguard_status": "WAIT_MISSING_SPOT_OR_ATM",
            "safeguard_reasons": ", ".join(reasons),
        })
        rows.append(row)
        safeguard_rows.append({
            "instrument_key": row.get("instrument_key"),
            "instrument_token": row.get("instrument_token"),
            "trading_symbol": row.get("trading_symbol"),
            "strike": row.get("strike"),
            "spot": spot,
            "atm": atm,
            "hard_safeguard": "WAIT",
            "hard_reasons": row["safeguard_reasons"],
            "strike_check": "WAIT_MISSING_SPOT_OR_ATM",
        })

    return {
        **base,
        "outcome": "WAIT" if rows else str(base.get("outcome") or "UNAVAILABLE"),
        "reason": (
            "Point-in-time spot and ATM are required before strike-distance safeguards can admit contracts."
            if rows else str(base.get("reason") or "No contract rows are available.")
        ),
        "contract_rows": rows,
        "safeguard_rows": safeguard_rows,
        "ready_for_ranking": 0,
        "hard_safeguard_pass_count": 0,
        "execution_metadata_ready_count": 0,
        "strike_safeguard_status": "WAIT_MISSING_SPOT_OR_ATM",
        "market_context_policy_version": MARKET_CONTEXT_POLICY_VERSION,
        "market_context_required": True,
        "next_step": "Capture authoritative point-in-time spot and ATM; do not rank or hand off a contract.",
    }


__all__ = [
    "ContractSafeguardPolicy",
    "POLICIES",
    "apply_contract_safeguards",
    "render_contract_safeguards",
]
