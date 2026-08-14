from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd


CHAIN_CONFIDENCE = {
    "EXACT_CHAIN_MATCH": 1.00,
    "STRONG_CHAIN_MATCH": 0.90,
    "PARTIAL_CHAIN_MATCH": 0.70,
    "AMBIGUOUS_MATCH": 0.40,
    "NO_MATCH": 0.00,
}

SIGNAL_TIME_FIELDS = (
    "confirmation_timestamp",
    "cross_timestamp",
    "signal_timestamp",
    "detected_timestamp",
    "triggered_at",
    "signal_time",
    "attempted_at",
    "decision_timestamp",
    "bar_timestamp",
    "candle_timestamp",
    "observed_at",
    "event_timestamp",
    "evaluated_at",
    "timestamp",
    "created_at",
    "updated_at",
)

PIPELINE_TIME_FIELDS = (
    "evaluated_at",
    "executed_at",
    "entry_timestamp",
    "exit_timestamp",
    "confirmation_timestamp",
    "cross_timestamp",
    "triggered_at",
    "event_timestamp",
    "timestamp",
    "created_at",
    "updated_at",
)


def _timestamp(value: object) -> pd.Timestamp | None:
    """Parse and normalize timestamps for safe comparison.

    Historical rows may mix tz-naive values with timezone-aware values.
    All internal comparisons use UTC-naive timestamps:
    - aware timestamp -> convert to UTC, then remove timezone
    - naive timestamp -> keep unchanged

    Original values remain available on source rows for display.
    """
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None

    try:
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
    except Exception:
        try:
            ts = ts.tz_localize(None)
        except Exception:
            return None
    return ts


def _looks_temporal(field: str) -> bool:
    key = field.lower()
    return (
        key.endswith("_at")
        or "time" in key
        or "timestamp" in key
        or key.endswith("_date")
        or key in {"date", "as_of"}
    )


def timestamp_candidates(
    row: Mapping[str, object],
    preferred_fields: Iterable[str],
) -> list[tuple[str, pd.Timestamp]]:
    """Return parseable timestamp candidates in deterministic priority order."""
    ordered = list(preferred_fields)
    dynamic = sorted(
        str(key)
        for key in row.keys()
        if _looks_temporal(str(key)) and str(key) not in ordered
    )
    result: list[tuple[str, pd.Timestamp]] = []
    seen: set[tuple[str, str]] = set()
    for field in ordered + dynamic:
        ts = _timestamp(row.get(field))
        if ts is None:
            continue
        identity = (field, str(ts))
        if identity in seen:
            continue
        seen.add(identity)
        result.append((field, ts))
    return result


def best_time_in_window(
    row: Mapping[str, object],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    preferred_fields: Iterable[str],
) -> tuple[str | None, pd.Timestamp | None]:
    """Prefer a domain timestamp inside the requested bundle window.

    This avoids selecting an ingestion `created_at` timestamp when a valid
    market-event timestamp is present under another field.
    """
    candidates = timestamp_candidates(row, preferred_fields)
    in_window = [
        (field, ts)
        for field, ts in candidates
        if start <= ts <= end
    ]
    if in_window:
        return min(
            in_window,
            key=lambda item: abs((item[1] - start).total_seconds()),
        )
    return (candidates[0] if candidates else (None, None))


def signal_event_time(row: Mapping[str, object]) -> pd.Timestamp | None:
    candidates = timestamp_candidates(row, SIGNAL_TIME_FIELDS)
    return candidates[0][1] if candidates else None


def row_event_time(row: Mapping[str, object]) -> pd.Timestamp | None:
    candidates = timestamp_candidates(row, PIPELINE_TIME_FIELDS)
    return candidates[0][1] if candidates else None


def direction_of(row: Mapping[str, object]) -> str:
    for field in (
        "direction",
        "signal_direction",
        "market_direction",
        "trade_direction",
    ):
        value = str(row.get(field) or "").upper()
        if value in {"BULLISH", "BEARISH"}:
            return value

    option_type = str(
        row.get("option_type")
        or row.get("option_side")
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


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _rank(value: object) -> int:
    try:
        return int(value)
    except Exception:
        return 999999


def _accepted(row: Mapping[str, object]) -> int:
    decision = str(row.get("decision") or "").upper()
    return int(
        bool(row.get("eligible"))
        or decision in {
            "SELECTED",
            "APPROVED",
            "EXECUTE",
            "ACCEPTED",
            "PASS",
            "ELIGIBLE",
        }
    )


def _candidate_sort_key(row: Mapping[str, object]) -> tuple:
    return (
        -_accepted(row),
        _rank(row.get("candidate_rank")),
        -_number(
            row.get("selection_score")
            or row.get("candidate_score")
            or row.get("opportunity_score")
        ),
    )


def _signal_id(row: Mapping[str, object]) -> str:
    for field in (
        "signal_id",
        "pipeline_signal_id",
        "source_signal_id",
        "parent_signal_id",
    ):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


@dataclass(frozen=True)
class TargetedPipelineMatchRequest:
    instrument_key: str
    grace_minutes: int = 45


class TargetedHistoricalPipelineResolver:
    """Resolve one historical bundle through one unique pipeline signal."""

    def __init__(self, *, database, grace_minutes: int = 45):
        self.database = database
        self.grace_minutes = int(grace_minutes)

    def _group_signal_candidates(
        self,
        rows: Iterable[Mapping[str, object]],
        *,
        detected: pd.Timestamp,
        upper: pd.Timestamp,
        direction: str,
        instrument_key: str,
        used_signal_ids: set[str],
        preferred_fields: Iterable[str],
    ) -> list[dict[str, object]]:
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)

        for original in rows:
            row = dict(original)
            signal_id = _signal_id(row)
            if not signal_id or signal_id in used_signal_ids:
                continue

            row_instrument = str(
                row.get("instrument_key")
                or row.get("underlying_key")
                or ""
            )
            if row_instrument and row_instrument != instrument_key:
                continue

            row_direction = direction_of(row)
            if direction and row_direction and direction != row_direction:
                continue

            time_field, event_time = best_time_in_window(
                row,
                start=detected,
                end=upper,
                preferred_fields=preferred_fields,
            )
            if event_time is None or not detected <= event_time <= upper:
                continue

            row["_resolved_time_field"] = time_field
            row["_resolved_event_time"] = event_time
            grouped[signal_id].append(row)

        candidates: list[dict[str, object]] = []
        for signal_id, group in grouped.items():
            representative = sorted(
                group,
                key=lambda row: (
                    abs(
                        (
                            row["_resolved_event_time"] - detected
                        ).total_seconds()
                    ),
                    *_candidate_sort_key(row),
                ),
            )[0]
            candidates.append(
                {
                    "signal_id": signal_id,
                    "rows": group,
                    "representative": representative,
                    "event_time": representative[
                        "_resolved_event_time"
                    ],
                    "time_field": representative[
                        "_resolved_time_field"
                    ],
                    "delta_seconds": abs(
                        (
                            representative["_resolved_event_time"]
                            - detected
                        ).total_seconds()
                    ),
                    "accepted": _accepted(representative),
                    "candidate_rank": _rank(
                        representative.get("candidate_rank")
                    ),
                    "score": _number(
                        representative.get("selection_score")
                        or representative.get("candidate_score")
                        or representative.get("opportunity_score")
                    ),
                }
            )
        return candidates

    @staticmethod
    def _resolution_rank(
        candidate: Mapping[str, object],
        primary_signal_id: str,
    ) -> tuple:
        return (
            0
            if primary_signal_id
            and candidate["signal_id"] == primary_signal_id
            else 1,
            candidate["delta_seconds"],
            -candidate["accepted"],
            candidate["candidate_rank"],
            -candidate["score"],
        )

    def _choose_unique(
        self,
        candidates: list[dict[str, object]],
        *,
        primary_signal_id: str,
    ) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
        if not candidates:
            return None, []
        ordered = sorted(
            candidates,
            key=lambda row: self._resolution_rank(
                row, primary_signal_id
            ),
        )
        best_rank = self._resolution_rank(
            ordered[0], primary_signal_id
        )
        tied = [
            row
            for row in ordered
            if self._resolution_rank(row, primary_signal_id)
            == best_rank
        ]
        return (ordered[0] if len(tied) == 1 else None), tied

    def resolve(
        self,
        bundle: Mapping[str, object],
        signal_rows: list[Mapping[str, object]],
        *,
        instrument_key: str,
        used_signal_ids: set[str] | None = None,
        selection_fallback_rows: list[Mapping[str, object]] | None = None,
    ) -> dict[str, object]:
        used_signal_ids = (
            used_signal_ids if used_signal_ids is not None else set()
        )
        detected = _timestamp(bundle.get("detected_at"))
        fresh_until = _timestamp(bundle.get("fresh_until"))
        direction = direction_of(bundle)
        primary_signal_id = str(
            bundle.get("primary_signal_id") or ""
        )

        if detected is None:
            return self._empty(
                bundle, "NO_MATCH", "BUNDLE_TIME_MISSING"
            )

        upper = (
            fresh_until if fresh_until is not None else detected
        ) + pd.Timedelta(minutes=self.grace_minutes)

        signal_candidates = self._group_signal_candidates(
            signal_rows,
            detected=detected,
            upper=upper,
            direction=direction,
            instrument_key=instrument_key,
            used_signal_ids=used_signal_ids,
            preferred_fields=SIGNAL_TIME_FIELDS,
        )
        chosen, tied = self._choose_unique(
            signal_candidates,
            primary_signal_id=primary_signal_id,
        )
        source = "SIGNAL_ATTEMPTS"

        if chosen is None and not signal_candidates:
            selection_candidates = self._group_signal_candidates(
                selection_fallback_rows or [],
                detected=detected,
                upper=upper,
                direction=direction,
                instrument_key=instrument_key,
                used_signal_ids=used_signal_ids,
                preferred_fields=PIPELINE_TIME_FIELDS,
            )
            chosen, tied = self._choose_unique(
                selection_candidates,
                primary_signal_id=primary_signal_id,
            )
            signal_candidates = selection_candidates
            source = "SELECTION_FALLBACK"

        candidate_ids = [
            str(row["signal_id"])
            for row in sorted(
                signal_candidates,
                key=lambda item: self._resolution_rank(
                    item, primary_signal_id
                ),
            )[:10]
        ]

        if chosen is None:
            if tied:
                result = self._empty(
                    bundle,
                    "AMBIGUOUS_MATCH",
                    "MULTIPLE_UNIQUE_SIGNAL_IDS_WITH_EQUAL_RANK",
                )
                result.update(
                    {
                        "pipeline_signal_source": source,
                        "pipeline_signal_candidates": len(
                            signal_candidates
                        ),
                        "nearest_signal_candidates": len(tied),
                        "candidate_pipeline_signal_ids": ",".join(
                            str(row["signal_id"]) for row in tied[:10]
                        ),
                        "ambiguity_reason": (
                            "Multiple unique signal IDs remained tied after "
                            "primary-ID, timestamp, eligibility, rank and "
                            "score resolution."
                        ),
                    }
                )
                return result

            result = self._empty(
                bundle,
                "NO_MATCH",
                "NO_PIPELINE_SIGNAL_OR_SELECTION_IN_WINDOW",
            )
            result["pipeline_signal_source"] = None
            return result

        signal_id = str(chosen["signal_id"])
        used_signal_ids.add(signal_id)
        representative = dict(chosen["representative"])
        representative.setdefault("signal_id", signal_id)

        selection = _safe_read(
            self.database,
            "read_trade_selection_evaluations",
            signal_id=signal_id,
            limit=1000,
        )
        if not selection and source == "SELECTION_FALLBACK":
            selection = [
                dict(row) for row in chosen.get("rows", [])
            ]

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
            row
            for row in all_orders
            if _signal_id(row) == signal_id
        ]

        selected = (
            sorted(selection, key=_candidate_sort_key)[0]
            if selection else {}
        )
        candidate_symbol = selected.get("candidate_symbol")
        if not candidate_symbol and opportunities:
            candidate_symbol = sorted(
                opportunities, key=_candidate_sort_key
            )[0].get("candidate_symbol")

        if candidate_symbol:
            opportunities = [
                row
                for row in opportunities
                if not row.get("candidate_symbol")
                or row.get("candidate_symbol") == candidate_symbol
            ]
            committee = [
                row
                for row in committee
                if not row.get("candidate_symbol")
                or row.get("candidate_symbol") == candidate_symbol
            ]
            queue = [
                row
                for row in queue
                if not row.get("candidate_symbol")
                or row.get("candidate_symbol") == candidate_symbol
            ]
            orders = [
                row
                for row in orders
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
                    _rank(row.get("candidate_rank")),
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
            bool(primary_signal_id)
            and primary_signal_id == signal_id
        )

        if direct_signal_match and chain_depth >= 3:
            resolution = "EXACT_CHAIN_MATCH"
        elif chain_depth >= 4:
            resolution = "STRONG_CHAIN_MATCH"
        else:
            resolution = "PARTIAL_CHAIN_MATCH"

        return {
            "bundle_id": bundle.get("bundle_id"),
            "detected_at": bundle.get("detected_at"),
            "fresh_until": bundle.get("fresh_until"),
            "direction": bundle.get("direction"),
            "primary_setup_type": bundle.get(
                "primary_setup_type"
            ),
            "primary_signal_id": primary_signal_id,
            "pipeline_signal_id": signal_id,
            "pipeline_signal_time": (
                chosen["event_time"].isoformat()
                if chosen.get("event_time") is not None
                else None
            ),
            "pipeline_signal_time_field": chosen["time_field"],
            "pipeline_signal_state": representative.get("state"),
            "pipeline_signal_source": source,
            "pipeline_signal_candidates": len(signal_candidates),
            "nearest_signal_candidates": 1,
            "candidate_pipeline_signal_ids": ",".join(candidate_ids),
            "ambiguity_reason": None,
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
            "opportunity_decision": selected_opportunity.get(
                "decision"
            ),
            "opportunity_reason": selected_opportunity.get("reason"),
            "committee_match_count": len(committee),
            "committee_decision": selected_committee.get("decision"),
            "committee_reason": selected_committee.get("reason"),
            "queue_match_count": len(queue),
            "queue_id": selected_queue.get("queue_id"),
            "queue_status": selected_queue.get("status"),
            "order_match_count": len(orders),
            "order_id": selected_order.get("order_id"),
            "order_status": selected_order.get("status"),
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
            "primary_setup_type": bundle.get(
                "primary_setup_type"
            ),
            "primary_signal_id": bundle.get("primary_signal_id"),
            "pipeline_signal_id": None,
            "pipeline_signal_time": None,
            "pipeline_signal_time_field": None,
            "pipeline_signal_state": None,
            "pipeline_signal_source": None,
            "pipeline_signal_candidates": 0,
            "nearest_signal_candidates": 0,
            "candidate_pipeline_signal_ids": None,
            "ambiguity_reason": None,
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
