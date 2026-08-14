from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Mapping
import json

import pandas as pd


MATCH_CONFIDENCE = {
    "EXACT_SIGNAL_ID": 1.00,
    "SIGNAL_AND_SYMBOL": 0.98,
    "DIRECTION_AND_WINDOW": 0.75,
    "NEAREST_TIME": 0.55,
    "NO_MATCH": 0.00,
}


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


def resolve_range_preset(
    preset: str,
    anchor: date,
) -> tuple[date, date]:
    key = preset.upper().strip()
    if key == "SINGLE DAY":
        return anchor, anchor
    if key == "PREVIOUS 5 TRADING DAYS":
        return _previous_trading_days(anchor, 5)
    if key == "PREVIOUS 10 TRADING DAYS":
        return _previous_trading_days(anchor, 10)
    if key == "PREVIOUS MONTH":
        first_this_month = anchor.replace(day=1)
        previous_end = first_this_month - timedelta(days=1)
        return previous_end.replace(day=1), previous_end
    if key == "PREVIOUS 3 MONTHS":
        end = anchor
        start = anchor - timedelta(days=89)
        return start, end
    return anchor, anchor


def _previous_trading_days(
    anchor: date,
    count: int,
) -> tuple[date, date]:
    days: list[date] = []
    cursor = anchor
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return min(days), max(days)


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value)
    except Exception:
        return None


def _event_time(row: Mapping[str, object]) -> pd.Timestamp | None:
    for field in (
        "evaluated_at",
        "created_at",
        "updated_at",
        "executed_at",
        "entry_timestamp",
        "exit_timestamp",
        "confirmation_timestamp",
        "detected_at",
    ):
        ts = _timestamp(row.get(field))
        if ts is not None:
            return ts
    return None


def _day_text(value: object) -> str:
    ts = _timestamp(value)
    return ts.date().isoformat() if ts is not None else ""


def _inside_time_window(
    row: Mapping[str, object],
    start_time: time,
    end_time: time,
) -> bool:
    ts = _event_time(row)
    if ts is None:
        return False
    return start_time <= ts.time().replace(tzinfo=None) <= end_time


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
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


class RangeHistoricalAttributionAudit:
    """Read-only range audit and historical pipeline matching.

    This service never inserts queue items, creates paper orders, or invokes
    automation/execution services.
    """

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
        rows: list[dict[str, object]] = []
        for path in sorted(folder.glob("*.jsonl")) if folder.exists() else []:
            for row in _read_jsonl(path):
                detected = _timestamp(row.get("detected_at"))
                if detected is None:
                    continue
                if not (request.date_from <= detected.date() <= request.date_to):
                    continue
                if not (
                    request.start_time
                    <= detected.time().replace(tzinfo=None)
                    <= request.end_time
                ):
                    continue
                if (
                    request.direction != "ALL"
                    and str(row.get("direction") or "").upper()
                    != request.direction
                ):
                    continue
                if (
                    request.setup_type != "ALL"
                    and str(row.get("primary_setup_type") or "")
                    != request.setup_type
                ):
                    continue
                rows.append(dict(row))
        rows.sort(key=lambda row: str(row.get("detected_at") or ""))
        return rows

    def _load_pipeline_range(
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

        selection: list[dict[str, object]] = []
        committee: list[dict[str, object]] = []
        queue: list[dict[str, object]] = []
        current = request.date_from
        while current <= request.date_to:
            day_text = current.isoformat()
            selection.extend(
                _safe_read(
                    self.database,
                    "read_trade_selection_evaluations",
                    trading_date=day_text,
                    limit=5000,
                )
            )
            committee.extend(
                _safe_read(
                    self.database,
                    "read_institutional_execution_evaluations",
                    trading_date=day_text,
                    limit=5000,
                )
            )
            queue.extend(
                _safe_read(
                    self.database,
                    "read_execution_queue",
                    trading_date=day_text,
                    limit=5000,
                )
            )
            current += timedelta(days=1)

        opportunities = _safe_read(
            self.database,
            "read_opportunity_evaluations",
            limit=50000,
        )
        orders = _safe_read(
            self.database,
            "read_paper_execution_orders",
            "PAPER-STD",
        )

        raw = {
            "signals": signals,
            "selection": selection,
            "opportunity": opportunities,
            "committee": committee,
            "queue": queue,
            "orders": orders,
        }
        output: dict[str, list[dict[str, object]]] = {}
        for name, rows in raw.items():
            output[name] = [
                row for row in rows
                if request.date_from
                <= (_event_time(row).date() if _event_time(row) is not None
                    else date.min)
                <= request.date_to
                and _inside_time_window(
                    row,
                    request.start_time,
                    request.end_time,
                )
            ]
        return output

    def audit(
        self,
        request: HistoricalAuditRequest,
    ) -> dict[str, object]:
        bundles = self.load_bundles(request)
        pipeline = self._load_pipeline_range(request)
        source_rows = [
            {
                "source": "v4.3 setup bundles",
                "available": bool(bundles),
                "matching_rows": len(bundles),
                "read_only": True,
            }
        ]
        for name, rows in pipeline.items():
            source_rows.append(
                {
                    "source": name,
                    "available": bool(rows),
                    "matching_rows": len(rows),
                    "read_only": True,
                }
            )

        matches = [
            self._match_bundle(bundle, pipeline)
            for bundle in bundles
        ]
        summary = {
            "date_from": request.date_from.isoformat(),
            "date_to": request.date_to.isoformat(),
            "calendar_days": (
                request.date_to - request.date_from
            ).days + 1,
            "bundles": len(bundles),
            "exact_matches": sum(
                row["match_method"] in {
                    "EXACT_SIGNAL_ID",
                    "SIGNAL_AND_SYMBOL",
                }
                for row in matches
            ),
            "inferred_matches": sum(
                row["match_method"] in {
                    "DIRECTION_AND_WINDOW",
                    "NEAREST_TIME",
                }
                for row in matches
            ),
            "no_matches": sum(
                row["match_method"] == "NO_MATCH"
                for row in matches
            ),
            "source_read_only": True,
            "execution_allowed": False,
        }
        return {
            "summary": summary,
            "sources": source_rows,
            "matches": matches,
            "bundles": bundles,
        }

    def _candidate_rows(
        self,
        bundle: Mapping[str, object],
        rows: Iterable[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        detected = _timestamp(bundle.get("detected_at"))
        fresh = _timestamp(bundle.get("fresh_until"))
        if detected is None:
            return []
        upper = (
            fresh + pd.Timedelta(minutes=self.grace_minutes)
            if fresh is not None
            else detected + pd.Timedelta(minutes=60)
        )
        direction = str(bundle.get("direction") or "").upper()
        result = []
        for row in rows:
            event = _event_time(row)
            if event is None or not (detected <= event <= upper):
                continue
            row_direction = str(row.get("direction") or "").upper()
            if direction and row_direction and direction != row_direction:
                continue
            result.append(dict(row))
        return result

    def _match_bundle(
        self,
        bundle: Mapping[str, object],
        pipeline: Mapping[str, list[dict[str, object]]],
    ) -> dict[str, object]:
        detected = _timestamp(bundle.get("detected_at"))
        all_rows: list[tuple[str, dict[str, object]]] = []
        for source, rows in pipeline.items():
            all_rows.extend(
                (source, row)
                for row in self._candidate_rows(bundle, rows)
            )

        primary_signal = str(
            bundle.get("primary_signal_id") or ""
        )
        exact = [
            (source, row)
            for source, row in all_rows
            if primary_signal
            and str(row.get("signal_id") or "") == primary_signal
        ]

        if exact:
            source, best = min(
                exact,
                key=lambda pair: abs(
                    (
                        (_event_time(pair[1]) or detected) - detected
                    ).total_seconds()
                ) if detected is not None else 0,
            )
            method = "EXACT_SIGNAL_ID"
        elif all_rows:
            source, best = min(
                all_rows,
                key=lambda pair: abs(
                    (
                        (_event_time(pair[1]) or detected) - detected
                    ).total_seconds()
                ) if detected is not None else 0,
            )
            method = "DIRECTION_AND_WINDOW"
        else:
            source, best, method = None, {}, "NO_MATCH"

        linked_signal_id = str(best.get("signal_id") or "") or None
        candidate_symbol = best.get("candidate_symbol")
        return {
            "bundle_id": bundle.get("bundle_id"),
            "detected_at": bundle.get("detected_at"),
            "fresh_until": bundle.get("fresh_until"),
            "direction": bundle.get("direction"),
            "primary_setup_type": bundle.get("primary_setup_type"),
            "primary_signal_id": primary_signal,
            "match_method": method,
            "match_confidence": MATCH_CONFIDENCE[method],
            "matched_source": source,
            "pipeline_signal_id": linked_signal_id,
            "candidate_symbol": candidate_symbol,
            "matched_event_time": (
                str(_event_time(best))
                if best and _event_time(best) is not None
                else None
            ),
            "source_read_only": True,
            "execution_allowed": False,
        }
