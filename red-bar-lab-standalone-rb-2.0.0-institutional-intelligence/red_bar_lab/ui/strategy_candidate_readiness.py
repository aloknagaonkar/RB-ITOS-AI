from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import math
from typing import Mapping

import pandas as pd
import streamlit as st


_VALID_STRATEGIES = frozenset({"RED_BAR", "DIRECTIONAL_REGIME", "RSI_EXTREME_REVERSAL"})
_CAPACITY = {"RED_BAR": 1, "DIRECTIONAL_REGIME": 1, "RSI_EXTREME_REVERSAL": 2}
_VALID_ROLES = {
    "RED_BAR": frozenset({"PRIMARY"}),
    "DIRECTIONAL_REGIME": frozenset({"PRIMARY"}),
    "RSI_EXTREME_REVERSAL": frozenset({"ENTRY_1", "ENTRY_2"}),
}


@dataclass(frozen=True)
class CandidateScorePolicy:
    policy_version: str = "CANDIDATE-SCORE-V1"
    contract_score_weight: float = 0.30
    spread_weight: float = 0.10
    volume_weight: float = 0.10
    oi_weight: float = 0.10
    delta_weight: float = 0.05
    iv_weight: float = 0.05
    atm_weight: float = 0.10
    snapshot_freshness_weight: float = 0.10
    bundle_freshness_weight: float = 0.05
    metadata_weight: float = 0.05


DEFAULT_SCORE_POLICY = CandidateScorePolicy()


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, "", "Unavailable", "Not created"):
        return None
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    if result.tzinfo is None:
        return result.tz_localize("Asia/Kolkata")
    return result.tz_convert("Asia/Kolkata")


def _row_value(rows, label: str):
    target = label.strip().lower()
    for raw in rows or []:
        row = dict(raw)
        name = str(row.get("field") or row.get("check") or "").strip().lower()
        if name == target:
            return row.get("value") or row.get("detail")
    return None


def _candidate_identity(strategy_id: str, bundle_id: str, token: str, role: str) -> tuple[str, str]:
    raw = f"{strategy_id}|{bundle_id}|{token}|{role}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    prefix = {"RED_BAR": "RB", "DIRECTIONAL_REGIME": "DRI", "RSI_EXTREME_REVERSAL": "RSI"}.get(strategy_id, "UNK")
    bundle_fragment = "".join(ch for ch in bundle_id if ch.isalnum())[-12:] or "BUNDLE"
    token_fragment = "".join(ch for ch in token if ch.isalnum())[-12:] or "TOKEN"
    readable_role = role.replace("_", "-")
    return f"{prefix}-CAND-{bundle_fragment}-{token_fragment}-{readable_role}", digest


def _quality(value: object) -> tuple[float, str]:
    number = _number(value)
    return (max(0.0, min(100.0, number)), "AVAILABLE") if number is not None else (0.0, "UNAVAILABLE")


def _metadata_quality(row: Mapping[str, object]) -> tuple[float, str, str]:
    checks = {
        "instrument_token": row.get("instrument_token") not in (None, "", "Unavailable"),
        "trading_symbol": row.get("trading_symbol") not in (None, "", "Unavailable"),
        "exchange": row.get("exchange") not in (None, "", "Unavailable"),
        "lot_size": (_number(row.get("lot_size")) or 0) > 0,
        "tick_size": (_number(row.get("tick_size")) or 0) > 0,
    }
    score = 100.0 * sum(checks.values()) / len(checks)
    missing = [name for name, passed in checks.items() if not passed]
    return score, "AVAILABLE", "NONE" if not missing else ", ".join(f"MISSING_{name.upper()}" for name in missing)


def _component(name: str, raw: object, normalized: float, weight: float, status: str, explanation: str) -> dict[str, object]:
    contribution = normalized * weight
    return {
        "component": name,
        "raw_value": raw,
        "normalized_score": round(normalized, 2),
        "weight_pct": round(weight * 100.0, 2),
        "contribution": round(contribution, 2),
        "status": status,
        "explanation": explanation,
    }


def _score_candidate(
    row: Mapping[str, object],
    *,
    snapshot_age_seconds: float | None,
    maximum_snapshot_age_seconds: float | None,
    bundle_remaining_seconds: float | None,
    bundle_lifetime_seconds: float | None,
    policy: CandidateScorePolicy,
) -> tuple[float, list[dict[str, object]]]:
    components: list[dict[str, object]] = []
    values = [
        ("Section 5 contract quality", row.get("score"), "contract_score_weight", "Section 5 deterministic contract score."),
        ("Spread quality", row.get("spread_quality"), "spread_weight", "Lower spread quality from Section 5."),
        ("Volume quality", row.get("volume_quality"), "volume_weight", "Relative volume quality from Section 5."),
        ("Open-interest quality", row.get("oi_quality"), "oi_weight", "Relative OI quality from Section 5."),
        ("Delta suitability", row.get("delta_quality"), "delta_weight", "Strategy-owned delta suitability evidence."),
        ("IV evidence", row.get("iv_evidence"), "iv_weight", "IV availability/suitability evidence."),
    ]
    for name, raw, weight_name, explanation in values:
        normalized, status = _quality(raw)
        components.append(_component(name, raw, normalized, getattr(policy, weight_name), status, explanation))

    distance = _number(row.get("strike_distance_steps"))
    if distance is None:
        atm_score, atm_status = 0.0, "UNAVAILABLE"
    else:
        atm_score, atm_status = max(0.0, 100.0 * (1.0 - min(distance, 2.0) / 2.0)), "AVAILABLE"
    components.append(_component("ATM proximity", distance, atm_score, policy.atm_weight, atm_status, "Distance from point-in-time ATM in strike steps."))

    if snapshot_age_seconds is None or not maximum_snapshot_age_seconds:
        snapshot_score, snapshot_status = 0.0, "UNAVAILABLE"
    else:
        snapshot_score = max(0.0, 100.0 * (1.0 - snapshot_age_seconds / maximum_snapshot_age_seconds))
        snapshot_status = "AVAILABLE"
    components.append(_component("Snapshot freshness", snapshot_age_seconds, snapshot_score, policy.snapshot_freshness_weight, snapshot_status, "Remaining freshness inside the Section 5 snapshot-age policy."))

    if bundle_remaining_seconds is None or not bundle_lifetime_seconds or bundle_lifetime_seconds <= 0:
        bundle_score, bundle_status = 0.0, "UNAVAILABLE"
    else:
        bundle_score = max(0.0, min(100.0, 100.0 * bundle_remaining_seconds / bundle_lifetime_seconds))
        bundle_status = "AVAILABLE"
    components.append(_component("Bundle freshness remaining", bundle_remaining_seconds, bundle_score, policy.bundle_freshness_weight, bundle_status, "Remaining fraction of the strategy-owned bundle lifetime."))

    metadata_score, metadata_status, metadata_reason = _metadata_quality(row)
    components.append(_component("Execution metadata completeness", metadata_reason, metadata_score, policy.metadata_weight, metadata_status, "Token, symbol, exchange, lot size and tick size completeness."))
    return round(sum(float(item["contribution"]) for item in components), 2), components


def build_candidate_readiness(
    *,
    gate: Mapping[str, object],
    resolution: Mapping[str, object] | None,
    safeguarded: Mapping[str, object],
    ranking: Mapping[str, object],
    option_direction: Mapping[str, object] | None = None,
    evaluation_timestamp: object = None,
    score_policy: CandidateScorePolicy = DEFAULT_SCORE_POLICY,
) -> dict[str, object]:
    """Validate, score and expose candidates without persistence or mutation."""
    strategy_id = str(ranking.get("strategy_id") or gate.get("strategy_id") or "Unavailable")
    bundle_id = str(ranking.get("bundle_id") or gate.get("bundle_id") or "Not created")
    signal_id = str(ranking.get("signal_id") or gate.get("signal_id") or "Not created")
    requested_side = str(ranking.get("requested_side") or "Unavailable").upper()
    selected = [dict(row) for row in (ranking.get("selected_rows") or [])]
    resolution_data = dict(resolution or {})
    bundle_rows = resolution_data.get("bundle_rows") or []
    created_ts = _timestamp(_row_value(bundle_rows, "Created at") or safeguarded.get("bundle_timestamp"))
    fresh_until_ts = _timestamp(_row_value(bundle_rows, "Fresh until"))
    evaluation_ts = _timestamp(evaluation_timestamp) or _timestamp(safeguarded.get("bundle_timestamp")) or pd.Timestamp.now(tz="Asia/Kolkata")
    remaining = (fresh_until_ts - evaluation_ts).total_seconds() if fresh_until_ts is not None else None
    lifetime = (fresh_until_ts - created_ts).total_seconds() if fresh_until_ts is not None and created_ts is not None else None
    snapshot_age = _number(safeguarded.get("snapshot_age_seconds"))
    max_snapshot_age = _number(safeguarded.get("maximum_snapshot_age_seconds"))

    candidates: list[dict[str, object]] = []
    seen: set[str] = set()
    capacity = _CAPACITY.get(strategy_id, 0)
    for position, source in enumerate(selected, start=1):
        row = dict(source)
        role = str(row.get("ranking_decision") or "Unavailable")
        token = str(row.get("instrument_token") or row.get("instrument_key") or "Unavailable")
        candidate_id, identity_key = _candidate_identity(strategy_id, bundle_id, token, role)
        checks: list[dict[str, object]] = []
        wait_reasons: list[str] = []
        reject_reasons: list[str] = []

        def check(name: str, passed: bool, reason: str, *, wait: bool = False):
            checks.append({"check": name, "status": "PASS" if passed else ("WAIT" if wait else "REJECT"), "detail": "OK" if passed else reason})
            if not passed:
                (wait_reasons if wait else reject_reasons).append(reason)

        check("Strategy ownership", strategy_id in _VALID_STRATEGIES, "INVALID_STRATEGY_ID")
        check("Bundle ownership", bundle_id.lower() not in {"", "not created", "unavailable"}, "MISSING_BUNDLE_ID")
        check("Signal identity", signal_id.lower() not in {"", "not created", "unavailable"}, "MISSING_SIGNAL_ID")
        check("Contract role", role in _VALID_ROLES.get(strategy_id, frozenset()), "INVALID_CONTRACT_ROLE")
        check("Contract identity", token not in {"", "Unavailable"}, "MISSING_INSTRUMENT_TOKEN_OR_KEY", wait=True)
        check("Trading symbol", row.get("trading_symbol") not in (None, "", "Unavailable"), "MISSING_TRADING_SYMBOL", wait=True)
        check("Exchange", row.get("exchange") not in (None, "", "Unavailable"), "MISSING_EXCHANGE", wait=True)
        check("Lot size", (_number(row.get("lot_size")) or 0) > 0, "MISSING_LOT_SIZE", wait=True)
        check("Tick size", (_number(row.get("tick_size")) or 0) > 0, "MISSING_TICK_SIZE", wait=True)
        check("Snapshot freshness", str(safeguarded.get("snapshot_freshness") or "UNAVAILABLE") == "FRESH", "SNAPSHOT_NOT_FRESH", wait=True)
        check("Bundle freshness", remaining is not None and remaining > 0, "BUNDLE_EXPIRED_OR_FRESHNESS_UNAVAILABLE", wait=remaining is None)
        expected_side = "CE" if requested_side in {"CE", "BUY CE"} else "PE" if requested_side in {"PE", "BUY PE"} else ""
        check("Direction match", bool(expected_side) and str(row.get("option_side") or "").upper() == expected_side, "CONTRACT_SIDE_DOES_NOT_MATCH_BUNDLE_INTENT")
        check("Section 5 safeguard", bool(row.get("hard_safeguard_pass", row.get("liquidity_ready"))), "SECTION_5_SAFEGUARD_FAILED")
        duplicate = identity_key in seen
        check("Duplicate within handoff", not duplicate, "DUPLICATE_WITHIN_CURRENT_HANDOFF")
        check("Strategy capacity", position <= capacity, "STRATEGY_CAPACITY_EXCEEDED")
        seen.add(identity_key)

        if reject_reasons:
            outcome = "REJECTED"
            lifecycle = "DUPLICATE" if "DUPLICATE_WITHIN_CURRENT_HANDOFF" in reject_reasons else "REJECTED"
        elif wait_reasons:
            outcome = "WAIT"
            lifecycle = "STALE" if "SNAPSHOT_NOT_FRESH" in wait_reasons or (remaining is not None and remaining <= 0) else "PROPOSED_READ_ONLY"
        else:
            outcome = "HANDOFF_READY"
            lifecycle = "ADMISSION_READY_READ_ONLY"

        candidate_score, score_components = _score_candidate(
            row,
            snapshot_age_seconds=snapshot_age,
            maximum_snapshot_age_seconds=max_snapshot_age,
            bundle_remaining_seconds=remaining,
            bundle_lifetime_seconds=lifetime,
            policy=score_policy,
        )
        candidates.append({
            "candidate_id": candidate_id,
            "identity_key": identity_key,
            "strategy_id": strategy_id,
            "signal_id": signal_id,
            "bundle_id": bundle_id,
            "role": role,
            "requested_side": expected_side or requested_side,
            "contract_side": row.get("option_side"),
            "instrument_token": row.get("instrument_token"),
            "instrument_key": row.get("instrument_key"),
            "trading_symbol": row.get("trading_symbol"),
            "exchange": row.get("exchange"),
            "expiry": row.get("expiry"),
            "strike": row.get("strike"),
            "lot_size": row.get("lot_size"),
            "tick_size": row.get("tick_size"),
            "contract_score": row.get("score"),
            "candidate_score": candidate_score,
            "score_policy_version": score_policy.policy_version,
            "snapshot_freshness": safeguarded.get("snapshot_freshness"),
            "bundle_freshness": "FRESH" if remaining is not None and remaining > 0 else "EXPIRED" if remaining is not None else "UNAVAILABLE",
            "freshness_remaining_seconds": round(remaining, 3) if remaining is not None else None,
            "duplicate_state": "DUPLICATE_WITHIN_CURRENT_HANDOFF" if duplicate else "UNIQUE_CURRENT_HANDOFF",
            "persistent_duplicate_state": "NOT_EVALUATED_READ_ONLY_SOURCE_UNAVAILABLE",
            "validation_outcome": outcome,
            "lifecycle_state": lifecycle,
            "option_chain_direction": str((option_direction or {}).get("direction") or "UNAVAILABLE"),
            "option_chain_policy_action": "OBSERVE_ONLY",
            "exact_reason": ", ".join(reject_reasons or wait_reasons) if (reject_reasons or wait_reasons) else "ALL_MANDATORY_HANDOFF_CHECKS_PASSED",
            "checks": checks,
            "score_components": score_components,
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
            "next_step": "Independent risk/admission evaluation; no persistence or execution yet." if outcome == "HANDOFF_READY" else "Resolve the exact validation reason before admission.",
        })

    ready = sum(row["validation_outcome"] == "HANDOFF_READY" for row in candidates)
    waiting = sum(row["validation_outcome"] == "WAIT" for row in candidates)
    rejected = sum(row["validation_outcome"] == "REJECTED" for row in candidates)
    return {
        "strategy_id": strategy_id,
        "bundle_id": bundle_id,
        "signal_id": signal_id,
        "capacity": capacity,
        "candidate_count": len(candidates),
        "ready_count": ready,
        "wait_count": waiting,
        "rejected_count": rejected,
        "outcome": "HANDOFF_READY" if ready else "WAIT" if waiting else "REJECTED" if rejected else "UNAVAILABLE",
        "candidates": candidates,
        "policy_action": "OBSERVE_ONLY",
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


def render_candidate_readiness(result: Mapping[str, object]) -> None:
    candidates = [dict(row) for row in (result.get("candidates") or [])]
    st.markdown("### 6. Candidate Handoff and Read-Only Lifecycle")
    st.markdown("#### 6A. Selection Handoff Validation")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(result.get("outcome") or "UNAVAILABLE"))
    c2.metric("Candidates", int(result.get("candidate_count") or 0))
    c3.metric("Handoff ready", int(result.get("ready_count") or 0))
    c4.metric("Capacity", int(result.get("capacity") or 0))
    st.caption("Validates strategy ownership, bundle/signal identity, role, executable metadata, freshness, side, duplicates and capacity. Read-only only.")

    summary = [{key: row.get(key) for key in (
        "candidate_id", "role", "requested_side", "contract_side", "trading_symbol", "exchange", "expiry", "strike",
        "snapshot_freshness", "bundle_freshness", "freshness_remaining_seconds", "duplicate_state", "validation_outcome", "exact_reason"
    )} for row in candidates]
    if summary:
        st.dataframe(summary, width="stretch", hide_index=True)
    else:
        st.info("No Section 5 proposed contracts are available for candidate validation.")

    st.markdown("#### 6B. Candidate Score")
    score_summary = [{key: row.get(key) for key in ("candidate_id", "role", "contract_score", "candidate_score", "score_policy_version", "validation_outcome")} for row in candidates]
    if score_summary:
        st.dataframe(score_summary, width="stretch", hide_index=True)
    for row in candidates:
        with st.expander(f"Why did {row['candidate_id']} receive this score?"):
            st.dataframe(list(row.get("score_components") or []), width="stretch", hide_index=True)

    st.markdown("#### 6C. Read-Only Candidate Lifecycle")
    lifecycle = [{key: row.get(key) for key in (
        "candidate_id", "role", "lifecycle_state", "validation_outcome", "duplicate_state", "persistent_duplicate_state",
        "persisted", "reserved", "bundle_consumed", "submitted", "next_step"
    )} for row in candidates]
    if lifecycle:
        st.dataframe(lifecycle, width="stretch", hide_index=True)
    for row in candidates:
        with st.expander(f"Why was {row['candidate_id']} admitted, held, or rejected?"):
            st.write(f"**Exact reason:** {row['exact_reason']}")
            st.dataframe(list(row.get("checks") or []), width="stretch", hide_index=True)
    st.write("**Mutation boundary:** no persistence, reservation, bundle consumption, candidate admission write, or order submission is performed.")
