from __future__ import annotations

from typing import Mapping

from red_bar_lab.ui.option_chain_directional_evidence import (
    build_option_chain_directional_evidence,
)
from red_bar_lab.ui.strategy_account_admission_v2 import (
    build_capital_reservation_proposal,
    build_final_admission,
    build_portfolio_admission,
)
from red_bar_lab.ui.strategy_account_context_source import (
    load_account_risk_context,
    merge_account_context,
)
from red_bar_lab.ui.strategy_adapter_mapping_validation import (
    build_adapter_mapping_validation,
)
from red_bar_lab.ui.strategy_broker_payload_preview import build_broker_payload_preview
from red_bar_lab.ui.strategy_candidate_readiness import build_candidate_readiness
from red_bar_lab.ui.strategy_contract_market_context import enrich_contract_market_context
from red_bar_lab.ui.strategy_contract_ranking import (
    POLICIES as RANKING_POLICIES,
    rank_strategy_contracts,
)
from red_bar_lab.ui.strategy_contract_readiness import build_contract_data_readiness
from red_bar_lab.ui.strategy_contract_safeguards import (
    POLICIES as SAFEGUARD_POLICIES,
    apply_contract_safeguards,
)
from red_bar_lab.ui.strategy_contract_selection_audit import build_selection_audit
from red_bar_lab.ui.strategy_execution_committee import build_execution_committee
from red_bar_lab.ui.strategy_execution_source_gate import (
    POLICIES,
    build_execution_source_gate,
)
from red_bar_lab.ui.strategy_historical_performance_source import load_completed_trade_history
from red_bar_lab.ui.strategy_history_coverage import build_history_coverage
from red_bar_lab.ui.strategy_live_activation_readiness import build_live_activation_readiness
from red_bar_lab.ui.strategy_opportunity_context_source import build_opportunity_context
from red_bar_lab.ui.strategy_opportunity_history_gate_v2 import (
    build_opportunity_history_gate,
    forward_candidates_for_risk,
)
from red_bar_lab.ui.strategy_order_specification import build_order_specification
from red_bar_lab.ui.strategy_scoped_risk import build_risk_readiness
from red_bar_lab.ui.strategy_shadow_submission_rehearsal import (
    build_shadow_submission_rehearsal,
)


HEADLESS_PIPELINE_VERSION = "HEADLESS-SECTIONS-4-9-V2"


def _candidate_copy_with_contract_fields(candidate_result, ranking):
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
        for field in (
            "ltp", "bid", "ask", "spread_pct", "volume", "oi", "iv", "delta",
            "expiry", "strike", "instrument_token", "instrument_key", "exchange",
            "trading_symbol", "lot_size", "tick_size", "initial_option_stop",
            "initial_stop", "stop_price", "estimated_slippage", "estimated_charges",
            "expected_favourable_excursion", "expected_adverse_excursion",
        ):
            if candidate.get(field) is None:
                candidate[field] = source.get(field)
        candidates.append(candidate)
    result["candidates"] = candidates
    return result


def _outcome(result: Mapping[str, object] | None, *names: str) -> str:
    row = dict(result or {})
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return "NOT_EVALUATED"


def _reason(result: Mapping[str, object] | None, fallback: str) -> str:
    row = dict(result or {})
    for name in (
        "reason", "blocking_reason", "decision_reason", "dominant_reason",
        "route_reason", "activation_reason", "live_activation_audit_reason",
    ):
        value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return fallback


def _first_blocking_terminal(result: Mapping[str, object]) -> tuple[str, str]:
    """Return the first authoritative stop, never the last downstream placeholder."""
    stages = (
        ("4", result.get("gate"), ("final_outcome",), {"FORWARD_TO_CONTRACT_SELECTION"}),
        ("5A", result.get("readiness_5a"), ("outcome",), {"READY_FOR_RANKING"}),
        ("5B", result.get("market_context_5b"), ("market_context_status",), {"READY"}),
        ("5C", result.get("metadata_context_5c"), ("metadata_context_status",), {"READY", "PARTIAL"}),
        ("5D", result.get("safeguarded"), ("outcome",), {"READY_FOR_RANKING"}),
        ("5E", result.get("ranking"), ("outcome",), {"SELECTED", "PARTIAL"}),
        ("6", result.get("candidate"), ("outcome",), {"READY", "CANDIDATE_READY", "FORWARD"}),
        ("7", result.get("opportunity"), ("outcome",), {"FORWARD", "APPROVED", "READY"}),
        ("8A", result.get("risk"), ("outcome",), {"READY", "RISK_READY_READ_ONLY", "FORWARD"}),
        ("8B", result.get("portfolio"), ("outcome",), {"READY", "PORTFOLIO_READY_READ_ONLY", "FORWARD"}),
        ("8C", result.get("reservation"), ("outcome",), {"PROPOSED_READ_ONLY", "READY", "FORWARD"}),
        ("8D", result.get("final_admission"), ("outcome", "decision"), {"ADMIT_READ_ONLY", "APPROVED", "FORWARD"}),
        ("9A", result.get("committee"), ("outcome",), {"APPROVED", "COMMITTEE_APPROVED", "FORWARD"}),
        ("9B", result.get("order_specification"), ("outcome",), {"READY", "ORDER_SPECIFICATION_READY"}),
        ("9C", result.get("payload_preview"), ("outcome",), {"READY", "BROKER_PAYLOAD_PREVIEW_READY"}),
        ("9D", result.get("adapter_mapping"), ("outcome",), {"READY", "ADAPTER_MAPPING_VALID"}),
        ("9E", result.get("shadow_rehearsal"), ("outcome",), {"SHADOW_HANDOFF_READY_DISABLED"}),
    )
    for section, raw, names, success in stages:
        mapping = raw if isinstance(raw, Mapping) else {}
        outcome = _outcome(mapping, *names).upper()
        if outcome in {"NOT_EVALUATED", "", "NONE"}:
            return section, f"{section}_NOT_EVALUATED"
        if outcome not in success:
            return section, _reason(mapping, outcome)
    return "10E", "PAPER_ACTIVATION_BLOCKED_BY_DESIGN"


def evaluate_sections_4_to_9(
    *,
    page: str,
    resolution: Mapping[str, object] | None,
    database,
    instrument_key: str,
    evaluation_timestamp: object = None,
    historical_trade_records=None,
    account_risk_context: Mapping[str, object] | None = None,
    opportunity_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Run the same pure builders as the UI without rendering or side effects."""
    policy = POLICIES[page]
    ranking_policy = RANKING_POLICIES[policy.strategy_id]
    safeguard_policy = SAFEGUARD_POLICIES[policy.strategy_id]
    gate = build_execution_source_gate(resolution, policy)

    readiness_5a = build_contract_data_readiness(
        gate=gate,
        resolution=resolution,
        database=database,
        instrument_key=str(instrument_key),
    )
    market_context_5b = enrich_contract_market_context(
        readiness_5a,
        database=database,
        instrument_key=str(instrument_key),
    )
    metadata_context_5c = dict(market_context_5b)
    safeguarded = apply_contract_safeguards(metadata_context_5c, policy=safeguard_policy)
    ranking = rank_strategy_contracts(safeguarded, policy=ranking_policy)
    audit = build_selection_audit(ranking, policy=ranking_policy)
    option_direction = build_option_chain_directional_evidence(
        readiness_5a,
        database=database,
        instrument_key=str(instrument_key),
    )
    candidate = build_candidate_readiness(
        gate=gate,
        resolution=resolution,
        safeguarded=safeguarded,
        ranking=ranking,
        option_direction=option_direction,
        evaluation_timestamp=evaluation_timestamp,
    )
    downstream_candidates = _candidate_copy_with_contract_fields(candidate, ranking)

    if isinstance(historical_trade_records, (list, tuple)):
        historical_records = [
            dict(row) for row in historical_trade_records if isinstance(row, Mapping)
        ]
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

    discovered_risk_context = load_account_risk_context(database)
    supplied_risk_context = account_risk_context if isinstance(account_risk_context, Mapping) else {}
    risk_context = merge_account_context(discovered_risk_context, supplied_risk_context)
    supplied_opportunity_context = opportunity_context if isinstance(opportunity_context, Mapping) else {}
    opportunity_source = build_opportunity_context(
        downstream_candidates,
        historical_records=historical_records,
        account_context=risk_context,
        explicit_context=supplied_opportunity_context,
    )
    opportunity = build_opportunity_history_gate(
        downstream_candidates,
        opportunity_context=opportunity_source,
        historical_records=historical_records,
        history_source=history_source,
    )
    risk_input = forward_candidates_for_risk(opportunity)
    risk = build_risk_readiness(risk_input, risk_context=risk_context)
    risk["account_context_status"] = risk_context.get("context_status")
    risk["account_context_source_version"] = risk_context.get("context_source_version")
    risk["account_context_evaluated_at"] = risk_context.get("context_evaluated_at")
    risk["account_context_provenance"] = risk_context.get("field_provenance")

    portfolio = build_portfolio_admission(opportunity, risk, account_context=risk_context)
    reservation = build_capital_reservation_proposal(portfolio, account_context=risk_context)
    final_admission = build_final_admission(
        reservation,
        execution_source_gate=gate,
        account_context=risk_context,
    )
    committee = build_execution_committee(final_admission)
    order_specification = build_order_specification(committee)
    payload_preview = build_broker_payload_preview(order_specification)
    adapter_mapping = build_adapter_mapping_validation(payload_preview)
    shadow_rehearsal = build_shadow_submission_rehearsal(adapter_mapping)
    live_activation = build_live_activation_readiness(shadow_rehearsal)

    result = {
        "pipeline_version": HEADLESS_PIPELINE_VERSION,
        "page": page,
        "strategy_id": policy.strategy_id,
        "resolution": dict(resolution or {}),
        "gate": gate,
        "readiness": readiness_5a,
        "readiness_5a": readiness_5a,
        "market_context_5b": market_context_5b,
        "metadata_context_5c": metadata_context_5c,
        "safeguarded": safeguarded,
        "ranking": ranking,
        "audit": audit,
        "option_direction": option_direction,
        "candidate": candidate,
        "history_source": history_source,
        "opportunity_context": opportunity_source,
        "opportunity": opportunity,
        "risk": risk,
        "portfolio": portfolio,
        "reservation": reservation,
        "final_admission": final_admission,
        "committee": committee,
        "order_specification": order_specification,
        "payload_preview": payload_preview,
        "adapter_mapping": adapter_mapping,
        "shadow_rehearsal": shadow_rehearsal,
        "live_activation": live_activation,
        "source_read_only": True,
        "persisted": False,
        "capital_reserved": False,
        "bundle_consumed": False,
        "position_created": False,
        "order_created": False,
        "order_submitted": False,
    }
    section, reason = _first_blocking_terminal(result)
    result["terminal_section"] = section
    result["terminal_reason"] = reason
    return result


__all__ = ["HEADLESS_PIPELINE_VERSION", "evaluate_sections_4_to_9"]
