from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


_SCHEMA = """
CREATE TABLE IF NOT EXISTS red_bar_v2_cycle_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    underlying_name TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    cycle_status TEXT NOT NULL,
    cycle_reason TEXT NOT NULL DEFAULT '',
    context_status TEXT NOT NULL DEFAULT 'UNAVAILABLE',
    context_reason TEXT NOT NULL DEFAULT '',
    aligned_rows INTEGER NOT NULL DEFAULT 0,
    alignment_coverage_pct REAL,
    index_rows INTEGER NOT NULL DEFAULT 0,
    futures_rows INTEGER NOT NULL DEFAULT 0,
    index_timestamp TEXT,
    futures_timestamp TEXT,
    last_aligned_timestamp TEXT,
    index_close REAL,
    index_rsi REAL,
    futures_close REAL,
    futures_vwap REAL,
    price_vs_vwap TEXT,
    reference_midpoint REAL,
    candidate_events_scanned INTEGER NOT NULL DEFAULT 0,
    admitted_candidates INTEGER NOT NULL DEFAULT 0,
    admission_direction TEXT,
    admission_code TEXT,
    admission_reason TEXT,
    bridge_status TEXT NOT NULL DEFAULT 'UNAVAILABLE',
    bridge_reason TEXT NOT NULL DEFAULT '',
    readiness_status TEXT NOT NULL DEFAULT 'UNAVAILABLE',
    readiness_reason TEXT NOT NULL DEFAULT '',
    blocking_reasons_json TEXT NOT NULL DEFAULT '[]',
    advisory_reasons_json TEXT NOT NULL DEFAULT '[]',
    execution_reasons_json TEXT NOT NULL DEFAULT '[]',
    signals_seen INTEGER NOT NULL DEFAULT 0,
    candidates_scored INTEGER NOT NULL DEFAULT 0,
    orders_opened INTEGER NOT NULL DEFAULT 0,
    orders_skipped INTEGER NOT NULL DEFAULT 0,
    cycle_timings_json TEXT NOT NULL DEFAULT '{}',
    candle_evidence_json TEXT NOT NULL DEFAULT '[]',
    authority TEXT NOT NULL DEFAULT 'OBSERVATIONAL_ONLY',
    payload_json TEXT NOT NULL,
    UNIQUE(run_id)
);
CREATE INDEX IF NOT EXISTS idx_v2_cycle_evaluations_time
ON red_bar_v2_cycle_evaluations(trading_date, julianday(observed_at) DESC);
"""


def _normalize_timestamp(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        return text


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result


def _price_vs_vwap(futures_close: float | None, futures_vwap: float | None) -> str | None:
    if futures_close is None or futures_vwap is None:
        return None
    if futures_close > futures_vwap:
        return "ABOVE"
    if futures_close < futures_vwap:
        return "BELOW"
    return "AT"


def _evidence_rows(value: object) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in value or ():
        if is_dataclass(item):
            rows.append(asdict(item))
        elif isinstance(item, Mapping):
            rows.append(dict(item))
    return rows


def persist_red_bar_v2_cycle_evaluation(
    database_path: str | Path,
    *,
    run_id: str,
    observed_at: datetime | str,
    trading_date: str,
    underlying_name: str,
    instrument_key: str,
    live_v2: Any = None,
    snapshot: Any = None,
    bridge: Any = None,
    readiness: Any = None,
    report: Any = None,
    cycle_timings_ms: Mapping[str, float] | None = None,
) -> int:
    """Persist one observational journal row for a paper-monitor cycle.

    The row captures what the Red Bar V2 evaluation saw and decided during
    the cycle (context health, gate values, candidates, publication and
    readiness outcomes) so zero-signal sessions remain explainable. Nothing
    here is consumed by the automation or gate path.
    """
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    observed = _normalize_timestamp(observed_at) or ""

    cycle_status = str(getattr(live_v2, "status", None) or "UNAVAILABLE").upper()
    cycle_reason = str(getattr(live_v2, "reason", "") or "")
    health = getattr(live_v2, "session_health", None)
    health = health if isinstance(health, Mapping) else {}
    admission = getattr(live_v2, "latest_admission", None)
    admission = admission if isinstance(admission, Mapping) else {}

    index_close = _float_or_none(getattr(snapshot, "index_close", None))
    index_rsi = _float_or_none(getattr(snapshot, "index_rsi", None))
    futures_close = _float_or_none(getattr(snapshot, "futures_close", None))
    futures_vwap = _float_or_none(getattr(snapshot, "futures_vwap", None))
    reference_midpoint = _float_or_none(
        getattr(snapshot, "reference_midpoint", None)
    )

    blocking = list(getattr(readiness, "blocking_reasons", ()) or ())
    advisory = list(getattr(readiness, "advisory_reasons", ()) or ())
    execution = list(getattr(readiness, "execution_reasons", ()) or ())

    timings = dict(cycle_timings_ms or {})
    candle_evidence = _evidence_rows(getattr(live_v2, "market_data_evidence", ()))

    payload: dict[str, Any] = {
        "cycle": {"status": cycle_status, "reason": cycle_reason},
        "context": dict(health),
        "admission": dict(admission),
        "snapshot": {
            "index_close": index_close,
            "index_rsi": index_rsi,
            "futures_close": futures_close,
            "futures_vwap": futures_vwap,
            "reference_midpoint": reference_midpoint,
        },
        "bridge": {
            "status": str(getattr(bridge, "status", "") or ""),
            "reason": str(getattr(bridge, "reason", "") or ""),
        },
        "report": {
            "signals_seen": _int(getattr(report, "signals_seen", 0)),
            "candidates_scored": _int(getattr(report, "candidates_scored", 0)),
            "paper_orders_opened": _int(getattr(report, "paper_orders_opened", 0)),
            "skipped": _int(getattr(report, "skipped", 0)),
            "errors": len(list(getattr(report, "errors", ()) or ())),
        },
        "cycle_timings_ms": timings,
        "candle_evidence": candle_evidence,
    }

    values = (
        str(run_id),
        observed,
        str(trading_date),
        str(underlying_name),
        str(instrument_key),
        cycle_status,
        cycle_reason,
        str(health.get("status") or "UNAVAILABLE").upper(),
        str(health.get("reason") or ""),
        _int(health.get("aligned_rows")),
        _float_or_none(health.get("alignment_coverage_pct")),
        _int(health.get("index_rows")),
        _int(health.get("futures_rows")),
        _normalize_timestamp(health.get("index_timestamp")),
        _normalize_timestamp(health.get("futures_timestamp")),
        _normalize_timestamp(health.get("last_aligned_timestamp")),
        index_close,
        index_rsi,
        futures_close,
        futures_vwap,
        _price_vs_vwap(futures_close, futures_vwap),
        reference_midpoint,
        _int(getattr(live_v2, "candidate_events_scanned", 0)),
        _int(getattr(live_v2, "admitted_candidates", 0)),
        str(admission.get("direction") or "") or None,
        str(admission.get("admission_code") or "") or None,
        str(admission.get("admission_reason") or "") or None,
        str(getattr(bridge, "status", "") or "UNAVAILABLE").upper(),
        str(getattr(bridge, "reason", "") or ""),
        str(getattr(readiness, "status", "") or "UNAVAILABLE").upper(),
        str(getattr(readiness, "reason", "") or ""),
        json.dumps(blocking),
        json.dumps(advisory),
        json.dumps(execution),
        _int(getattr(report, "signals_seen", 0)),
        _int(getattr(report, "candidates_scored", 0)),
        _int(getattr(report, "paper_orders_opened", 0)),
        _int(getattr(report, "skipped", 0)),
        json.dumps(timings, default=str, sort_keys=True),
        json.dumps(candle_evidence, default=str, sort_keys=True),
        "OBSERVATIONAL_ONLY",
        json.dumps(payload, default=str, sort_keys=True),
    )

    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA)
        cursor = connection.execute(
            """
            INSERT INTO red_bar_v2_cycle_evaluations (
                run_id,observed_at,trading_date,underlying_name,instrument_key,
                cycle_status,cycle_reason,context_status,context_reason,
                aligned_rows,alignment_coverage_pct,index_rows,futures_rows,
                index_timestamp,futures_timestamp,last_aligned_timestamp,
                index_close,index_rsi,futures_close,futures_vwap,price_vs_vwap,
                reference_midpoint,candidate_events_scanned,admitted_candidates,
                admission_direction,admission_code,admission_reason,
                bridge_status,bridge_reason,readiness_status,readiness_reason,
                blocking_reasons_json,advisory_reasons_json,execution_reasons_json,
                signals_seen,candidates_scored,orders_opened,orders_skipped,
                cycle_timings_json,candle_evidence_json,authority,payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
                observed_at=excluded.observed_at,
                cycle_status=excluded.cycle_status,
                cycle_reason=excluded.cycle_reason,
                context_status=excluded.context_status,
                context_reason=excluded.context_reason,
                bridge_status=excluded.bridge_status,
                bridge_reason=excluded.bridge_reason,
                readiness_status=excluded.readiness_status,
                readiness_reason=excluded.readiness_reason,
                blocking_reasons_json=excluded.blocking_reasons_json,
                advisory_reasons_json=excluded.advisory_reasons_json,
                execution_reasons_json=excluded.execution_reasons_json,
                payload_json=excluded.payload_json,
                authority='OBSERVATIONAL_ONLY'
            """,
            values,
        )
        connection.commit()
        return int(cursor.lastrowid or 0)


def read_red_bar_v2_cycle_evaluations(
    database_path: str | Path,
    *,
    trading_date: str | None = None,
    underlying_name: str | None = None,
    limit: int = 400,
) -> list[dict[str, Any]]:
    """Read cycle journal rows without creating tables or indexes."""
    path = Path(database_path)
    if not path.exists():
        return []
    clauses: list[str] = []
    params: list[Any] = []
    if trading_date:
        clauses.append("trading_date=?")
        params.append(str(trading_date))
    if underlying_name:
        clauses.append("underlying_name=?")
        params.append(str(underlying_name))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    try:
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM red_bar_v2_cycle_evaluations "
                f"{where} "
                "ORDER BY julianday(observed_at) DESC, observed_at DESC LIMIT ?",
                (*params, max(1, int(limit))),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise
    result = []
    for row in rows:
        item = dict(row)
        item["blocking_reasons"] = json.loads(
            item.pop("blocking_reasons_json") or "[]"
        )
        item["advisory_reasons"] = json.loads(
            item.pop("advisory_reasons_json") or "[]"
        )
        item["execution_reasons"] = json.loads(
            item.pop("execution_reasons_json") or "[]"
        )
        try:
            item["cycle_timings"] = json.loads(item.pop("cycle_timings_json") or "{}")
        except json.JSONDecodeError:
            item["cycle_timings"] = {}
            item.pop("cycle_timings_json", None)
        try:
            item["candle_evidence"] = json.loads(
                item.pop("candle_evidence_json") or "[]"
            )
        except json.JSONDecodeError:
            item["candle_evidence"] = []
            item.pop("candle_evidence_json", None)
        result.append(item)
    return result
