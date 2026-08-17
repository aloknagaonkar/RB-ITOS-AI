from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pandas as pd
import streamlit as st


@dataclass(frozen=True)
class OptionDirectionPolicy:
    policy_version: str = "OPTION-OI-DIRECTION-V1"
    strike_window_steps: int = 2
    minimum_absolute_oi_change: float = 1.0
    minimum_percentage_oi_change: float = 0.1
    dominance_margin: float = 0.15


DEFAULT_POLICY = OptionDirectionPolicy()


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


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(result) else result


def _load_artifact(path_value: object) -> pd.DataFrame:
    if not path_value:
        return pd.DataFrame()
    try:
        path = Path(str(path_value))
        if not path.exists() or not path.is_file():
            return pd.DataFrame()
        return pd.read_json(path) if path.suffix.lower() == ".json" else pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    lower = {str(name).lower(): str(name) for name in frame.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _normalized_oi(frame: pd.DataFrame) -> pd.DataFrame:
    strike_col = _column(frame, ("strike", "strike_price"))
    call_col = _column(frame, ("call_oi", "ce_oi", "call_open_interest"))
    put_col = _column(frame, ("put_oi", "pe_oi", "put_open_interest"))
    if not strike_col or not call_col or not put_col:
        return pd.DataFrame(columns=["strike", "call_oi", "put_oi"])
    result = pd.DataFrame(
        {
            "strike": pd.to_numeric(frame[strike_col], errors="coerce"),
            "call_oi": pd.to_numeric(frame[call_col], errors="coerce"),
            "put_oi": pd.to_numeric(frame[put_col], errors="coerce"),
        }
    ).dropna(subset=["strike"])
    return result.groupby("strike", as_index=False).last()


def _classify(current: float | None, previous: float | None, policy: OptionDirectionPolicy):
    if current is None or previous is None:
        return "UNAVAILABLE", None, None
    change = current - previous
    percentage = (change / abs(previous) * 100.0) if previous else (100.0 if change else 0.0)
    material = (
        abs(change) >= policy.minimum_absolute_oi_change
        and abs(percentage) >= policy.minimum_percentage_oi_change
    )
    if not material:
        return "NEUTRAL", change, percentage
    return ("ADDITION" if change > 0 else "UNWINDING"), change, percentage


def _resolve_snapshots(database, instrument_key: str, current_ts: pd.Timestamp):
    source = getattr(database, "_database", database)
    rows = list(
        source.read_option_chain_history(
            instrument_key,
            current_ts.date().isoformat(),
            current_ts.date().isoformat(),
            limit=2000,
        )
        or []
    )
    eligible = []
    for raw in rows:
        row = dict(raw)
        if str(row.get("collector_mode") or "").upper() != "ONLINE":
            continue
        ts = _timestamp(row.get("snapshot_timestamp"))
        if ts is not None and ts <= current_ts:
            eligible.append((ts, row))
    eligible.sort(key=lambda item: item[0])
    current = next((row for ts, row in reversed(eligible) if ts == current_ts), None)
    previous = next((row for ts, row in reversed(eligible) if ts < current_ts), None)
    return previous, current


def build_option_chain_directional_evidence(
    readiness: Mapping[str, object],
    *,
    database,
    instrument_key: str,
    policy: OptionDirectionPolicy = DEFAULT_POLICY,
    artifact_loader=_load_artifact,
) -> dict[str, object]:
    """Compare two no-look-ahead option snapshots and classify OI direction read-only."""
    base = {
        "outcome": "UNAVAILABLE",
        "direction": "UNAVAILABLE",
        "confidence": "NONE",
        "policy_version": policy.policy_version,
        "policy_action": "OBSERVE_ONLY",
        "strategy_id": str(readiness.get("strategy_id") or "Unavailable"),
        "signal_id": str(readiness.get("signal_id") or "Not created"),
        "bundle_id": str(readiness.get("bundle_id") or "Not created"),
        "requested_side": str(readiness.get("requested_side") or "Unavailable"),
        "previous_snapshot_timestamp": "Unavailable",
        "current_snapshot_timestamp": str(readiness.get("snapshot_timestamp") or "Unavailable"),
        "comparison_seconds": None,
        "atm_strike": readiness.get("atm_strike"),
        "strike_interval": None,
        "strikes_evaluated": 0,
        "bullish_score": 0.0,
        "bearish_score": 0.0,
        "bullish_evidence_count": 0,
        "bearish_evidence_count": 0,
        "neutral_evidence_count": 0,
        "dominant_reason": "Comparable option snapshots are unavailable.",
        "rows": [],
        "selection_unchanged": True,
        "persisted": False,
        "executed": False,
    }
    current_ts = _timestamp(readiness.get("snapshot_timestamp"))
    atm = _number(readiness.get("atm_strike"))
    if current_ts is None or atm is None:
        return {**base, "dominant_reason": "Current snapshot timestamp or ATM strike is unavailable."}

    previous, current = _resolve_snapshots(database, instrument_key, current_ts)
    if current is None:
        return {**base, "dominant_reason": "The exact Section 5A current snapshot could not be resolved."}
    if previous is None:
        return {**base, "dominant_reason": "No earlier ONLINE option snapshot exists before Section 5A."}

    previous_ts = _timestamp(previous.get("snapshot_timestamp"))
    current_frame = _normalized_oi(artifact_loader(current.get("chain_artifact_path")))
    previous_frame = _normalized_oi(artifact_loader(previous.get("chain_artifact_path")))
    if current_frame.empty or previous_frame.empty:
        return {**base, "dominant_reason": "Current or previous snapshot lacks comparable Call/Put OI columns."}

    strikes = sorted(set(current_frame["strike"]) & set(previous_frame["strike"]))
    differences = [b - a for a, b in zip(strikes, strikes[1:]) if b > a]
    interval = min(differences) if differences else None
    if interval is None:
        return {**base, "dominant_reason": "A strike interval cannot be resolved from common strikes."}
    allowed = {
        strike for strike in strikes
        if abs(float(strike) - atm) / float(interval) <= policy.strike_window_steps
    }
    if not allowed:
        return {**base, "dominant_reason": "No common strikes exist inside the configured ATM window."}

    previous_by_strike = previous_frame.set_index("strike").to_dict("index")
    current_by_strike = current_frame.set_index("strike").to_dict("index")
    rows = []
    bullish_total = bearish_total = 0.0
    bullish_count = bearish_count = neutral_count = 0
    reasons = []
    for strike in sorted(allowed):
        prev = previous_by_strike[strike]
        curr = current_by_strike[strike]
        call_state, call_change, call_pct = _classify(
            _number(curr.get("call_oi")), _number(prev.get("call_oi")), policy
        )
        put_state, put_change, put_pct = _classify(
            _number(curr.get("put_oi")), _number(prev.get("put_oi")), policy
        )
        bullish = bearish = 0.0
        evidence = []
        if put_state == "ADDITION":
            bullish += abs(float(put_change or 0.0)); bullish_count += 1; evidence.append("PUT_OI_ADDITION")
        elif put_state == "UNWINDING":
            bearish += abs(float(put_change or 0.0)); bearish_count += 1; evidence.append("PUT_OI_UNWINDING")
        if call_state == "UNWINDING":
            bullish += abs(float(call_change or 0.0)); bullish_count += 1; evidence.append("CALL_OI_UNWINDING")
        elif call_state == "ADDITION":
            bearish += abs(float(call_change or 0.0)); bearish_count += 1; evidence.append("CALL_OI_ADDITION")
        if not evidence or all(state in {"NEUTRAL", "UNAVAILABLE"} for state in (call_state, put_state)):
            neutral_count += 1
        bullish_total += bullish
        bearish_total += bearish
        strike_direction = "BULLISH" if bullish > bearish else "BEARISH" if bearish > bullish else "MIXED" if bullish else "NEUTRAL"
        rows.append({
            "strike": strike,
            "call_oi_previous": prev.get("call_oi"),
            "call_oi_current": curr.get("call_oi"),
            "call_oi_change": call_change,
            "call_oi_change_pct": call_pct,
            "call_behaviour": call_state,
            "put_oi_previous": prev.get("put_oi"),
            "put_oi_current": curr.get("put_oi"),
            "put_oi_change": put_change,
            "put_oi_change_pct": put_pct,
            "put_behaviour": put_state,
            "bullish_contribution": bullish,
            "bearish_contribution": bearish,
            "evidence": ", ".join(evidence) if evidence else "NONE",
            "strike_direction": strike_direction,
        })
        reasons.extend(evidence)

    total = bullish_total + bearish_total
    if total <= 0:
        direction, confidence = "NEUTRAL", "NONE"
        bullish_score = bearish_score = 0.0
    else:
        bullish_score, bearish_score = bullish_total / total, bearish_total / total
        difference = abs(bullish_score - bearish_score)
        if difference < policy.dominance_margin:
            direction, confidence = "MIXED", "NONE"
        else:
            direction = "BULLISH" if bullish_score > bearish_score else "BEARISH"
            agreement = max(bullish_score, bearish_score)
            confidence = "STRONG" if agreement >= 0.70 else "MODERATE" if agreement >= 0.60 else "WEAK"

    return {
        **base,
        "outcome": direction,
        "direction": direction,
        "confidence": confidence,
        "previous_snapshot_timestamp": previous_ts.isoformat() if previous_ts is not None else "Unavailable",
        "comparison_seconds": (current_ts - previous_ts).total_seconds() if previous_ts is not None else None,
        "strike_interval": interval,
        "strikes_evaluated": len(rows),
        "bullish_score": round(bullish_score, 4),
        "bearish_score": round(bearish_score, 4),
        "bullish_evidence_count": bullish_count,
        "bearish_evidence_count": bearish_count,
        "neutral_evidence_count": neutral_count,
        "dominant_reason": ", ".join(sorted(set(reasons))) if reasons else "No material OI change.",
        "rows": rows,
    }


def render_option_chain_directional_evidence(result: Mapping[str, object]) -> None:
    st.markdown("### 6. Evidence Alignment and Conflict Visibility")
    st.markdown("#### 6A. Option-Chain Directional Evidence")
    st.caption(
        "Read-only comparison of the exact Section 5A option snapshot with the nearest earlier "
        "ONLINE snapshot. Strategy direction and selected contracts remain unchanged."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("OI direction", str(result.get("direction") or "UNAVAILABLE"))
    c2.metric("Confidence", str(result.get("confidence") or "NONE"))
    c3.metric("Bullish score", f"{float(result.get('bullish_score') or 0.0):.1%}")
    c4.metric("Bearish score", f"{float(result.get('bearish_score') or 0.0):.1%}")
    st.write(f"**Previous snapshot:** {result.get('previous_snapshot_timestamp')}")
    st.write(f"**Current snapshot:** {result.get('current_snapshot_timestamp')}")
    st.write(f"**Comparison interval:** {result.get('comparison_seconds')} seconds")
    st.write(f"**ATM / strikes evaluated:** {result.get('atm_strike')} / {result.get('strikes_evaluated')}")
    st.write(f"**Dominant evidence:** {result.get('dominant_reason')}")
    st.write("**Policy action:** OBSERVE_ONLY — selection unchanged, not persisted, not executed")
    rows = list(result.get("rows") or [])
    with st.expander("View strike-level Call/Put OI evidence"):
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No comparable strike-level OI evidence is available.")
