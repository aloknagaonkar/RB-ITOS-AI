from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable, Mapping
import hashlib


FINAL_OUTCOMES = {
    "SUCCESS",
    "FAILURE",
    "BREAKEVEN",
    "EXPIRED_WITHOUT_ENTRY",
    "REJECTED_BY_COMMITTEE",
    "SUPPRESSED_BY_COOLDOWN",
    "INVALIDATED_BEFORE_ENTRY",
}


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


@dataclass(frozen=True)
class SignalTradeAttributionRecord:
    ledger_id: str
    instrument_key: str
    regime_snapshot_id: str
    transition_id: str
    bundle_id: str
    primary_signal_id: str
    primary_setup_type: str
    supporting_signal_ids: tuple[str, ...]
    supporting_setup_types: tuple[str, ...]
    direction: str
    detected_at: str
    trigger_level: float | None
    invalidation_level: float | None
    fresh_until: str
    red_bar_alignment: str

    candidate_id: str | None = None
    candidate_status: str | None = None
    candidate_created_at: str | None = None

    opportunity_id: str | None = None
    opportunity_status: str | None = None
    opportunity_created_at: str | None = None

    committee_decision_id: str | None = None
    committee_decision: str | None = None
    committee_reason: str | None = None
    committee_decided_at: str | None = None

    trade_id: str | None = None
    trade_mode: str | None = None
    option_side: str | None = None
    option_symbol: str | None = None
    entry_time: str | None = None
    entry_price: float | None = None
    exit_time: str | None = None
    exit_price: float | None = None
    realized_pnl: float | None = None
    pnl_percentage: float | None = None
    maximum_favorable_excursion: float | None = None
    maximum_adverse_excursion: float | None = None
    target_hit: bool | None = None
    stop_hit: bool | None = None
    exit_reason: str | None = None
    outcome: str | None = None

    execution_allowed: bool = False

    def as_record(self) -> dict[str, object]:
        return {
            **self.__dict__,
            "supporting_signal_ids": list(self.supporting_signal_ids),
            "supporting_setup_types": list(self.supporting_setup_types),
            "execution_allowed": False,
        }


def create_ledger_record(
    bundle: Mapping[str, object],
    *,
    instrument_key: str,
) -> SignalTradeAttributionRecord:
    bundle_id = str(bundle.get("bundle_id") or "")
    ledger_id = _stable_id(
        "LEDGER",
        instrument_key,
        bundle_id,
        bundle.get("detected_at"),
    )
    return SignalTradeAttributionRecord(
        ledger_id=ledger_id,
        instrument_key=instrument_key,
        regime_snapshot_id=str(bundle.get("regime_snapshot_id") or ""),
        transition_id=str(bundle.get("transition_id") or ""),
        bundle_id=bundle_id,
        primary_signal_id=str(bundle.get("primary_signal_id") or ""),
        primary_setup_type=str(bundle.get("primary_setup_type") or ""),
        supporting_signal_ids=tuple(bundle.get("supporting_signal_ids") or []),
        supporting_setup_types=tuple(bundle.get("supporting_setup_types") or []),
        direction=str(bundle.get("direction") or ""),
        detected_at=str(bundle.get("detected_at") or ""),
        trigger_level=bundle.get("trigger_level"),
        invalidation_level=bundle.get("invalidation_level"),
        fresh_until=str(bundle.get("fresh_until") or ""),
        red_bar_alignment=str(bundle.get("red_bar_alignment") or "NOT_AVAILABLE"),
        execution_allowed=False,
    )


def link_candidate(
    record: SignalTradeAttributionRecord,
    *,
    candidate_id: str,
    status: str,
    created_at: str,
) -> SignalTradeAttributionRecord:
    return replace(
        record,
        candidate_id=candidate_id,
        candidate_status=status,
        candidate_created_at=created_at,
        execution_allowed=False,
    )


def link_opportunity(
    record: SignalTradeAttributionRecord,
    *,
    opportunity_id: str,
    status: str,
    created_at: str,
) -> SignalTradeAttributionRecord:
    return replace(
        record,
        opportunity_id=opportunity_id,
        opportunity_status=status,
        opportunity_created_at=created_at,
        execution_allowed=False,
    )


def link_committee_decision(
    record: SignalTradeAttributionRecord,
    *,
    decision_id: str,
    decision: str,
    reason: str | None,
    decided_at: str,
) -> SignalTradeAttributionRecord:
    outcome = record.outcome
    if decision.upper() in {"REJECTED", "BLOCKED"} and record.trade_id is None:
        outcome = "REJECTED_BY_COMMITTEE"
    return replace(
        record,
        committee_decision_id=decision_id,
        committee_decision=decision,
        committee_reason=reason,
        committee_decided_at=decided_at,
        outcome=outcome,
        execution_allowed=False,
    )


def link_trade_entry(
    record: SignalTradeAttributionRecord,
    *,
    trade_id: str,
    trade_mode: str,
    option_side: str,
    option_symbol: str | None,
    entry_time: str,
    entry_price: float,
) -> SignalTradeAttributionRecord:
    return replace(
        record,
        trade_id=trade_id,
        trade_mode=trade_mode,
        option_side=option_side,
        option_symbol=option_symbol,
        entry_time=entry_time,
        entry_price=float(entry_price),
        outcome=None,
        execution_allowed=False,
    )


def close_trade(
    record: SignalTradeAttributionRecord,
    *,
    exit_time: str,
    exit_price: float,
    realized_pnl: float,
    pnl_percentage: float,
    maximum_favorable_excursion: float | None,
    maximum_adverse_excursion: float | None,
    target_hit: bool | None,
    stop_hit: bool | None,
    exit_reason: str,
) -> SignalTradeAttributionRecord:
    pnl = float(realized_pnl)
    if pnl > 0:
        outcome = "SUCCESS"
    elif pnl < 0:
        outcome = "FAILURE"
    else:
        outcome = "BREAKEVEN"

    return replace(
        record,
        exit_time=exit_time,
        exit_price=float(exit_price),
        realized_pnl=pnl,
        pnl_percentage=float(pnl_percentage),
        maximum_favorable_excursion=(
            float(maximum_favorable_excursion)
            if maximum_favorable_excursion is not None else None
        ),
        maximum_adverse_excursion=(
            float(maximum_adverse_excursion)
            if maximum_adverse_excursion is not None else None
        ),
        target_hit=target_hit,
        stop_hit=stop_hit,
        exit_reason=exit_reason,
        outcome=outcome,
        execution_allowed=False,
    )


def classify_unentered(
    record: SignalTradeAttributionRecord,
    outcome: str,
) -> SignalTradeAttributionRecord:
    if outcome not in FINAL_OUTCOMES:
        raise ValueError(f"Unsupported attribution outcome: {outcome}")
    if record.trade_id is not None:
        raise ValueError("Cannot classify an entered trade as unentered.")
    return replace(record, outcome=outcome, execution_allowed=False)
