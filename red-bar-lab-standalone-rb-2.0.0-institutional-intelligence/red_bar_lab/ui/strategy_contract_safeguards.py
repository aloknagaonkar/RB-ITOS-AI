from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Mapping

import pandas as pd
import streamlit as st


@dataclass(frozen=True)
class ContractSafeguardPolicy:
    strategy_id: str
    policy_version: str
    maximum_snapshot_age_seconds: int = 60
    minimum_volume: float = 1.0
    minimum_open_interest: float = 1.0
    maximum_spread_pct: float = 4.0
    maximum_strike_distance_steps: int = 2


_DRI_POLICY = ContractSafeguardPolicy(
    "DIRECTIONAL_REGIME", "DRI-CONTRACT-SAFEGUARD-V1"
)

POLICIES: Mapping[str, ContractSafeguardPolicy] = {
    "RED_BAR": ContractSafeguardPolicy("RED_BAR", "RB-CONTRACT-SAFEGUARD-V1"),
    "DIRECTIONAL_REGIME": _DRI_POLICY,
    "DIRECTIONAL_REGIME_INTELLIGENCE": _DRI_POLICY,
    "RSI_EXTREME_REVERSAL": ContractSafeguardPolicy(
        "RSI_EXTREME_REVERSAL", "RSI-CONTRACT-SAFEGUARD-V1"
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


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, "", "Unavailable"):
        return None
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("Asia/Kolkata")
    return ts.tz_convert("Asia/Kolkata")


def _expiry(value: object) -> date | None:
    if value in (None, "", "Unavailable"):
        return None
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def _instrument_token(row: Mapping[str, object]) -> str | None:
    for key in ("instrument_token", "instrument_key"):
        value = row.get(key)
        if value not in (None, "", "Unavailable"):
            return str(value)
    return None


def _strike_interval(rows: list[dict[str, object]]) -> float | None:
    strikes = sorted(
        {
            value
            for row in rows
            if (value := _number(row.get("strike"))) is not None and value > 0
        }
    )
    differences = [right - left for left, right in zip(strikes, strikes[1:]) if right > left]
    return min(differences) if differences else None


def apply_contract_safeguards(
    readiness: Mapping[str, object],
    *,
    policy: ContractSafeguardPolicy,
) -> dict[str, object]:
    """Apply absolute read-only safeguards before relative contract ranking."""
    result = dict(readiness)
    rows = [dict(row) for row in (result.get("contract_rows") or [])]
    base = {
        **result,
        "safeguard_policy_version": policy.policy_version,
        "maximum_snapshot_age_seconds": policy.maximum_snapshot_age_seconds,
        "minimum_volume": policy.minimum_volume,
        "minimum_open_interest": policy.minimum_open_interest,
        "maximum_spread_pct": policy.maximum_spread_pct,
        "maximum_strike_distance_steps": policy.maximum_strike_distance_steps,
        "snapshot_age_seconds": None,
        "snapshot_freshness": "UNAVAILABLE",
        "hard_safeguard_pass_count": 0,
        "execution_metadata_ready_count": 0,
        "strike_safeguard_status": "NOT_EVALUATED",
        "safeguard_rows": [],
    }

    if str(result.get("outcome") or "UNAVAILABLE") != "READY_FOR_RANKING":
        return base

    bundle_ts = _timestamp(result.get("bundle_timestamp"))
    snapshot_ts = _timestamp(result.get("snapshot_timestamp"))
    if bundle_ts is None or snapshot_ts is None:
        return {
            **base,
            "outcome": "UNAVAILABLE",
            "reason": "Bundle or option snapshot timestamp is unavailable for freshness validation.",
            "contract_rows": [],
        }

    age_seconds = (bundle_ts - snapshot_ts).total_seconds()
    if age_seconds < 0:
        return {
            **base,
            "outcome": "UNAVAILABLE",
            "reason": "The selected option snapshot is after the strategy bundle timestamp.",
            "snapshot_age_seconds": round(age_seconds, 3),
            "snapshot_freshness": "INVALID_FUTURE",
            "contract_rows": [],
        }
    if age_seconds > policy.maximum_snapshot_age_seconds:
        return {
            **base,
            "outcome": "WAIT",
            "reason": (
                f"The option snapshot is {age_seconds:.1f}s old; the maximum allowed age is "
                f"{policy.maximum_snapshot_age_seconds}s."
            ),
            "snapshot_age_seconds": round(age_seconds, 3),
            "snapshot_freshness": "STALE",
            "contract_rows": [],
        }

    trading_date = bundle_ts.date()
    visible_expiries = {
        item for row in rows if (item := _expiry(row.get("expiry"))) is not None
    }
    mixed_expiry = len(visible_expiries) > 1

    spot = _number(result.get("spot_price"))
    atm = _number(result.get("atm_strike"))
    interval = _strike_interval(rows)
    strike_evaluable = spot is not None and atm is not None and interval not in (None, 0)

    hardened: list[dict[str, object]] = []
    safeguard_rows: list[dict[str, object]] = []
    for raw in rows:
        row = dict(raw)
        reasons: list[str] = []
        expiry_value = _expiry(row.get("expiry"))
        volume = _number(row.get("volume"))
        oi = _number(row.get("oi"))
        spread_pct = _number(row.get("spread_pct"))
        strike = _number(row.get("strike"))

        if expiry_value is None:
            reasons.append("MISSING_EXPIRY")
        elif expiry_value < trading_date:
            reasons.append("EXPIRED_CONTRACT")
        if mixed_expiry:
            reasons.append("MIXED_EXPIRY_ARTIFACT")
        if volume is None or volume < policy.minimum_volume:
            reasons.append("VOLUME_BELOW_MINIMUM")
        if oi is None or oi < policy.minimum_open_interest:
            reasons.append("OPEN_INTEREST_BELOW_MINIMUM")
        if spread_pct is None:
            reasons.append("MISSING_SPREAD")
        elif spread_pct > policy.maximum_spread_pct:
            reasons.append("SPREAD_TOO_WIDE")

        strike_distance_steps = None
        strike_status = "NOT_EVALUATED_MISSING_SPOT_OR_ATM"
        if strike_evaluable and strike is not None:
            strike_distance_steps = abs(strike - float(atm)) / float(interval)
            strike_status = "PASS"
            if strike_distance_steps > policy.maximum_strike_distance_steps:
                reasons.append("STRIKE_OUT_OF_RANGE")
                strike_status = "BLOCK"

        explicit_token = row.get("instrument_token") not in (None, "", "Unavailable")
        executable_identity = _instrument_token(row) is not None
        lot_size = _number(row.get("lot_size"))
        exchange = row.get("exchange")
        tick_size = _number(row.get("tick_size"))
        execution_metadata_reasons: list[str] = []
        if not explicit_token:
            execution_metadata_reasons.append("MISSING_EXPLICIT_INSTRUMENT_TOKEN")
        if lot_size is None or lot_size <= 0:
            execution_metadata_reasons.append("MISSING_LOT_SIZE")
        if exchange in (None, "", "Unavailable"):
            execution_metadata_reasons.append("MISSING_EXCHANGE")
        if tick_size is None or tick_size <= 0:
            execution_metadata_reasons.append("MISSING_TICK_SIZE")

        hard_pass = bool(row.get("liquidity_ready")) and executable_identity and not reasons
        execution_metadata_ready = hard_pass and not execution_metadata_reasons
        row.update(
            {
                "hard_safeguard_pass": hard_pass,
                "safeguard_reasons": ", ".join(reasons) if reasons else "NONE",
                "snapshot_age_seconds": round(age_seconds, 3),
                "snapshot_freshness": "FRESH",
                "strike_distance_steps": (
                    round(strike_distance_steps, 3)
                    if strike_distance_steps is not None
                    else None
                ),
                "strike_safeguard_status": strike_status,
                "execution_metadata_ready": execution_metadata_ready,
                "execution_metadata_reasons": (
                    ", ".join(execution_metadata_reasons)
                    if execution_metadata_reasons
                    else "NONE"
                ),
                "liquidity_ready": hard_pass,
                "decision": "READY_FOR_RANKING" if hard_pass else "REJECTED",
            }
        )
        hardened.append(row)
        safeguard_rows.append(
            {
                "instrument_key": row.get("instrument_key"),
                "expiry": row.get("expiry"),
                "strike": strike,
                "spread_pct": spread_pct,
                "volume": volume,
                "oi": oi,
                "hard_safeguard": "PASS" if hard_pass else "BLOCK",
                "hard_reasons": row["safeguard_reasons"],
                "execution_metadata": (
                    "READY" if execution_metadata_ready else "INCOMPLETE"
                ),
                "execution_metadata_reasons": row["execution_metadata_reasons"],
                "strike_check": strike_status,
            }
        )

    pass_count = sum(bool(row.get("hard_safeguard_pass")) for row in hardened)
    metadata_count = sum(bool(row.get("execution_metadata_ready")) for row in hardened)
    outcome = "READY_FOR_RANKING" if pass_count else "REJECTED"
    reason = (
        f"{pass_count} contract(s) passed absolute snapshot, expiry and liquidity safeguards."
        if pass_count
        else "No contract passed the absolute snapshot, expiry and liquidity safeguards."
    )
    return {
        **base,
        "outcome": outcome,
        "reason": reason,
        "snapshot_age_seconds": round(age_seconds, 3),
        "snapshot_freshness": "FRESH",
        "hard_safeguard_pass_count": pass_count,
        "execution_metadata_ready_count": metadata_count,
        "strike_safeguard_status": (
            "EVALUATED" if strike_evaluable else "NOT_EVALUATED_MISSING_SPOT_OR_ATM"
        ),
        "contract_rows": hardened,
        "safeguard_rows": safeguard_rows,
        "ready_for_ranking": pass_count,
        "next_step": (
            "Rank only contracts that passed all absolute safeguards."
            if pass_count
            else "Wait for a fresh snapshot with eligible contracts; do not rank or execute."
        ),
    }


def render_contract_safeguards(result: Mapping[str, object]) -> None:
    st.markdown("#### 5D. Contract Safeguard Hardening")
    st.caption(
        "Absolute read-only safeguards run before relative ranking. A weak contract cannot "
        "win merely because it is the least-weak contract in the snapshot."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(result.get("outcome") or "UNAVAILABLE"))
    c2.metric("Snapshot", str(result.get("snapshot_freshness") or "UNAVAILABLE"))
    c3.metric("Hard-pass contracts", int(result.get("hard_safeguard_pass_count") or 0))
    c4.metric(
        "Execution metadata ready",
        int(result.get("execution_metadata_ready_count") or 0),
    )
    st.write(f"**Safeguard policy:** {result.get('safeguard_policy_version', 'Unavailable')}")
    st.write(f"**Snapshot age:** {result.get('snapshot_age_seconds', 'Unavailable')} seconds")
    st.write(f"**Strike safeguard:** {result.get('strike_safeguard_status', 'NOT_EVALUATED')}")
    st.write(f"**Decision reason:** {result.get('reason', 'Unavailable')}")
    st.write(
        "**Execution note:** Missing token/lot/exchange/tick metadata is displayed explicitly; "
        "nothing is fabricated or executed."
    )
    rows = list(result.get("safeguard_rows") or [])
    with st.expander("View absolute contract safeguards"):
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No contract rows were available for safeguard evaluation.")
