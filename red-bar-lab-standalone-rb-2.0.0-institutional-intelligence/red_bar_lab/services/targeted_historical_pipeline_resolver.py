from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
import hashlib

import pandas as pd


CHAIN_CONFIDENCE = {
    "EXACT_CHAIN_MATCH": 1.00,
    "STRONG_CHAIN_MATCH": 0.90,
    "PARTIAL_CHAIN_MATCH": 0.70,
    "AMBIGUOUS_MATCH": 0.40,
    "NO_MATCH": 0.00,
}


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value)
    except Exception:
        return None


def signal_event_time(
    row: Mapping[str, object],
) -> pd.Timestamp | None:
    for field in (
        "confirmation_timestamp",
        "cross_timestamp",
        "created_at",
        "signal_timestamp",
        "detected_timestamp",
        "observed_at",
        "timestamp",
    ):
        ts = _timestamp(row.get(field))
        if ts is not None:
            return ts
    return None


def row_event_time(
    row: Mapping[str, object],
) -> pd.Timestamp | None:
    for field in (
        "evaluated_at",
        "created_at",
        "updated_at",
        "executed_at",
        "entry_timestamp",
        "exit_timestamp",
        "confirmation_timestamp",
        "cross_timestamp",
    ):
        ts = _timestamp(row.get(field))
        if ts is not None:
            return ts
    return None


def direction_of(row: Mapping[str, object]) -> str:
    value = str(row.get("direction") or "").upper()
    if value in {"BULLISH", "BEARISH"}:
        return value
    option_type = str(
        row.get("option_type")
        or row.get("side")
        or ""
    ).upper()
    if option_type == "CE":
        return "BULLISH"
    if option_type == "PE":
        return "BEARISH"
    return ""


def _safe_read(database, method: str, *args, **kwargs):
    fn = getattr(database, method, None)
    if fn is None:
        return []
    try:
        return [dict(row) for row in (fn(*args, **kwargs) or [])]
    except TypeError:
        try:
            return [dict(row) for row in (fn(*args) or [])]
        except Exception:
            return []
    except Exception:
        return []


def _candidate_sort_key(row: Mapping[str, object]) -> tuple:
    eligible = int(bool(row.get("eligible")))
    decision = str(row.get("decision") or "").upper()
    accepted = int(
        decision in {
            "SELECTED",
            "APPROVED",
            "EXECUTE",
            "ACCEPTED",
            "PASS",
            "ELIGIBLE",
        }
    )
    rank = int(row.get("candidate_rank") or 999999)
    score = float(
        row.get("selection_score")
        or row.get("candidate_score")
        or row.get("opportunity_score")
        or 0.0
    )
    return (-eligible, -accepted, rank, -score)


@dataclass(frozen=True)
class TargetedPipelineMatchRequest:
    instrument_key: str
    grace_minutes: int = 45


class TargetedHistoricalPipelineResolver:
    """Resolve one historical bundle through exact signal-id queries."""

    def __init__(self, *, database):
        self.database = database

    def resolve(
        self,
        bundle: Mapping[str, object],
        signal_rows: list[Mapping[str, object]],
        *,
        instrument_key: str,
        used_signal_ids: set[str] | None = None,
        selection_fallback_rows: list[Mapping[str, object]] | None = None,
    ) -> dict[str, object]:
        used_signal_ids = used_signal_ids if used_signal_ids is not None else set()
        detected = _timestamp(bundle.get("detected_at"))
        fresh_until = _timestamp(bundle.get("fresh_until"))
        direction = direction_of(bundle)

        if detected is None:
            return self._empty(bundle, "NO_MATCH", "BUNDLE_TIME_MISSING")

        upper = (
            fresh_until if fresh_until is not None else detected
        ) + pd.Timedelta(minutes=45)

        candidates = []
        for row in signal_rows:
            signal_id = str(row.get("signal_id") or "")
            if not signal_id or signal_id in used_signal_ids:
                continue
            if str(row.get("instrument_key") or instrument_key) != instrument_key:
                continue
            row_direction = direction_of(row)
            if direction and row_direction and direction != row_direction:
                continue
            event_time = signal_event_time(row)
            if event_time is None or not detected <= event_time <= upper:
                continue
            delta_seconds = abs((event_time - detected).total_seconds())
            candidates.append((delta_seconds, dict(row)))

        recovered_from_selection = False
        if not candidates:
            selection_candidates = []
            for row in selection_fallback_rows or []:
                signal_id = str(row.get("signal_id") or "")
                if not signal_id or signal_id in used_signal_ids:
                    continue
                row_direction = direction_of(row)
                if direction and row_direction and direction != row_direction:
                    continue
                event_time = row_event_time(row)
                if event_time is None or not detected <= event_time <= upper:
                    continue
                delta_seconds = abs(
                    (event_time - detected).total_seconds()
                )
                selection_candidates.append(
                    (delta_seconds, dict(row))
                )

            if not selection_candidates:
                return self._empty(
                    bundle,
                    "NO_MATCH",
                    "NO_PIPELINE_SIGNAL_OR_SELECTION_IN_WINDOW",
                )

            selection_candidates.sort(key=lambda item: item[0])
            nearest_delta = selection_candidates[0][0]
            nearest_selection = [
                row
                for delta, row in selection_candidates
                if delta == nearest_delta
            ]
            if len(nearest_selection) > 1:
                return {
                    **self._empty(
                        bundle,
                        "AMBIGUOUS_MATCH",
                        "MULTIPLE_EQUALLY_NEAR_SELECTION_ROWS",
                    ),
                    "pipeline_signal_candidates": 0,
                    "selection_fallback_candidates": len(
                        selection_candidates
                    ),
                    "nearest_signal_candidates": 0,
                }

            recovered = nearest_selection[0]
            recovered_signal_id = str(
                recovered.get("signal_id") or ""
            )
            signal = {
                "signal_id": recovered_signal_id,
                "instrument_key": instrument_key,
                "direction": direction_of(recovered) or direction,
                "confirmation_timestamp": str(
                    row_event_time(recovered)
                ),
                "state": "RECOVERED_FROM_SELECTION",
            }
            candidates = [(nearest_delta, signal)]
            recovered_from_selection = True

        candidates.sort(key=lambda item: item[0])
        closest_delta = candidates[0][0]
        closest = [
            row for delta, row in candidates
            if delta == closest_delta
        ]
        if len(closest) > 1:
            return {
                **self._empty(
                    bundle,
                    "AMBIGUOUS_MATCH",
                    "MULTIPLE_EQUALLY_NEAR_PIPELINE_SIGNALS",
                ),
                "pipeline_signal_candidates": len(candidates),
                "nearest_signal_candidates": len(closest),
            }

        signal = closest[0]
        signal_id = str(signal.get("signal_id") or "")
        used_signal_ids.add(signal_id)

        selection = _safe_read(
            self.database,
            "read_trade_selection_evaluations",
            signal_id=signal_id,
            limit=1000,
        )
        opportunities = _safe_read(
            self.database,
            "read_opportunity_evaluations",
            signal_id=signal_id,
            limit=1000,
        )
        committee = _safe_read(
            self.database,
            "read_institutional_execution_evaluations",
            signal_id=signal_id,
            limit=1000,
        )
        queue = _safe_read(
            self.database,
            "read_execution_queue",
            signal_id=signal_id,
            limit=1000,
        )
        all_orders = _safe_read(
            self.database,
            "read_paper_execution_orders",
            "PAPER-STD",
        )
        orders = [
            row for row in all_orders
            if str(row.get("signal_id") or "") == signal_id
        ]

        selected = (
            sorted(selection, key=_candidate_sort_key)[0]
            if selection else {}
        )
        candidate_symbol = (
            selected.get("candidate_symbol")
            or (
                sorted(opportunities, key=_candidate_sort_key)[0].get(
                    "candidate_symbol"
                )
                if opportunities else None
            )
        )

        if candidate_symbol:
            opportunities = [
                row for row in opportunities
                if not row.get("candidate_symbol")
                or row.get("candidate_symbol") == candidate_symbol
            ]
            committee = [
                row for row in committee
                if not row.get("candidate_symbol")
                or row.get("candidate_symbol") == candidate_symbol
            ]
            queue = [
                row for row in queue
                if not row.get("candidate_symbol")
                or row.get("candidate_symbol") == candidate_symbol
            ]
            orders = [
                row for row in orders
                if not row.get("tradingsymbol")
                or row.get("tradingsymbol") == candidate_symbol
            ]

        selected_opportunity = (
            sorted(opportunities, key=_candidate_sort_key)[0]
            if opportunities else {}
        )
        selected_committee = (
            sorted(committee, key=_candidate_sort_key)[0]
            if committee else {}
        )
        selected_queue = (
            sorted(
                queue,
                key=lambda row: (
                    str(row.get("status") or "") not in {
                        "EXECUTED",
                        "APPROVED",
                        "EXECUTING",
                    },
                    int(row.get("candidate_rank") or 999999),
                ),
            )[0]
            if queue else {}
        )
        selected_order = (
            sorted(
                orders,
                key=lambda row: str(
                    row.get("entry_timestamp") or ""
                ),
            )[0]
            if orders else {}
        )

        chain_depth = sum(
            bool(items)
            for items in (
                selection,
                opportunities,
                committee,
                queue,
                orders,
            )
        )
        direct_signal_match = (
            str(bundle.get("primary_signal_id") or "") == signal_id
        )

        if direct_signal_match and chain_depth >= 3:
            resolution = "EXACT_CHAIN_MATCH"
        elif chain_depth >= 4:
            resolution = "STRONG_CHAIN_MATCH"
        elif chain_depth >= 1:
            resolution = "PARTIAL_CHAIN_MATCH"
        else:
            resolution = "PARTIAL_CHAIN_MATCH"

        committee_decision = str(
            selected_committee.get("decision") or ""
        )
        queue_status = str(selected_queue.get("status") or "")
        order_status = str(selected_order.get("status") or "")

        return {
            "bundle_id": bundle.get("bundle_id"),
            "detected_at": bundle.get("detected_at"),
            "fresh_until": bundle.get("fresh_until"),
            "direction": bundle.get("direction"),
            "primary_setup_type": bundle.get("primary_setup_type"),
            "primary_signal_id": bundle.get("primary_signal_id"),
            "pipeline_signal_id": signal_id,
            "pipeline_signal_time": str(signal_event_time(signal)),
            "pipeline_signal_state": signal.get("state"),
            "pipeline_signal_source": (
                "SELECTION_FALLBACK"
                if recovered_from_selection
                else "SIGNAL_ATTEMPTS"
            ),
            "pipeline_signal_candidates": len(candidates),
            "nearest_signal_candidates": 1,
            "candidate_matches_found": len(selection),
            "selected_candidate_id": (
                selected.get("id")
                or selected.get("candidate_id")
                or None
            ),
            "selected_candidate_symbol": candidate_symbol,
            "selection_decision": selected.get("decision"),
            "selection_reason": selected.get("reason"),
            "opportunity_match_count": len(opportunities),
            "opportunity_decision": selected_opportunity.get("decision"),
            "opportunity_reason": selected_opportunity.get("reason"),
            "committee_match_count": len(committee),
            "committee_decision": committee_decision or None,
            "committee_reason": selected_committee.get("reason"),
            "queue_match_count": len(queue),
            "queue_id": selected_queue.get("queue_id"),
            "queue_status": queue_status or None,
            "order_match_count": len(orders),
            "order_id": selected_order.get("order_id"),
            "order_status": order_status or None,
            "option_symbol": selected_order.get("tradingsymbol"),
            "option_type": selected_order.get("option_type"),
            "entry_timestamp": selected_order.get("entry_timestamp"),
            "exit_timestamp": selected_order.get("exit_timestamp"),
            "realized_pnl": selected_order.get("realized_pnl"),
            "match_resolution": resolution,
            "match_confidence": CHAIN_CONFIDENCE[resolution],
            "chain_depth": chain_depth,
            "source_read_only": True,
            "execution_allowed": False,
        }

    @staticmethod
    def _empty(
        bundle: Mapping[str, object],
        resolution: str,
        reason: str,
    ) -> dict[str, object]:
        return {
            "bundle_id": bundle.get("bundle_id"),
            "detected_at": bundle.get("detected_at"),
            "fresh_until": bundle.get("fresh_until"),
            "direction": bundle.get("direction"),
            "primary_setup_type": bundle.get("primary_setup_type"),
            "primary_signal_id": bundle.get("primary_signal_id"),
            "pipeline_signal_id": None,
            "pipeline_signal_candidates": 0,
            "nearest_signal_candidates": 0,
            "candidate_matches_found": 0,
            "selected_candidate_id": None,
            "selected_candidate_symbol": None,
            "selection_decision": None,
            "selection_reason": reason,
            "opportunity_match_count": 0,
            "committee_match_count": 0,
            "queue_match_count": 0,
            "order_match_count": 0,
            "match_resolution": resolution,
            "match_confidence": CHAIN_CONFIDENCE[resolution],
            "chain_depth": 0,
            "source_read_only": True,
            "execution_allowed": False,
        }
