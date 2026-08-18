from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import streamlit as st


@dataclass(frozen=True)
class ContractRankingPolicy:
    strategy_id: str
    policy_version: str
    maximum_contracts: int
    spread_weight: float = 0.30
    volume_weight: float = 0.25
    oi_weight: float = 0.25
    delta_weight: float = 0.20


POLICIES: Mapping[str, ContractRankingPolicy] = {
    "RED_BAR": ContractRankingPolicy("RED_BAR", "RB-CONTRACT-RANKING-V1", 1),
    "DIRECTIONAL_REGIME": ContractRankingPolicy("DIRECTIONAL_REGIME", "DRI-CONTRACT-RANKING-V1", 1),
    "DIRECTIONAL_REGIME_INTELLIGENCE": ContractRankingPolicy("DIRECTIONAL_REGIME_INTELLIGENCE", "DRI-CONTRACT-RANKING-V1", 1),
    "RSI_EXTREME_REVERSAL": ContractRankingPolicy("RSI_EXTREME_REVERSAL", "RSI-CONTRACT-RANKING-V1", 2),
}


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_positive(values: list[float]) -> list[float]:
    if not values:
        return []
    maximum = max(values)
    if maximum <= 0:
        return [0.0 for _ in values]
    return [value / maximum for value in values]


def _normalize_inverse(values: list[float]) -> list[float]:
    if not values:
        return []
    maximum = max(values)
    minimum = min(values)
    if maximum == minimum:
        return [1.0 for _ in values]
    return [1.0 - ((value - minimum) / (maximum - minimum)) for value in values]


def _selected_role(policy: ContractRankingPolicy, position: int) -> str:
    if policy.maximum_contracts == 1:
        return "ENTRY_1"
    return f"ENTRY_{position}"


def rank_strategy_contracts(
    readiness: Mapping[str, object],
    *,
    policy: ContractRankingPolicy,
) -> dict[str, object]:
    rows = [dict(row) for row in (readiness.get("contract_rows") or [])]
    eligible = [
        row for row in rows
        if bool(row.get("hard_safeguard_pass", row.get("liquidity_ready")))
        and bool(row.get("execution_metadata_ready", row.get("execution_metadata_complete", True)))
    ]
    base = {
        **dict(readiness),
        "policy_version": policy.policy_version,
        "maximum_contracts": policy.maximum_contracts,
        "eligible_count": len(eligible),
        "selected_count": 0,
        "ranked_rows": [],
        "selected_rows": [],
    }
    if not eligible:
        return {
            **base,
            "outcome": "REJECTED",
            "reason": "No contract passed the absolute safeguards and execution-metadata checks.",
            "next_step": "Wait for a new eligible contract snapshot.",
        }

    spreads = [_number(row.get("spread_pct"), 999.0) for row in eligible]
    volumes = [_number(row.get("volume")) for row in eligible]
    open_interest = [_number(row.get("oi")) for row in eligible]
    deltas = [abs(_number(row.get("delta"), 0.5)) for row in eligible]
    spread_scores = _normalize_inverse(spreads)
    volume_scores = _normalize_positive(volumes)
    oi_scores = _normalize_positive(open_interest)
    delta_scores = [max(0.0, 1.0 - abs(value - 0.5) / 0.5) for value in deltas]

    scored = []
    for index, row in enumerate(eligible):
        score = 100.0 * (
            policy.spread_weight * spread_scores[index]
            + policy.volume_weight * volume_scores[index]
            + policy.oi_weight * oi_scores[index]
            + policy.delta_weight * delta_scores[index]
        )
        scored.append({
            **row,
            "spread_score": round(spread_scores[index] * 100.0, 3),
            "volume_score": round(volume_scores[index] * 100.0, 3),
            "oi_score": round(oi_scores[index] * 100.0, 3),
            "delta_score": round(delta_scores[index] * 100.0, 3),
            "score": round(score, 3),
            "ranking_decision": "ELIGIBLE",
        })

    scored.sort(
        key=lambda row: (
            -_number(row.get("score")),
            _number(row.get("spread_pct"), 999.0),
            -_number(row.get("volume")),
            -_number(row.get("oi")),
            _number(row.get("strike")),
            str(row.get("instrument_key") or row.get("trading_symbol") or ""),
        )
    )
    distinct = []
    seen: set[str] = set()
    for row in scored:
        identity = str(row.get("instrument_key") or row.get("trading_symbol") or "")
        if not identity or identity in seen:
            row["ranking_decision"] = "DUPLICATE_EXCLUDED"
            continue
        seen.add(identity)
        distinct.append(row)

    selected = distinct[: policy.maximum_contracts]
    selected_identity_to_position = {
        str(row.get("instrument_key") or row.get("trading_symbol") or ""): position
        for position, row in enumerate(selected, start=1)
    }
    for index, row in enumerate(scored, start=1):
        row["rank"] = index
        if row.get("ranking_decision") == "DUPLICATE_EXCLUDED":
            continue
        identity = str(row.get("instrument_key") or row.get("trading_symbol") or "")
        selected_index = selected_identity_to_position.get(identity)
        if selected_index is not None:
            row["ranking_decision"] = _selected_role(policy, selected_index)

    if len(selected) >= policy.maximum_contracts:
        outcome = "SELECTED"
        reason = f"{len(selected)} distinct strategy-owned contract(s) proposed under {policy.policy_version}."
    elif selected:
        outcome = "PARTIAL"
        reason = f"Only {len(selected)} distinct eligible contract(s) are available for a capacity of {policy.maximum_contracts}."
    else:
        outcome = "REJECTED"
        reason = "No distinct eligible contract remained after deterministic ranking."

    return {
        **base,
        "outcome": outcome,
        "reason": reason,
        "eligible_count": len(eligible),
        "selected_count": len(selected),
        "ranked_rows": scored,
        "selected_rows": [dict(row) for row in selected],
        "next_step": (
            "Expose the proposed selection to Section 6 candidate readiness."
            if selected else "Wait for a new eligible contract snapshot."
        ),
    }


def render_strategy_contract_ranking(result: Mapping[str, object]) -> None:
    st.markdown("#### 5E. Deterministic Ranking & Proposed Selection")
    st.caption(
        "Runs only after 5A data readiness, 5B market context, 5C execution metadata "
        "and 5D absolute safeguards. Proposed contracts remain read-only."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(result["outcome"]))
    c2.metric("Policy", str(result["policy_version"]))
    c3.metric("Eligible", int(result["eligible_count"]))
    c4.metric("Proposed", f"{result['selected_count']} / {result['maximum_contracts']}")
    st.write(f"**Decision reason:** {result['reason']}")
    st.write(f"**Next architectural step:** {result['next_step']}")
    st.write("**Persisted / reserved / executed:** NO / NO / NO")

    selected = list(result.get("selected_rows") or [])
    if selected:
        st.dataframe(
            [
                {
                    "role": row.get("ranking_decision") or _selected_role(POLICIES[str(result.get("strategy_id"))], index),
                    "rank": row.get("rank", index),
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
                    "score": row.get("score"),
                }
                for index, row in enumerate(selected, start=1)
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No contract has been proposed by Section 5E.")

    with st.expander("View complete deterministic ranking"):
        rows = list(result.get("ranked_rows") or [])
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No contracts were ranked.")
