from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path
from typing import Mapping
import json

import pandas as pd

from red_bar_lab.services.fresh_setup_bundle_store import (
    canonical_bundle_identity,
)
from red_bar_lab.services.targeted_historical_pipeline_resolver import (
    PIPELINE_TIME_FIELDS,
    SIGNAL_TIME_FIELDS,
    TargetedHistoricalPipelineResolver,
    timestamp_candidates,
)


MATCH_CONFIDENCE = {
    "EXACT_SIGNAL_ID": 1.00,
    "SIGNAL_AND_SYMBOL": 0.98,
    "DIRECTION_AND_WINDOW": 0.75,
    "AMBIGUOUS_MATCH": 0.40,
    "NO_MATCH": 0.00,
}

TIMESTAMP_FIELDS = (
    "evaluated_at",
    "created_at",
    "updated_at",
    "executed_at",
    "entry_timestamp",
    "exit_timestamp",
    "confirmation_timestamp",
    "detected_at",
    "signal_timestamp",
    "detected_timestamp",
    "confirmation_time",
    "observed_at",
    "created_timestamp",
    "event_timestamp",
    "timestamp",
    "cross_timestamp",
)


@dataclass(frozen=True)
class HistoricalAuditRequest:
    instrument_key: str
    date_from: date
    date_to: date
    start_time: time
    end_time: time
    direction: str = "ALL"
    setup_type: str = "ALL"
    maximum_days: int = 90

    def validate(self) -> None:
        if self.date_to < self.date_from:
            raise ValueError("End date must be on or after start date.")
        span = (self.date_to - self.date_from).days + 1
        if span > self.maximum_days:
            raise ValueError(
                f"Range contains {span} calendar days; maximum is "
                f"{self.maximum_days}."
            )
        if self.end_time < self.start_time:
            raise ValueError("End time must be after start time.")


def resolve_range_preset(preset: str, anchor: date) -> tuple[date, date]:
    key = preset.upper().strip()
    if key == "SINGLE DAY":
        return anchor, anchor
    if key == "PREVIOUS 5 TRADING DAYS":
        return _previous_trading_days(anchor, 5)
    if key == "PREVIOUS 10 TRADING DAYS":
        return _previous_trading_days(anchor, 10)
    if key == "PREVIOUS MONTH":
        first = anchor.replace(day=1)
        end = first - timedelta(days=1)
        return end.replace(day=1), end
    if key == "PREVIOUS 3 MONTHS":
        return anchor - timedelta(days=89), anchor
    return anchor, anchor


def _previous_trading_days(anchor: date, count: int) -> tuple[date, date]:
    days = []
    cursor = anchor
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return min(days), max(days)


def _timestamp(value: object) -> pd.Timestamp | None:
    """Normalize mixed aware/naive timestamps to UTC-naive."""
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


def _timestamp_info(
    row: Mapping[str, object],
    source: str | None = None,
    request: HistoricalAuditRequest | None = None,
) -> tuple[pd.Timestamp | None, bool, str | None]:
    preferred = (
        SIGNAL_TIME_FIELDS
        if source == "signals"
        else PIPELINE_TIME_FIELDS
    )
    candidates = timestamp_candidates(row, preferred)

    if request is not None:
        same_date = [
            (field, ts)
            for field, ts in candidates
            if request.date_from <= ts.date() <= request.date_to
        ]
        in_session = [
            (field, ts)
            for field, ts in same_date
            if request.start_time
            <= ts.time().replace(tzinfo=None)
            <= request.end_time
        ]
        if in_session:
            field, ts = in_session[0]
            return ts, True, field
        if same_date:
            field, ts = same_date[0]
            raw = str(row.get(field))
            has_time = (
                "T" in raw
                or " " in raw
                or ":" in raw
                or ts.time() != time(0, 0)
            )
            return ts, has_time, field

    if candidates:
        field, ts = candidates[0]
        raw = str(row.get(field))
        has_time = (
            "T" in raw
            or " " in raw
            or ":" in raw
            or ts.time() != time(0, 0)
        )
        return ts, has_time, field

    trading_date = row.get("trading_date")
    ts = _timestamp(trading_date)
    if ts is not None:
        return ts, False, "trading_date"
    return None, False, None


def _event_time(row: Mapping[str, object]) -> pd.Timestamp | None:
    return _timestamp_info(row)[0]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


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


def _direction(row: Mapping[str, object]) -> str:
    for field in ("direction", "signal_direction", "market_direction"):
        value = str(row.get(field) or "").upper()
        if value in {"BULLISH", "BEARISH"}:
            return value
    side = str(row.get("option_side") or row.get("side") or "").upper()
    return "BULLISH" if side == "CE" else "BEARISH" if side == "PE" else ""


def _instrument_matches(
    row: Mapping[str, object],
    instrument_key: str,
) -> bool:
    fields = (
        "instrument_key",
        "underlying_key",
        "underlying_instrument_key",
        "index_instrument_key",
    )
    present = [str(row.get(field) or "") for field in fields if row.get(field)]
    if not present:
        return True
    return instrument_key in present


def _row_identity(source: str, row: Mapping[str, object]) -> str:
    for field in (
        "evaluation_id",
        "decision_id",
        "queue_id",
        "order_id",
        "trade_id",
        "candidate_id",
        "opportunity_id",
        "signal_id",
        "id",
    ):
        value = row.get(field)
        if value not in (None, ""):
            return f"{source}:{field}:{value}"
    ts, _, _ = _timestamp_info(row)
    return (
        f"{source}:fallback:{ts}:"
        f"{row.get('candidate_symbol')}:{_direction(row)}"
    )


class RangeHistoricalAttributionAudit:
    QUERY_LIMITS = {
        "selection": 5000,
        "committee": 5000,
        "queue": 5000,
        "opportunity": 50000,
    }

    def __init__(
        self,
        *,
        database,
        runs_root: str | Path,
        grace_minutes: int = 45,
    ):
        self.database = database
        self.runs_root = Path(runs_root)
        self.grace_minutes = int(grace_minutes)

    def load_bundles(
        self,
        request: HistoricalAuditRequest,
    ) -> list[dict[str, object]]:
        request.validate()
        folder = self.runs_root / "fresh_setup_bundles_v43"
        selected: dict[
            tuple[str, str, str, str],
            dict[str, object],
        ] = {}

        for path in sorted(folder.glob("*.jsonl")) if folder.exists() else []:
            for row in _read_jsonl(path):
                ts = _timestamp(row.get("detected_at"))
                if ts is None:
                    continue
                if not request.date_from <= ts.date() <= request.date_to:
                    continue
                if not (
                    request.start_time
                    <= ts.time().replace(tzinfo=None)
                    <= request.end_time
                ):
                    continue
                if (
                    request.direction != "ALL"
                    and _direction(row) != request.direction
                ):
                    continue
                if (
                    request.setup_type != "ALL"
                    and str(row.get("primary_setup_type") or "")
                    != request.setup_type
                ):
                    continue

                payload = dict(row)
                payload.setdefault("instrument_key", request.instrument_key)
                key = canonical_bundle_identity(payload)
                current = selected.get(key)
                if current is None:
                    selected[key] = payload
                    continue

                current_backfill = bool(current.get("historical_backfill"))
                payload_backfill = bool(payload.get("historical_backfill"))
                if current_backfill and not payload_backfill:
                    selected[key] = payload

        rows = list(selected.values())
        rows.sort(key=lambda row: str(row.get("detected_at") or ""))
        return rows

    def _raw_pipeline(
        self,
        request: HistoricalAuditRequest,
    ) -> dict[str, list[dict[str, object]]]:
        signals = _safe_read(
            self.database,
            "read_signal_attempts_range",
            request.instrument_key,
            request.date_from.isoformat(),
            request.date_to.isoformat(),
        )
        selection, committee, queue = [], [], []
        current = request.date_from
        while current <= request.date_to:
            day = current.isoformat()
            selection.extend(
                _safe_read(
                    self.database,
                    "read_trade_selection_evaluations",
                    trading_date=day,
                    limit=self.QUERY_LIMITS["selection"],
                )
            )
            committee.extend(
                _safe_read(
                    self.database,
                    "read_institutional_execution_evaluations",
                    trading_date=day,
                    limit=self.QUERY_LIMITS["committee"],
                )
            )
            queue.extend(
                _safe_read(
                    self.database,
                    "read_execution_queue",
                    trading_date=day,
                    limit=self.QUERY_LIMITS["queue"],
                )
            )
            current += timedelta(days=1)

        return {
            "signals": signals,
            "selection": selection,
            "opportunity": _safe_read(
                self.database,
                "read_opportunity_evaluations",
                limit=self.QUERY_LIMITS["opportunity"],
            ),
            "committee": committee,
            "queue": queue,
            "orders": _safe_read(
                self.database,
                "read_paper_execution_orders",
                "PAPER-STD",
            ),
        }

    def _filter_source(
        self,
        source: str,
        rows: list[dict[str, object]],
        request: HistoricalAuditRequest,
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        raw = list(rows)
        date_rows = []
        session_rows = []
        session_unavailable_rows = []

        for row in raw:
            ts, has_time, _ = _timestamp_info(
                row,
                source=source,
                request=request,
            )
            if ts is None:
                continue
            if not request.date_from <= ts.date() <= request.date_to:
                continue
            date_rows.append(row)

            if not has_time:
                session_unavailable_rows.append(row)
                session_rows.append(row)
                continue

            if (
                request.start_time
                <= ts.time().replace(tzinfo=None)
                <= request.end_time
            ):
                session_rows.append(row)

        instrument_rows = [
            row
            for row in session_rows
            if _instrument_matches(row, request.instrument_key)
        ]
        direction_rows = [
            row
            for row in instrument_rows
            if request.direction == "ALL"
            or not _direction(row)
            or _direction(row) == request.direction
        ]

        limit = self.QUERY_LIMITS.get(source)
        limit_hit = bool(limit and len(raw) >= limit)

        discovered_timestamp_fields = sorted({
            field
            for row in raw[:200]
            for field, _ in timestamp_candidates(
                row,
                SIGNAL_TIME_FIELDS
                if source == "signals"
                else PIPELINE_TIME_FIELDS,
            )
        })
        discovered_signal_id_fields = sorted({
            field
            for row in raw[:200]
            for field in (
                "signal_id",
                "pipeline_signal_id",
                "source_signal_id",
                "parent_signal_id",
            )
            if row.get(field) not in (None, "")
        })
        sample_fields = sorted({
            str(field)
            for row in raw[:10]
            for field in row.keys()
        })

        return direction_rows, {
            "raw_rows": len(raw),
            "date_filtered": len(date_rows),
            "session_filtered": len(session_rows),
            "session_time_unavailable": len(session_unavailable_rows),
            "instrument_filtered": len(instrument_rows),
            "direction_filtered": len(direction_rows),
            "matching_rows": len(direction_rows),
            "query_limit": limit,
            "query_limit_hit": limit_hit,
            "result_complete": not limit_hit,
            "timestamp_fields_detected": ",".join(
                discovered_timestamp_fields
            ),
            "signal_id_fields_detected": ",".join(
                discovered_signal_id_fields
            ),
            "sample_field_names": ",".join(sample_fields[:30]),
        }

    def audit(self, request: HistoricalAuditRequest) -> dict[str, object]:
        bundles = self.load_bundles(request)
        raw = self._raw_pipeline(request)
        pipeline: dict[str, list[dict[str, object]]] = {}

        source_rows = [
            {
                "source": "v4.3 setup bundles",
                "raw_rows": len(bundles),
                "date_filtered": len(bundles),
                "session_filtered": len(bundles),
                "session_time_unavailable": 0,
                "instrument_filtered": len(bundles),
                "direction_filtered": len(bundles),
                "matching_rows": len(bundles),
                "query_limit": None,
                "query_limit_hit": False,
                "result_complete": True,
                "timestamp_fields_detected": "detected_at,fresh_until",
                "signal_id_fields_detected": "primary_signal_id",
                "sample_field_names": "",
                "available": bool(bundles),
                "read_only": True,
            }
        ]

        for source, rows in raw.items():
            filtered, counts = self._filter_source(
                source,
                rows,
                request,
            )
            pipeline[source] = filtered
            source_rows.append(
                {
                    "source": source,
                    **counts,
                    "available": bool(filtered),
                    "read_only": True,
                }
            )

        resolver = TargetedHistoricalPipelineResolver(
            database=self.database
        )
        used_signal_ids: set[str] = set()
        targeted_matches = [
            resolver.resolve(
                bundle,
                raw.get("signals", []),
                instrument_key=request.instrument_key,
                used_signal_ids=used_signal_ids,
                selection_fallback_rows=raw.get(
                    "selection", []
                ),
            )
            for bundle in bundles
        ]

        legacy_method_by_resolution = {
            "EXACT_CHAIN_MATCH": "EXACT_SIGNAL_ID",
            "STRONG_CHAIN_MATCH": "DIRECTION_AND_WINDOW",
            "PARTIAL_CHAIN_MATCH": "DIRECTION_AND_WINDOW",
            "AMBIGUOUS_MATCH": "AMBIGUOUS_MATCH",
            "NO_MATCH": "NO_MATCH",
        }
        for row in targeted_matches:
            row.setdefault(
                "match_method",
                legacy_method_by_resolution.get(
                    str(row.get("match_resolution") or ""),
                    "NO_MATCH",
                ),
            )

        return {
            "summary": {
                "date_from": request.date_from.isoformat(),
                "date_to": request.date_to.isoformat(),
                "calendar_days": (
                    request.date_to - request.date_from
                ).days + 1,
                "bundles": len(bundles),
                "exact_chain_matches": sum(
                    row["match_resolution"] == "EXACT_CHAIN_MATCH"
                    for row in targeted_matches
                ),
                "strong_chain_matches": sum(
                    row["match_resolution"] == "STRONG_CHAIN_MATCH"
                    for row in targeted_matches
                ),
                "partial_chain_matches": sum(
                    row["match_resolution"] == "PARTIAL_CHAIN_MATCH"
                    for row in targeted_matches
                ),
                "ambiguous_matches": sum(
                    row["match_resolution"] == "AMBIGUOUS_MATCH"
                    for row in targeted_matches
                ),
                "no_matches": sum(
                    row["match_resolution"] == "NO_MATCH"
                    for row in targeted_matches
                ),
                # Backward-compatible Sprint 4.3.5.1/1.2 aliases.
                "exact_matches": sum(
                    row["match_resolution"] == "EXACT_CHAIN_MATCH"
                    for row in targeted_matches
                ),
                "inferred_matches": sum(
                    row["match_resolution"] in {
                        "STRONG_CHAIN_MATCH",
                        "PARTIAL_CHAIN_MATCH",
                    }
                    for row in targeted_matches
                ),
                "incomplete_sources": sum(
                    not bool(row.get("result_complete"))
                    for row in source_rows
                ),
                "source_read_only": True,
                "execution_allowed": False,
            },
            "sources": source_rows,
            "matches": targeted_matches,
            "bundles": bundles,
        }

    def _candidate_rows(
        self,
        bundle: Mapping[str, object],
        pipeline: Mapping[str, list[dict[str, object]]],
    ) -> list[tuple[str, dict[str, object], float]]:
        detected = _timestamp(bundle.get("detected_at"))
        fresh = _timestamp(bundle.get("fresh_until"))
        if detected is None:
            return []
        upper = (
            fresh if fresh is not None else detected
        ) + pd.Timedelta(minutes=self.grace_minutes)
        direction = _direction(bundle)

        candidates = []
        for source, rows in pipeline.items():
            for row in rows:
                ts = _event_time(row)
                if ts is None or not detected <= ts <= upper:
                    continue
                row_direction = _direction(row)
                if direction and row_direction and direction != row_direction:
                    continue
                delta = abs((ts - detected).total_seconds())
                candidates.append((source, row, delta))
        return candidates

    def _match_bundles_one_to_one(
        self,
        bundles: list[dict[str, object]],
        pipeline: Mapping[str, list[dict[str, object]]],
    ) -> list[dict[str, object]]:
        used_rows: set[str] = set()
        results = []

        for bundle in bundles:
            candidates = self._candidate_rows(bundle, pipeline)
            primary = str(bundle.get("primary_signal_id") or "")

            exact = [
                item
                for item in candidates
                if primary
                and str(item[1].get("signal_id") or "") == primary
                and _row_identity(item[0], item[1]) not in used_rows
            ]
            available = [
                item
                for item in candidates
                if _row_identity(item[0], item[1]) not in used_rows
            ]

            if exact:
                source, best, _ = min(exact, key=lambda item: item[2])
                method = "EXACT_SIGNAL_ID"
            elif len(available) == 1:
                source, best, _ = available[0]
                method = "DIRECTION_AND_WINDOW"
            elif len(available) > 1:
                available.sort(key=lambda item: item[2])
                source, best, _ = available[0]
                closest_delta = available[0][2]
                tied = [
                    item for item in available
                    if item[2] == closest_delta
                ]
                method = (
                    "AMBIGUOUS_MATCH"
                    if len(tied) > 1
                    else "DIRECTION_AND_WINDOW"
                )
            else:
                source, best, method = None, {}, "NO_MATCH"

            if best:
                used_rows.add(_row_identity(source, best))

            results.append(
                {
                    "bundle_id": bundle.get("bundle_id"),
                    "detected_at": bundle.get("detected_at"),
                    "fresh_until": bundle.get("fresh_until"),
                    "direction": bundle.get("direction"),
                    "primary_setup_type": bundle.get(
                        "primary_setup_type"
                    ),
                    "primary_signal_id": primary,
                    "match_method": method,
                    "match_confidence": MATCH_CONFIDENCE[method],
                    "matched_source": source,
                    "pipeline_signal_id": (
                        str(best.get("signal_id") or "") or None
                    ),
                    "candidate_symbol": best.get("candidate_symbol"),
                    "matched_event_time": (
                        str(_event_time(best))
                        if best and _event_time(best) is not None
                        else None
                    ),
                    "candidate_count_before_assignment": len(candidates),
                    "pipeline_row_reused": False,
                    "source_read_only": True,
                    "execution_allowed": False,
                }
            )

        return results
