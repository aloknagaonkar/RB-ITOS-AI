from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
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
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value)
    except Exception:
        return None


def _event_time(row: Mapping[str, object]) -> pd.Timestamp | None:
    for field in (
        "evaluated_at", "created_at", "updated_at", "executed_at",
        "entry_timestamp", "exit_timestamp",
        "confirmation_timestamp", "detected_at",
    ):
        ts = _timestamp(row.get(field))
        if ts is not None:
            return ts
    trading_date = row.get("trading_date")
    if trading_date:
        return _timestamp(trading_date)
    return None


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
        "instrument_key", "underlying_key", "underlying_instrument_key",
        "index_instrument_key",
    )
    present = [str(row.get(f) or "") for f in fields if row.get(f)]
    if not present:
        return True
    return instrument_key in present


class RangeHistoricalAttributionAudit:
    def __init__(self, *, database, runs_root: str | Path, grace_minutes: int = 45):
        self.database = database
        self.runs_root = Path(runs_root)
        self.grace_minutes = int(grace_minutes)

    def load_bundles(self, request: HistoricalAuditRequest) -> list[dict[str, object]]:
        request.validate()
        folder = self.runs_root / "fresh_setup_bundles_v43"
        rows = []
        for path in sorted(folder.glob("*.jsonl")) if folder.exists() else []:
            for row in _read_jsonl(path):
                ts = _timestamp(row.get("detected_at"))
                if ts is None:
                    continue
                if not request.date_from <= ts.date() <= request.date_to:
                    continue
                if not request.start_time <= ts.time().replace(tzinfo=None) <= request.end_time:
                    continue
                if request.direction != "ALL" and _direction(row) != request.direction:
                    continue
                if request.setup_type != "ALL" and str(row.get("primary_setup_type") or "") != request.setup_type:
                    continue
                rows.append(dict(row))
        rows.sort(key=lambda row: str(row.get("detected_at") or ""))
        return rows

    def _raw_pipeline(self, request: HistoricalAuditRequest) -> dict[str, list[dict[str, object]]]:
        signals = _safe_read(
            self.database, "read_signal_attempts_range",
            request.instrument_key,
            request.date_from.isoformat(),
            request.date_to.isoformat(),
        )
        selection, committee, queue = [], [], []
        current = request.date_from
        while current <= request.date_to:
            day = current.isoformat()
            selection.extend(_safe_read(
                self.database, "read_trade_selection_evaluations",
                trading_date=day, limit=5000,
            ))
            committee.extend(_safe_read(
                self.database, "read_institutional_execution_evaluations",
                trading_date=day, limit=5000,
            ))
            queue.extend(_safe_read(
                self.database, "read_execution_queue",
                trading_date=day, limit=5000,
            ))
            current += timedelta(days=1)
        return {
            "signals": signals,
            "selection": selection,
            "opportunity": _safe_read(
                self.database, "read_opportunity_evaluations", limit=50000
            ),
            "committee": committee,
            "queue": queue,
            "orders": _safe_read(
                self.database, "read_paper_execution_orders", "PAPER-STD"
            ),
        }

    def _filter_source(
        self,
        rows: list[dict[str, object]],
        request: HistoricalAuditRequest,
    ) -> tuple[list[dict[str, object]], dict[str, int]]:
        raw = list(rows)
        date_rows = [
            row for row in raw
            if (ts := _event_time(row)) is not None
            and request.date_from <= ts.date() <= request.date_to
        ]
        session_rows = [
            row for row in date_rows
            if request.start_time
            <= _event_time(row).time().replace(tzinfo=None)
            <= request.end_time
        ]
        instrument_rows = [
            row for row in session_rows
            if _instrument_matches(row, request.instrument_key)
        ]
        direction_rows = [
            row for row in instrument_rows
            if request.direction == "ALL"
            or not _direction(row)
            or _direction(row) == request.direction
        ]
        return direction_rows, {
            "raw_rows": len(raw),
            "date_filtered": len(date_rows),
            "session_filtered": len(session_rows),
            "instrument_filtered": len(instrument_rows),
            "direction_filtered": len(direction_rows),
            "matching_rows": len(direction_rows),
        }

    def audit(self, request: HistoricalAuditRequest) -> dict[str, object]:
        bundles = self.load_bundles(request)
        raw = self._raw_pipeline(request)
        pipeline = {}
        source_rows = [{
            "source": "v4.3 setup bundles",
            "raw_rows": len(bundles),
            "date_filtered": len(bundles),
            "session_filtered": len(bundles),
            "instrument_filtered": len(bundles),
            "direction_filtered": len(bundles),
            "matching_rows": len(bundles),
            "available": bool(bundles),
            "read_only": True,
        }]
        for name, rows in raw.items():
            filtered, counts = self._filter_source(rows, request)
            pipeline[name] = filtered
            source_rows.append({
                "source": name,
                **counts,
                "available": bool(filtered),
                "read_only": True,
            })

        matches = [self._match_bundle(bundle, pipeline) for bundle in bundles]
        return {
            "summary": {
                "date_from": request.date_from.isoformat(),
                "date_to": request.date_to.isoformat(),
                "calendar_days": (request.date_to - request.date_from).days + 1,
                "bundles": len(bundles),
                "exact_matches": sum(r["match_method"] == "EXACT_SIGNAL_ID" for r in matches),
                "inferred_matches": sum(r["match_method"] == "DIRECTION_AND_WINDOW" for r in matches),
                "no_matches": sum(r["match_method"] == "NO_MATCH" for r in matches),
                "source_read_only": True,
                "execution_allowed": False,
            },
            "sources": source_rows,
            "matches": matches,
            "bundles": bundles,
        }

    def _candidate_rows(self, bundle, rows):
        detected = _timestamp(bundle.get("detected_at"))
        fresh = _timestamp(bundle.get("fresh_until"))
        if detected is None:
            return []
        upper = (fresh if fresh is not None else detected) + pd.Timedelta(minutes=self.grace_minutes)
        direction = _direction(bundle)
        result = []
        for row in rows:
            ts = _event_time(row)
            if ts is None or not detected <= ts <= upper:
                continue
            row_direction = _direction(row)
            if direction and row_direction and direction != row_direction:
                continue
            result.append(dict(row))
        return result

    def _match_bundle(self, bundle, pipeline):
        detected = _timestamp(bundle.get("detected_at"))
        all_rows = []
        for source, rows in pipeline.items():
            all_rows.extend((source, row) for row in self._candidate_rows(bundle, rows))
        primary = str(bundle.get("primary_signal_id") or "")
        exact = [
            pair for pair in all_rows
            if primary and str(pair[1].get("signal_id") or "") == primary
        ]
        if exact:
            source, best = min(
                exact,
                key=lambda pair: abs(((_event_time(pair[1]) or detected) - detected).total_seconds()),
            )
            method = "EXACT_SIGNAL_ID"
        elif all_rows:
            source, best = min(
                all_rows,
                key=lambda pair: abs(((_event_time(pair[1]) or detected) - detected).total_seconds()),
            )
            method = "DIRECTION_AND_WINDOW"
        else:
            source, best, method = None, {}, "NO_MATCH"
        return {
            "bundle_id": bundle.get("bundle_id"),
            "detected_at": bundle.get("detected_at"),
            "fresh_until": bundle.get("fresh_until"),
            "direction": bundle.get("direction"),
            "primary_setup_type": bundle.get("primary_setup_type"),
            "primary_signal_id": primary,
            "match_method": method,
            "match_confidence": MATCH_CONFIDENCE[method],
            "matched_source": source,
            "pipeline_signal_id": str(best.get("signal_id") or "") or None,
            "candidate_symbol": best.get("candidate_symbol"),
            "matched_event_time": str(_event_time(best)) if best and _event_time(best) is not None else None,
            "source_read_only": True,
            "execution_allowed": False,
        }
