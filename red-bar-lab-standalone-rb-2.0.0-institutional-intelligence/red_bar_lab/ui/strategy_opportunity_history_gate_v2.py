from __future__ import annotations

from statistics import median
from typing import Mapping, Sequence

from red_bar_lab.ui.strategy_opportunity_history_gate import (
    DEFAULT_POLICY,
    OpportunityHistoryPolicy,
    _number,
    _opportunity,
    forward_candidates_for_risk,
    render_opportunity_history_gate,
)


_EXACT_FIELDS = (
    "strategy_version",
    "setup_type",
    "role",
    "moneyness",
    "time_of_day_bucket",
    "days_to_expiry_bucket",
    "exit_policy_version",
)
_CORE_FIELDS = ("strategy_version", "exit_policy_version")


def _text(value: object) -> str:
    return str(value or "").strip().upper()


def _candidate_value(candidate: Mapping[str, object], field: str) -> object:
    aliases = {
        "setup_type": ("setup_type", "primary_setup_type", "signal_type"),
        "moneyness": ("moneyness", "moneyness_bucket"),
        "time_of_day_bucket": ("time_of_day_bucket", "session_bucket"),
        "days_to_expiry_bucket": ("days_to_expiry_bucket", "dte_bucket"),
    }
    for name in aliases.get(field, (field,)):
        if candidate.get(name) not in (None, ""):
            return candidate.get(name)
    return None


def _base_rows(candidate: Mapping[str, object], records: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    strategy_id = _text(candidate.get("strategy_id"))
    side = _text(candidate.get("contract_side") or candidate.get("requested_side"))
    rows = []
    for raw in records or []:
        row = dict(raw)
        if _text(row.get("strategy_id")) != strategy_id:
            continue
        row_side = _text(row.get("contract_side") or row.get("side"))
        if side and row_side and row_side != side:
            continue
        if _text(row.get("status") or row.get("trade_status") or "CLOSED") not in {
            "CLOSED", "COMPLETED", "EXITED"
        }:
            continue
        if _number(row.get("net_points") if row.get("net_points") is not None else row.get("pnl_points")) is None:
            continue
        rows.append(row)
    return rows


def _matches(candidate: Mapping[str, object], row: Mapping[str, object], fields: Sequence[str]) -> bool:
    compared = False
    for field in fields:
        expected = _candidate_value(candidate, field)
        if expected in (None, ""):
            continue
        compared = True
        if _text(row.get(field)) != _text(expected):
            return False
    return compared


def _select_tier(candidate: Mapping[str, object], records: Sequence[Mapping[str, object]]) -> tuple[str, list[dict[str, object]], list[str], list[str]]:
    base = _base_rows(candidate, records)
    exact_filters = [field for field in _EXACT_FIELDS if _candidate_value(candidate, field) not in (None, "")]
    core_filters = [field for field in _CORE_FIELDS if _candidate_value(candidate, field) not in (None, "")]
    exact = [row for row in base if _matches(candidate, row, _EXACT_FIELDS)] if exact_filters else []
    if exact:
        return "TIER_1_EXACT_CONTEXT", exact, exact_filters, []
    core = [row for row in base if _matches(candidate, row, _CORE_FIELDS)] if core_filters else []
    if core:
        relaxed = [field for field in exact_filters if field not in core_filters]
        return "TIER_2_VERSIONED_BASELINE", core, core_filters, relaxed
    missing = [field for field in _EXACT_FIELDS if _candidate_value(candidate, field) in (None, "")]
    return "TIER_3_STRATEGY_SIDE_BASELINE", base, [], missing


def _historical_v2(candidate: Mapping[str, object], records: Sequence[Mapping[str, object]], policy: OpportunityHistoryPolicy) -> dict[str, object]:
    tier, comparable, applied, relaxed = _select_tier(candidate, records)
    points = [float(_number(row.get("net_points") if row.get("net_points") is not None else row.get("pnl_points"))) for row in comparable]
    wins = [value for value in points if value > 0]
    losses = [value for value in points if value < 0]
    sample_count = len(points)
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    net_points = sum(points)
    win_rate = len(wins) / sample_count if sample_count else None
    average_win = gross_profit / len(wins) if wins else 0.0
    average_loss = abs(gross_loss / len(losses)) if losses else 0.0
    average_costs = (
        sum(_number(row.get("estimated_costs")) or 0.0 for row in comparable) / sample_count
        if sample_count else 0.0
    )
    expectancy = (
        win_rate * average_win - (1.0 - win_rate) * average_loss - average_costs
        if win_rate is not None else None
    )
    profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else (float("inf") if gross_profit > 0 else None)
    mfe = [_number(row.get("mfe_points")) for row in comparable]
    mae = [_number(row.get("mae_points")) for row in comparable]
    mfe = [value for value in mfe if value is not None]
    mae = [value for value in mae if value is not None]
    cumulative = peak = maximum_drawdown = 0.0
    for value in points:
        cumulative += value
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)

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
        "strategy_id": candidate.get("strategy_id"),
        "matching_tier": tier,
        "filters_applied": applied,
        "filters_relaxed_or_missing": relaxed,
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
        "median_mfe": median(mfe) if mfe else None,
        "median_mae": median(mae) if mae else None,
        "maximum_drawdown": maximum_drawdown,
        "confidence_state": confidence,
        "outcome": outcome,
        "unit": "POINTS",
        "comparable_rows": comparable,
        "source_read_only": True,
    }


def build_opportunity_history_gate(
    candidate_result: Mapping[str, object],
    *,
    opportunity_context: Mapping[str, object] | None = None,
    historical_records: Sequence[Mapping[str, object]] | None = None,
    policy: OpportunityHistoryPolicy = DEFAULT_POLICY,
    history_source: Mapping[str, object] | None = None,
) -> dict[str, object]:
    rows = []
    records = list(historical_records or [])
    for raw in candidate_result.get("candidates") or []:
        candidate = dict(raw)
        opportunity = _opportunity(candidate, dict(opportunity_context or {}), policy)
        historical = _historical_v2(candidate, records, policy)
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
            "historical_filter_version": "HISTORICAL-GATE-V2-TIERED",
            "history_source_status": (history_source or {}).get("source_status", "EXPLICIT_RECORDS"),
            "history_source_reason": (history_source or {}).get("source_reason", "CALLER_SUPPLIED_RECORDS"),
            "history_source_adapter_version": (history_source or {}).get("source_adapter_version"),
            "policy_action": "OBSERVE_ONLY",
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
        })
    return {
        "outcome": "FORWARD" if any(row["combined_outcome"] in {"FORWARD", "FORWARD_WITHOUT_HISTORICAL_SUPPORT"} for row in rows) else "WAIT" if any(row["combined_outcome"] == "WAIT" for row in rows) else "OBSERVE_ONLY" if any(row["combined_outcome"] == "OBSERVE_ONLY" for row in rows) else "REJECT" if rows else "UNAVAILABLE",
        "rows": rows,
        "history_source": dict(history_source or {}),
        "policy_action": "OBSERVE_ONLY",
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


__all__ = [
    "build_opportunity_history_gate",
    "forward_candidates_for_risk",
    "render_opportunity_history_gate",
]
