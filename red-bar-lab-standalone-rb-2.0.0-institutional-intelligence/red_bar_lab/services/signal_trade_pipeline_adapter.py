from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from red_bar_lab.services.signal_trade_attribution import (
    SignalTradeAttributionRecord,
    link_candidate,
    link_opportunity,
    link_committee_decision,
    link_trade_entry,
    close_trade,
)


def apply_pipeline_event(
    record: SignalTradeAttributionRecord,
    event_type: str,
    payload: Mapping[str, object],
) -> SignalTradeAttributionRecord:
    """Apply normalized existing-pipeline events to one attribution record."""
    event = event_type.upper()

    if event == "CANDIDATE":
        return link_candidate(
            record,
            candidate_id=str(payload.get("candidate_id") or ""),
            status=str(payload.get("status") or "UNKNOWN"),
            created_at=str(payload.get("created_at") or ""),
        )

    if event == "OPPORTUNITY":
        return link_opportunity(
            record,
            opportunity_id=str(payload.get("opportunity_id") or ""),
            status=str(payload.get("status") or "UNKNOWN"),
            created_at=str(payload.get("created_at") or ""),
        )

    if event == "COMMITTEE":
        return link_committee_decision(
            record,
            decision_id=str(payload.get("decision_id") or ""),
            decision=str(payload.get("decision") or "UNKNOWN"),
            reason=(
                str(payload.get("reason"))
                if payload.get("reason") is not None else None
            ),
            decided_at=str(payload.get("decided_at") or ""),
        )

    if event == "TRADE_ENTRY":
        return link_trade_entry(
            record,
            trade_id=str(payload.get("trade_id") or ""),
            trade_mode=str(payload.get("trade_mode") or "PAPER"),
            option_side=str(payload.get("option_side") or ""),
            option_symbol=(
                str(payload.get("option_symbol"))
                if payload.get("option_symbol") is not None else None
            ),
            entry_time=str(payload.get("entry_time") or ""),
            entry_price=float(payload.get("entry_price") or 0.0),
        )

    if event == "TRADE_EXIT":
        return close_trade(
            record,
            exit_time=str(payload.get("exit_time") or ""),
            exit_price=float(payload.get("exit_price") or 0.0),
            realized_pnl=float(payload.get("realized_pnl") or 0.0),
            pnl_percentage=float(payload.get("pnl_percentage") or 0.0),
            maximum_favorable_excursion=payload.get(
                "maximum_favorable_excursion"
            ),
            maximum_adverse_excursion=payload.get(
                "maximum_adverse_excursion"
            ),
            target_hit=payload.get("target_hit"),
            stop_hit=payload.get("stop_hit"),
            exit_reason=str(payload.get("exit_reason") or "UNKNOWN"),
        )

    raise ValueError(f"Unsupported pipeline event type: {event_type}")
