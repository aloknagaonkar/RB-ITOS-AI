from __future__ import annotations

from functools import wraps
from types import ModuleType
from typing import Mapping

from red_bar_lab.ui.option_chain_directional_evidence import (
    build_option_chain_directional_evidence,
)
from red_bar_lab.ui.option_chain_directional_evidence_view import (
    render_option_chain_directional_evidence_5e,
)
from red_bar_lab.ui.strategy_candidate_readiness import (
    build_candidate_readiness,
    render_candidate_readiness,
)
from red_bar_lab.ui.strategy_contract_market_context import enrich_contract_market_context
from red_bar_lab.ui.strategy_contract_ranking import (
    POLICIES as RANKING_POLICIES,
    rank_strategy_contracts,
    render_strategy_contract_ranking,
)
from red_bar_lab.ui.strategy_contract_readiness import build_contract_data_readiness
from red_bar_lab.ui.strategy_contract_safeguards import (
    POLICIES as SAFEGUARD_POLICIES,
    apply_contract_safeguards,
    render_contract_safeguards,
)
from red_bar_lab.ui.strategy_contract_selection_audit import (
    build_selection_audit,
    render_selection_audit,
)
from red_bar_lab.ui.strategy_execution_decision_gate import (
    build_execution_decision_gate,
    render_execution_decision_gate,
)
from red_bar_lab.ui.strategy_execution_source_gate import POLICIES, build_execution_source_gate
from red_bar_lab.ui.strategy_historical_performance_source import load_completed_trade_history
from red_bar_lab.ui.strategy_history_coverage import (
    build_history_coverage,
    render_history_coverage,
)
from red_bar_lab.ui.strategy_opportunity_history_gate_v2 import (
    build_opportunity_history_gate,
    forward_candidates_for_risk,
    render_opportunity_history_gate,
)
from red_bar_lab.ui.strategy_risk_readiness import build_risk_readiness
from red_bar_lab.ui.strategy_risk_readiness_view import render_risk_readiness_8a


def _candidate_copy_with_contract_fields(candidate_result, ranking):
    """Enrich a downstream read-only copy without mutating Section 6 records."""
    result = dict(candidate_result or {})
    selected = [dict(row) for row in (ranking.get("selected_rows") or [])]
    by_identity = {
        (
            str(row.get("instrument_key") or row.get("instrument_token") or ""),
            str(row.get("ranking_decision") or ""),
        ): row
        for row in selected
    }
    candidates = []
    for raw in result.get("candidates") or []:
        candidate = dict(raw)
        key = (
            str(candidate.get("instrument_key") or candidate.get("instrument_token") or ""),
            str(candidate.get("role") or ""),
        )
        source = by_identity.get(key, {})
        for field in ("ltp", "bid", "ask", "spread_pct", "volume", "oi", "iv", "delta"):
            if candidate.get(field) is None:
                candidate[field] = source.get(field)
        candidates.append(candidate)
    result["candidates"] = candidates
    return result


def build_contract_ranking_page_wrapper(module: ModuleType, page: str):
    """Append read-only Sections 5B-5E, 6A-6C, 7A-7C and 8A-8B after Section 5A."""
    policy = POLICIES[page]
    ranking_policy = RANKING_POLICIES[policy.strategy_id]
    safeguard_policy = SAFEGUARD_POLICIES[policy.strategy_id]
    original_builder = getattr(module, policy.builder_name)
    original_render = module.render_page
    captured: dict[str, object] = {}

    @wraps(original_builder)
    def capture_resolution(*args, **kwargs):
        resolution = original_builder(*args, **kwargs)
        captured["resolution"] = resolution
        return resolution

    @wraps(original_render)
    def wrapped_render(*args, **kwargs):
        captured.clear()
        result = original_render(*args, **kwargs)
        resolution = captured.get("resolution") if isinstance(captured.get("resolution"), Mapping) else None
        gate = build_execution_source_gate(resolution, policy)

        database = kwargs.get("database")
        instrument_key = kwargs.get("instrument_key")
        if database is None and len(args) > 2:
            database = args[2]
        if instrument_key is None and len(args) > 5:
            instrument_key = args[5]

        if database is None or not instrument_key:
            readiness = {
                "outcome": "UNAVAILABLE",
                "reason": "Database or instrument context is unavailable to Section 5.",
                "strategy_id": policy.strategy_id,
                "signal_id": str(gate.get("signal_id") or "Not created"),
                "bundle_id": str(gate.get("bundle_id") or "Not created"),
                "requested_side": "Unavailable",
                "bundle_timestamp": "Unavailable",
                "snapshot_timestamp": "Unavailable",
                "contract_rows": [],
            }
        else:
            readiness = build_contract_data_readiness(
                gate=gate,
                resolution=resolution,
                database=database,
                instrument_key=str(instrument_key),
            )
            readiness = enrich_contract_market_context(
                readiness,
                database=database,
                instrument_key=str(instrument_key),
            )

        safeguarded = apply_contract_safeguards(readiness, policy=safeguard_policy)
        render_contract_safeguards(safeguarded)
        ranking = rank_strategy_contracts(safeguarded, policy=ranking_policy)
        render_strategy_contract_ranking(ranking)
        audit = build_selection_audit(ranking, policy=ranking_policy)
        render_selection_audit(audit)

        if database is None or not instrument_key:
            option_direction = {
                "direction": "UNAVAILABLE",
                "confidence": "NONE",
                "bullish_score": 0.0,
                "bearish_score": 0.0,
                "previous_snapshot_timestamp": "Unavailable",
                "current_snapshot_timestamp": str(readiness.get("snapshot_timestamp") or "Unavailable"),
                "comparison_seconds": None,
                "atm_strike": readiness.get("atm_strike"),
                "strikes_evaluated": 0,
                "dominant_reason": "Database or instrument context is unavailable.",
                "rows": [],
            }
        else:
            option_direction = build_option_chain_directional_evidence(
                readiness,
                database=database,
                instrument_key=str(instrument_key),
            )
        render_option_chain_directional_evidence_5e(option_direction)

        evaluation_timestamp = resolution.get("refreshed_at") if isinstance(resolution, Mapping) else None
        candidate_result = build_candidate_readiness(
            gate=gate,
            resolution=resolution,
            safeguarded=safeguarded,
            ranking=ranking,
            option_direction=option_direction,
            evaluation_timestamp=evaluation_timestamp,
        )
        render_candidate_readiness(candidate_result)

        downstream_candidates = _candidate_copy_with_contract_fields(candidate_result, ranking)
        opportunity_context = kwargs.get("opportunity_context")
        if not isinstance(opportunity_context, Mapping):
            opportunity_context = {}

        supplied_history = kwargs.get("historical_trade_records")
        if isinstance(supplied_history, (list, tuple)):
            historical_records = [dict(row) for row in supplied_history if isinstance(row, Mapping)]
            history_source = {
                "source_status": "EXPLICIT_OVERRIDE",
                "source_reason": "CALLER_SUPPLIED_RECORDS",
                "source_adapter_version": None,
                "normalized_row_count": len(historical_records),
                "coverage": build_history_coverage(historical_records),
                "source_read_only": True,
            }
        else:
            history_source = load_completed_trade_history(database)
            historical_records = list(history_source.get("records") or [])

        opportunity_result = build_opportunity_history_gate(
            downstream_candidates,
            opportunity_context=opportunity_context,
            historical_records=historical_records,
            history_source=history_source,
        )
        render_opportunity_history_gate(opportunity_result)
        render_history_coverage(history_source.get("coverage") or build_history_coverage([]))

        risk_context = kwargs.get("account_risk_context")
        if not isinstance(risk_context, Mapping):
            risk_context = {}
        risk_input = forward_candidates_for_risk(opportunity_result)
        risk_result = build_risk_readiness(risk_input, risk_context=risk_context)
        render_risk_readiness_8a(risk_result)

        execution_decision = build_execution_decision_gate(
            opportunity_result,
            risk_result,
            execution_source_gate=gate,
        )
        render_execution_decision_gate(execution_decision)
        return result

    setattr(module, policy.builder_name, capture_resolution)
    return wrapped_render
