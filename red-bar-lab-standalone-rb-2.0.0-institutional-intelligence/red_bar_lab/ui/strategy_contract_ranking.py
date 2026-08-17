from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import streamlit as st


@dataclass(frozen=True)
class ContractRankingPolicy:
    strategy_id: str
    policy_version: str
    maximum_contracts: int
    spread_weight: float = 0.35
    volume_weight: float = 0.25
    oi_weight: float = 0.25
    delta_weight: float = 0.10
    iv_evidence_weight: float = 0.05
    preferred_abs_delta_min: float = 0.30
    preferred_abs_delta_max: float = 0.70


POLICIES: Mapping[str, ContractRankingPolicy] = {
    "RED_BAR": ContractRankingPolicy("RED_BAR", "RB-CONTRACT-RANK-V1", 1),
    "DIRECTIONAL_REGIME_INTELLIGENCE": ContractRankingPolicy(
        "DIRECTIONAL_REGIME_INTELLIGENCE", "DRI-CONTRACT-RANK-V1", 1
    ),
    "RSI_EXTREME_REVERSAL": ContractRankingPolicy(
        "RSI_EXTREME_REVERSAL", "RSI-CONTRACT-RANK-V1", 2
    ),
}


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _quality_low(value: float | None, maximum: float) -> float:
    if value is None or value < 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - value / maximum))


def _log_quality(value: float | None, maximum: float) -> float:
    if value is None or value <= 0 or maximum <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log1p(value) / math.log1p(maximum)))


def _delta_quality(value: float | None, policy: ContractRankingPolicy) -> float:
    if value is None:
        return 0.0
    absolute = abs(value)
    low = policy.preferred_abs_delta_min
    high = policy.preferred_abs_delta_max
    if low <= absolute <= high:
        midpoint = (low + high) / 2.0
        half_width = max((high - low) / 2.0, 0.01)
        return max(0.5, 1.0 - abs(absolute - midpoint) / (2.0 * half_width))
    distance = low - absolute if absolute < low else absolute - high
    return max(0.0, 0.5 - distance)


def rank_strategy_contracts(
    readiness: Mapping[str, object],
    *,
    policy: ContractRankingPolicy,
) -> dict[str, object]:
    """Rank Section 5A-ready rows without persistence, reservation, or execution."""
    readiness_outcome = str(readiness.get("outcome") or "UNAVAILABLE")
    base = {
        "strategy_id": policy.strategy_id,
        "policy_version": policy.policy_version,
        "maximum_contracts": policy.maximum_contracts,
        "bundle_id": str(readiness.get("bundle_id") or "Not created"),
        "signal_id": str(readiness.get("signal_id") or "Not created"),
        "requested_side": str(readiness.get("requested_side") or "Unavailable"),
        "snapshot_timestamp": str(readiness.get("snapshot_timestamp") or "Unavailable"),
        "ranked_rows": [],
        "selected_rows": [],
        "selected_count": 0,
        "eligible_count": 0,
        "persisted": False,
        "reserved": False,
        "executed": False,
    }
    if readiness_outcome != "READY_FOR_RANKING":
        return {
            **base,
            "outcome": readiness_outcome,
            "reason": str(readiness.get("reason") or "Section 5A did not permit ranking."),
            "next_step": "Resolve Section 5A readiness before ranking contracts.",
        }

    eligible = [
        dict(row)
        for row in (readiness.get("contract_rows") or [])
        if bool(dict(row).get("liquidity_ready"))
    ]
    if not eligible:
        return {
            **base,
            "outcome": "REJECTED",
            "reason": "No liquidity-ready strategy-owned contracts are available for ranking.",
            "next_step": "Wait for a new time-valid snapshot with complete liquidity fields.",
        }

    max_volume = max((_number(row.get("volume")) or 0.0 for row in eligible), default=0.0)
    max_oi = max((_number(row.get("oi")) or 0.0 for row in eligible), default=0.0)
    scored: list[dict[str, object]] = []
    for row in eligible:
        spread_pct = _number(row.get("spread_pct"))
        volume = _number(row.get("volume"))
        oi = _number(row.get("oi"))
        delta = _number(row.get("delta"))
        iv = _number(row.get("iv"))
        components = {
            "spread_quality": _quality_low(spread_pct, 10.0),
            "volume_quality": _log_quality(volume, max_volume),
            "oi_quality": _log_quality(oi, max_oi),
            "delta_quality": _delta_quality(delta, policy),
            "iv_evidence": 1.0 if iv is not None and iv >= 0 else 0.0,
        }
        score = 100.0 * (
            components["spread_quality"] * policy.spread_weight
            + components["volume_quality"] * policy.volume_weight
            + components["oi_quality"] * policy.oi_weight
            + components["delta_quality"] * policy.delta_weight
            + components["iv_evidence"] * policy.iv_evidence_weight
        )
        scored.append(
            {
                **row,
                **{key: round(value * 100.0, 2) for key, value in components.items()},
                "score": round(score, 2),
                "ranking_decision": "ELIGIBLE",
            }
        )

    scored.sort(
        key=lambda row: (
            -float(row["score"]),
            _number(row.get("spread_pct")) if _number(row.get("spread_pct")) is not None else float("inf"),
            -(_number(row.get("volume")) or 0.0),
            -(_number(row.get("oi")) or 0.0),
            _number(row.get("strike")) if _number(row.get("strike")) is not None else float("inf"),
            str(row.get("instrument_key") or ""),
        )
    )

    distinct: list[dict[str, object]] = []
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
            row["ranking_decision"] = "PRIMARY" if selected_index == 1 else "FALLBACK"

    if len(selected) >= policy.maximum_contracts:
        outcome = "SELECTED"
        reason = f"{len(selected)} distinct strategy-owned contract(s) proposed under {policy.policy_version}."
    elif selected:
        outcome = "PARTIAL"
        reason = (
            f"Only {len(selected)} distinct eligible contract(s) are available for a "
            f"capacity of {policy.maximum_contracts}."
        )
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
            "Expose the proposed selection to a later independent risk/candidate handoff."
            if selected
            else "Wait for a new eligible contract snapshot."
        ),
    }


def render_strategy_contract_ranking(result: Mapping[str, object]) -> None:
    st.markdown("#### 5B. Strategy-Owned Ranking & Proposed Selection")
    st.caption(
        "Read-only deterministic ranking. Proposed contracts are not persisted, reserved, "
        "consumed, sized, or executed."
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
        summary_rows = []
        for index, row in enumerate(selected, start=1):
            summary_rows.append(
                {
                    "role": "PRIMARY" if index == 1 else "FALLBACK",
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
            )
        st.dataframe(summary_rows, width="stretch", hide_index=True)
    else:
        st.info("No contract has been proposed by Section 5B.")

    with st.expander("View complete deterministic ranking"):
        rows = list(result.get("ranked_rows") or [])
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No contracts were ranked.")
