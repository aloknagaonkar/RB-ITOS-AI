from __future__ import annotations

from typing import Mapping

import streamlit as st

from red_bar_lab.ui.strategy_contract_ranking import ContractRankingPolicy


_COMPONENTS = (
    ("spread_quality", "Spread quality", "spread_weight"),
    ("volume_quality", "Volume quality", "volume_weight"),
    ("oi_quality", "Open-interest quality", "oi_weight"),
    ("delta_quality", "Delta suitability", "delta_weight"),
    ("iv_evidence", "IV evidence", "iv_evidence_weight"),
)


def _weighted_contribution(row: Mapping[str, object], component: str, weight: float) -> float:
    try:
        quality_pct = float(row.get(component) or 0.0)
    except (TypeError, ValueError):
        quality_pct = 0.0
    return round(quality_pct * float(weight), 2)


def _arrow_safe_rows(rows) -> list[dict[str, object]]:
    values = [dict(row) for row in (rows or [])]
    if not values:
        return []
    columns = {key for row in values for key in row}
    for column in columns:
        present = [row.get(column) for row in values if row.get(column) is not None]
        kinds = {
            "bool" if isinstance(value, bool)
            else "number" if isinstance(value, (int, float))
            else "text"
            for value in present
        }
        if len(kinds) > 1:
            for row in values:
                value = row.get(column)
                row[column] = "" if value is None else str(value)
    return values


def _handoff_role(policy: ContractRankingPolicy, row: Mapping[str, object], index: int) -> str:
    ranked_role = str(row.get("ranking_decision") or "")
    if ranked_role in {"PRIMARY", "ENTRY_1", "ENTRY_2"}:
        return ranked_role
    if policy.strategy_id == "RSI_EXTREME_REVERSAL":
        return f"ENTRY_{index}"
    return "PRIMARY"


def build_selection_audit(
    ranking: Mapping[str, object],
    *,
    policy: ContractRankingPolicy,
) -> dict[str, object]:
    """Explain Section 5E ranking and prepare a non-persisted handoff view."""
    selected = [dict(row) for row in (ranking.get("selected_rows") or [])]
    ranked = [dict(row) for row in (ranking.get("ranked_rows") or [])]

    policy_rows = [
        {"policy field": "Strategy ID", "value": str(policy.strategy_id)},
        {"policy field": "Policy version", "value": str(policy.policy_version)},
        {"policy field": "Maximum proposed contracts", "value": str(policy.maximum_contracts)},
        {
            "policy field": "Preferred absolute delta",
            "value": (
                f"{policy.preferred_abs_delta_min:.2f} to "
                f"{policy.preferred_abs_delta_max:.2f}"
            ),
        },
    ]
    for _, label, weight_name in _COMPONENTS:
        policy_rows.append(
            {
                "policy field": f"{label} weight",
                "value": f"{getattr(policy, weight_name) * 100.0:.1f}%",
            }
        )

    audit_rows: list[dict[str, object]] = []
    for row in ranked:
        contributions = {
            f"{component}_contribution": _weighted_contribution(
                row, component, getattr(policy, weight_name)
            )
            for component, _, weight_name in _COMPONENTS
        }
        audit_rows.append(
            {
                "rank": row.get("rank"),
                "ranking_decision": row.get("ranking_decision"),
                "instrument_key": row.get("instrument_key"),
                "trading_symbol": row.get("trading_symbol"),
                "side": row.get("option_side"),
                "expiry": row.get("expiry"),
                "strike": row.get("strike"),
                "ltp": row.get("ltp"),
                "spread_pct": row.get("spread_pct"),
                "volume": row.get("volume"),
                "oi": row.get("oi"),
                "delta": row.get("delta"),
                "iv": row.get("iv"),
                "delta_evidence_status": row.get("delta_evidence_status"),
                "iv_evidence_status": row.get("iv_evidence_status"),
                "spread_quality": row.get("spread_quality"),
                "volume_quality": row.get("volume_quality"),
                "oi_quality": row.get("oi_quality"),
                "delta_quality": row.get("delta_quality"),
                "iv_evidence": row.get("iv_evidence"),
                **contributions,
                "score": row.get("score"),
            }
        )

    handoff_rows: list[dict[str, object]] = []
    for index, row in enumerate(selected, start=1):
        handoff_rows.append(
            {
                "strategy_id": policy.strategy_id,
                "policy_version": policy.policy_version,
                "signal_id": str(ranking.get("signal_id") or "Not created"),
                "bundle_id": str(ranking.get("bundle_id") or "Not created"),
                "snapshot_timestamp": str(
                    ranking.get("snapshot_timestamp") or "Unavailable"
                ),
                "requested_side": str(ranking.get("requested_side") or "Unavailable"),
                "role": _handoff_role(policy, row, index),
                "rank": row.get("rank", index),
                "instrument_key": row.get("instrument_key"),
                "trading_symbol": row.get("trading_symbol"),
                "expiry": row.get("expiry"),
                "strike": row.get("strike"),
                "ltp": row.get("ltp"),
                "score": row.get("score"),
                "handoff_state": "PROPOSED_READ_ONLY",
                "persisted": False,
                "reserved": False,
                "bundle_consumed": False,
                "executed": False,
            }
        )

    if handoff_rows:
        outcome = "HANDOFF_READY_READ_ONLY"
        reason = (
            f"{len(handoff_rows)} strategy-owned proposed contract(s) are fully auditable "
            "and may be inspected by Section 6 candidate readiness."
        )
        next_step = (
            "Evaluate the proposed records in Section 6; do not persist or execute yet."
        )
    else:
        outcome = "NO_HANDOFF"
        reason = str(ranking.get("reason") or "No proposed contract is available.")
        next_step = (
            "Resolve the first blocked Section 5A-5E prerequisite before Section 6."
        )

    return {
        "outcome": outcome,
        "reason": reason,
        "next_step": next_step,
        "strategy_id": policy.strategy_id,
        "policy_version": policy.policy_version,
        "selection_outcome": str(ranking.get("outcome") or "UNAVAILABLE"),
        "selected_count": len(handoff_rows),
        "policy_rows": policy_rows,
        "audit_rows": audit_rows,
        "handoff_rows": handoff_rows,
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "executed": False,
    }


def render_selection_audit(result: Mapping[str, object]) -> None:
    st.markdown("##### 5E Audit. Ranking Explanation & Read-Only Handoff")
    st.caption(
        "Explains the Section 5E score components and exposes a non-persisted handoff "
        "view for Section 6. No candidate, reservation, bundle consumption, position, "
        "or order is created."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Audit outcome", str(result["outcome"]))
    c2.metric("Selection outcome", str(result["selection_outcome"]))
    c3.metric("Policy version", str(result["policy_version"]))
    c4.metric("Handoff proposals", int(result["selected_count"]))

    st.write(f"**Decision reason:** {result['reason']}")
    st.write(f"**Next architectural step:** {result['next_step']}")
    st.write("**Persisted / reserved / bundle consumed / executed:** NO / NO / NO / NO")

    with st.expander("View active strategy-owned ranking policy"):
        st.dataframe(
            _arrow_safe_rows(result.get("policy_rows") or []),
            width="stretch",
            hide_index=True,
        )

    with st.expander("View score-component audit"):
        rows = _arrow_safe_rows(result.get("audit_rows") or [])
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No contracts were available for score auditing.")

    with st.expander("View proposed read-only handoff records"):
        rows = _arrow_safe_rows(result.get("handoff_rows") or [])
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No contract is ready for Section 6 candidate readiness.")
