from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

import pandas as pd
import streamlit as st


@dataclass(frozen=True)
class OpportunityHistoryPolicy:
    opportunity_policy_version: str = "OPPORTUNITY-GATE-V1"
    historical_filter_version: str = "HISTORICAL-GATE-V1"
    maximum_spread_pct: float = 4.0
    minimum_reward_risk: float = 1.0
    minimum_historical_samples_for_veto: int = 20
    pass_profit_factor: float = 1.20
    reject_profit_factor: float = 0.90


DEFAULT_POLICY = OpportunityHistoryPolicy()


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _candidate_context(context: Mapping[str, object], candidate_id: str) -> dict[str, object]:
    nested = context.get("candidates")
    if isinstance(nested, Mapping) and isinstance(nested.get(candidate_id), Mapping):
        return {**dict(context), **dict(nested[candidate_id])}
    return dict(context)


def _opportunity(candidate: Mapping[str, object], context: Mapping[str, object], policy: OpportunityHistoryPolicy) -> dict[str, object]:
    cid = str(candidate.get("candidate_id") or "Unavailable")
    values = _candidate_context(context, cid)
    checks: list[dict[str, object]] = []
    waits: list[str] = []
    rejects: list[str] = []

    def check(name: str, passed: bool, reason: str, *, wait: bool = False, detail: object = None):
        checks.append({"check": name, "status": "PASS" if passed else ("WAIT" if wait else "REJECT"), "detail": detail if passed and detail is not None else ("OK" if passed else reason)})
        if not passed:
            (waits if wait else rejects).append(reason)

    ready = str(candidate.get("validation_outcome")) == "HANDOFF_READY"
    check("Candidate validity", ready, "CANDIDATE_NOT_ADMISSION_READY")
    entry = _number(candidate.get("ltp") or values.get("entry_premium"))
    bid = _number(candidate.get("bid") or values.get("bid"))
    ask = _number(candidate.get("ask") or values.get("ask"))
    spread_pct = _number(candidate.get("spread_pct") or values.get("spread_pct"))
    stop = _number(values.get("initial_option_stop"))
    slippage = _number(values.get("estimated_slippage"))
    charges = _number(values.get("estimated_charges"))
    mfe = _number(values.get("expected_favourable_excursion"))
    mae = _number(values.get("expected_adverse_excursion"))
    available_capital = _number(values.get("available_capital"))
    lot_size = _number(candidate.get("lot_size"))
    lots = int(_number(values.get("proposed_lots")) or 1)

    check("Premium validity", entry is not None and entry > 0, "INVALID_ENTRY_PREMIUM")
    check("Bid/ask validity", bid is not None and ask is not None and bid > 0 and ask >= bid, "INVALID_BID_ASK", wait=bid is None or ask is None)
    check("Spread", spread_pct is not None and spread_pct <= policy.maximum_spread_pct, "SPREAD_EXCEEDS_LIMIT", wait=spread_pct is None, detail=spread_pct)
    check("Snapshot freshness", str(candidate.get("snapshot_freshness")) == "FRESH", "SNAPSHOT_NOT_FRESH")
    check("Bundle freshness", str(candidate.get("bundle_freshness")) == "FRESH", "BUNDLE_NOT_FRESH")
    check("Initial stop", stop is not None and entry is not None and 0 < stop < entry, "INVALID_OR_MISSING_INITIAL_STOP", wait=stop is None)
    check("Slippage estimate", slippage is not None and slippage >= 0, "SLIPPAGE_ESTIMATE_UNAVAILABLE", wait=slippage is None)
    check("Charges estimate", charges is not None and charges >= 0, "CHARGES_ESTIMATE_UNAVAILABLE", wait=charges is None)
    check("Expected favourable excursion", mfe is not None and mfe > 0, "EXPECTED_FAVOURABLE_EXCURSION_UNAVAILABLE", wait=mfe is None)
    check("Expected adverse excursion", mae is not None and mae >= 0, "EXPECTED_ADVERSE_EXCURSION_UNAVAILABLE", wait=mae is None)

    required_capital = entry * lot_size * lots if entry is not None and lot_size is not None else None
    if available_capital is None:
        check("Capital requirement", False, "AVAILABLE_CAPITAL_UNAVAILABLE", wait=True)
    elif required_capital is None:
        check("Capital requirement", False, "CAPITAL_REQUIREMENT_UNAVAILABLE", wait=True)
    else:
        check("Capital requirement", available_capital >= required_capital, "INSUFFICIENT_CAPITAL", detail=required_capital)

    initial_risk = entry - stop if entry is not None and stop is not None else None
    effective_risk = initial_risk + slippage + charges if initial_risk is not None and slippage is not None and charges is not None else None
    expected_net_edge = mfe - mae - slippage - charges if None not in (mfe, mae, slippage, charges) else None
    reward_risk = expected_net_edge / effective_risk if expected_net_edge is not None and effective_risk and effective_risk > 0 else None
    break_even = effective_risk / (mfe + effective_risk) if effective_risk is not None and mfe is not None and (mfe + effective_risk) > 0 else None
    if effective_risk is not None:
        check("Effective initial risk", effective_risk > 0, "INVALID_EFFECTIVE_RISK", detail=effective_risk)
    if expected_net_edge is not None:
        check("Cost-adjusted edge", expected_net_edge > 0, "NON_POSITIVE_EXPECTED_NET_EDGE", detail=expected_net_edge)
    if reward_risk is not None:
        check("Reward/risk estimate", reward_risk >= policy.minimum_reward_risk, "REWARD_RISK_BELOW_MINIMUM", detail=reward_risk)

    outcome = "REJECT" if rejects else "WAIT" if waits else "PASS"
    return {
        "candidate_id": cid,
        "outcome": outcome,
        "entry_premium": entry,
        "initial_option_stop": stop,
        "initial_risk": initial_risk,
        "estimated_slippage": slippage,
        "estimated_charges": charges,
        "effective_risk": effective_risk,
        "expected_favourable_excursion": mfe,
        "expected_adverse_excursion": mae,
        "expected_net_edge": expected_net_edge,
        "reward_to_risk": reward_risk,
        "break_even_win_rate": break_even,
        "required_capital": required_capital,
        "checks": checks,
        "exact_reason": ", ".join(rejects or waits) if (rejects or waits) else "ALL_OPPORTUNITY_CHECKS_PASSED",
    }


def _historical(candidate: Mapping[str, object], records: Sequence[Mapping[str, object]], policy: OpportunityHistoryPolicy) -> dict[str, object]:
    strategy_id = str(candidate.get("strategy_id") or "Unavailable")
    side = str(candidate.get("contract_side") or candidate.get("requested_side") or "").upper()
    comparable = []
    for raw in records or []:
        row = dict(raw)
        if str(row.get("strategy_id") or "") != strategy_id:
            continue
        row_side = str(row.get("contract_side") or row.get("side") or "").upper()
        if side and row_side and row_side != side:
            continue
        if str(row.get("status") or row.get("trade_status") or "CLOSED").upper() not in {"CLOSED", "COMPLETED", "EXITED"}:
            continue
        points = _number(row.get("net_points") if row.get("net_points") is not None else row.get("pnl_points"))
        if points is None:
            continue
        row["_points"] = points
        comparable.append(row)

    points = [float(row["_points"]) for row in comparable]
    wins = [value for value in points if value > 0]
    losses = [value for value in points if value < 0]
    sample_count = len(points)
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    net_points = sum(points)
    win_rate = len(wins) / sample_count if sample_count else None
    average_win = gross_profit / len(wins) if wins else 0.0
    average_loss = abs(gross_loss / len(losses)) if losses else 0.0
    average_costs = sum(_number(row.get("estimated_costs")) or 0.0 for row in comparable) / sample_count if sample_count else 0.0
    expectancy = (win_rate * average_win - (1.0 - win_rate) * average_loss - average_costs) if win_rate is not None else None
    profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else (float("inf") if gross_profit > 0 else None)
    mfe_values = [_number(row.get("mfe_points")) for row in comparable]
    mae_values = [_number(row.get("mae_points")) for row in comparable]
    mfe_clean = [value for value in mfe_values if value is not None]
    mae_clean = [value for value in mae_values if value is not None]
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in points:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)

    if sample_count <= 4:
        confidence, outcome = "INSUFFICIENT_DATA", "NO_VETO_INSUFFICIENT_DATA"
    elif sample_count <= 19:
        confidence, outcome = "OBSERVE_ONLY", "OBSERVE_ONLY"
    else:
        confidence = "MODERATE_CONFIDENCE" if sample_count <= 49 else "HIGHER_CONFIDENCE"
        if expectancy is not None and expectancy > 0 and profit_factor is not None and profit_factor >= policy.pass_profit_factor:
            outcome = "PASS"
        elif expectancy is not None and expectancy < 0 and profit_factor is not None and profit_factor < policy.reject_profit_factor:
            outcome = "REJECT"
        else:
            outcome = "OBSERVE_ONLY"

    return {
        "candidate_id": candidate.get("candidate_id"),
        "strategy_id": strategy_id,
        "matching_tier": "STRATEGY_AND_SIDE_BASELINE",
        "sample_count": sample_count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_points": net_points,
        "profit_factor": profit_factor,
        "average_win": average_win,
        "average_loss": average_loss,
        "average_costs": average_costs,
        "expectancy": expectancy,
        "median_mfe": float(pd.Series(mfe_clean).median()) if mfe_clean else None,
        "median_mae": float(pd.Series(mae_clean).median()) if mae_clean else None,
        "maximum_drawdown": max_drawdown,
        "confidence_state": confidence,
        "outcome": outcome,
        "unit": "POINTS",
        "comparable_rows": comparable,
    }


def build_opportunity_history_gate(
    candidate_result: Mapping[str, object],
    *,
    opportunity_context: Mapping[str, object] | None = None,
    historical_records: Sequence[Mapping[str, object]] | None = None,
    policy: OpportunityHistoryPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    rows = []
    for raw in candidate_result.get("candidates") or []:
        candidate = dict(raw)
        opportunity = _opportunity(candidate, dict(opportunity_context or {}), policy)
        historical = _historical(candidate, list(historical_records or []), policy)
        if opportunity["outcome"] == "REJECT":
            final = "REJECT"
        elif opportunity["outcome"] == "WAIT":
            final = "WAIT"
        elif historical["outcome"] == "PASS":
            final = "FORWARD"
        elif historical["outcome"] == "NO_VETO_INSUFFICIENT_DATA":
            final = "FORWARD_WITHOUT_HISTORICAL_SUPPORT"
        elif historical["outcome"] == "OBSERVE_ONLY":
            final = "OBSERVE_ONLY"
        else:
            final = "REJECT"
        rows.append({
            **candidate,
            "opportunity": opportunity,
            "historical": historical,
            "opportunity_outcome": opportunity["outcome"],
            "historical_outcome": historical["outcome"],
            "combined_outcome": final,
            "opportunity_policy_version": policy.opportunity_policy_version,
            "historical_filter_version": policy.historical_filter_version,
            "policy_action": "OBSERVE_ONLY",
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
        })
    return {
        "outcome": "FORWARD" if any(row["combined_outcome"] in {"FORWARD", "FORWARD_WITHOUT_HISTORICAL_SUPPORT"} for row in rows) else "WAIT" if any(row["combined_outcome"] == "WAIT" for row in rows) else "OBSERVE_ONLY" if any(row["combined_outcome"] == "OBSERVE_ONLY" for row in rows) else "REJECT" if rows else "UNAVAILABLE",
        "rows": rows,
        "policy_action": "OBSERVE_ONLY",
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


def forward_candidates_for_risk(result: Mapping[str, object]) -> dict[str, object]:
    allowed = {"FORWARD", "FORWARD_WITHOUT_HISTORICAL_SUPPORT"}
    rows = [dict(row) for row in (result.get("rows") or []) if row.get("combined_outcome") in allowed]
    return {"candidates": rows, "outcome": "HANDOFF_READY" if rows else "NOT_ELIGIBLE"}


def render_opportunity_history_gate(result: Mapping[str, object]) -> None:
    rows = [dict(row) for row in (result.get("rows") or [])]
    st.markdown("### 7. Opportunity & Historical-Performance Gates")
    st.markdown("#### 7A. Opportunity-Quality Gate")
    st.caption("Read-only cost-adjusted opportunity evaluation. No fixed target is invented; expected excursion must be supplied by measurable structure or strategy-owned history.")
    if rows:
        st.dataframe([{
            "candidate_id": row.get("candidate_id"),
            "role": row.get("role"),
            "opportunity": row.get("opportunity_outcome"),
            "entry": row["opportunity"].get("entry_premium"),
            "effective_risk": row["opportunity"].get("effective_risk"),
            "expected_net_edge": row["opportunity"].get("expected_net_edge"),
            "reward_to_risk": row["opportunity"].get("reward_to_risk"),
            "reason": row["opportunity"].get("exact_reason"),
        } for row in rows], width="stretch", hide_index=True)
    else:
        st.info("No Section 6 candidates are available for opportunity evaluation.")
    for row in rows:
        with st.expander(f"Why did the opportunity gate evaluate {row.get('candidate_id')} this way?"):
            st.dataframe(row["opportunity"].get("checks") or [], width="stretch", hide_index=True)

    st.markdown("#### 7B. Historical-Performance Gate")
    if rows:
        st.dataframe([{
            "candidate_id": row.get("candidate_id"),
            "strategy_id": row.get("strategy_id"),
            "historical_result": row.get("historical_outcome"),
            "confidence": row["historical"].get("confidence_state"),
            "samples": row["historical"].get("sample_count"),
            "win_rate": row["historical"].get("win_rate"),
            "expectancy_points": row["historical"].get("expectancy"),
            "profit_factor": row["historical"].get("profit_factor"),
            "median_mfe": row["historical"].get("median_mfe"),
            "median_mae": row["historical"].get("median_mae"),
        } for row in rows], width="stretch", hide_index=True)
    for row in rows:
        with st.expander(f"Which historical trades were comparable for {row.get('candidate_id')}?"):
            st.write(f"**Matching tier:** {row['historical'].get('matching_tier')}")
            st.write("**Unit:** POINTS")
            comparable = row["historical"].get("comparable_rows") or []
            st.dataframe(comparable, width="stretch", hide_index=True) if comparable else st.info("No same-strategy comparable completed trades were supplied.")

    st.markdown("#### 7C. Combined Gate Decision")
    if rows:
        st.dataframe([{
            "candidate_id": row.get("candidate_id"),
            "role": row.get("role"),
            "opportunity": row.get("opportunity_outcome"),
            "historical": row.get("historical_outcome"),
            "final_result": row.get("combined_outcome"),
        } for row in rows], width="stretch", hide_index=True)
    st.write("**Mutation boundary:** no persistence, reservation, bundle consumption or order submission is performed.")
