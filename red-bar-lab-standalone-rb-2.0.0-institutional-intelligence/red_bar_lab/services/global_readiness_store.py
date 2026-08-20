from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


_SCHEMA = """
CREATE TABLE IF NOT EXISTS global_market_readiness_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    underlying_name TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    overall_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    underlying_status TEXT NOT NULL,
    option_chain_status TEXT NOT NULL,
    option_quote_status TEXT NOT NULL,
    pcr_status TEXT NOT NULL,
    futures_status TEXT NOT NULL,
    futures_strength TEXT NOT NULL,
    v2_alignment_status TEXT NOT NULL,
    execution_source_status TEXT NOT NULL,
    market_hours_status TEXT NOT NULL,
    blocking_reasons_json TEXT NOT NULL DEFAULT '[]',
    advisory_reasons_json TEXT NOT NULL DEFAULT '[]',
    execution_reasons_json TEXT NOT NULL DEFAULT '[]',
    signals_seen INTEGER NOT NULL DEFAULT 0,
    signals_scored INTEGER NOT NULL DEFAULT 0,
    orders_opened INTEGER NOT NULL DEFAULT 0,
    orders_skipped INTEGER NOT NULL DEFAULT 0,
    trade_outcome TEXT,
    authority TEXT NOT NULL DEFAULT 'OBSERVATIONAL_ONLY',
    payload_json TEXT NOT NULL,
    UNIQUE(underlying_name, instrument_key, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_global_readiness_time
ON global_market_readiness_snapshots(underlying_name, julianday(observed_at) DESC);
"""


def _payload(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {key: getattr(value, key) for key in dir(value) if not key.startswith('_') and not callable(getattr(value, key, None))}


def _normalize_timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        return text


def persist_global_readiness_snapshot(
    database_path: str | Path,
    *,
    observed_at: datetime | str,
    underlying_name: str,
    instrument_key: str,
    readiness,
    signals_seen: int = 0,
    signals_scored: int = 0,
    orders_opened: int = 0,
    orders_skipped: int = 0,
    trade_outcome: str | None = None,
) -> int:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    observed = _normalize_timestamp(observed_at)
    data = _payload(readiness)
    payload = {
        "readiness": data,
        "signals_seen": int(signals_seen),
        "signals_scored": int(signals_scored),
        "orders_opened": int(orders_opened),
        "orders_skipped": int(orders_skipped),
        "trade_outcome": trade_outcome,
    }
    values = (
        observed, str(underlying_name), str(instrument_key),
        str(data.get("status") or "UNAVAILABLE"), str(data.get("reason") or ""),
        str(data.get("underlying_status") or "UNAVAILABLE"),
        str(data.get("option_chain_status") or "UNAVAILABLE"),
        str(data.get("option_quote_status") or "UNAVAILABLE"),
        str(data.get("pcr_status") or "UNAVAILABLE"),
        str(data.get("futures_status") or "NOT_APPLICABLE"),
        str(data.get("futures_strength") or "NOT_APPLICABLE"),
        str(data.get("v2_alignment_status") or "UNAVAILABLE"),
        str(data.get("execution_source_status") or "UNAVAILABLE"),
        str(data.get("market_hours_status") or "UNAVAILABLE"),
        json.dumps(list(data.get("blocking_reasons") or ())),
        json.dumps(list(data.get("advisory_reasons") or ())),
        json.dumps(list(data.get("execution_reasons") or ())),
        int(signals_seen), int(signals_scored), int(orders_opened), int(orders_skipped),
        trade_outcome, "OBSERVATIONAL_ONLY", json.dumps(payload, default=str, sort_keys=True),
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA)
        cursor = connection.execute(
            """
            INSERT INTO global_market_readiness_snapshots (
                observed_at,underlying_name,instrument_key,overall_status,reason,
                underlying_status,option_chain_status,option_quote_status,pcr_status,
                futures_status,futures_strength,v2_alignment_status,
                execution_source_status,market_hours_status,blocking_reasons_json,
                advisory_reasons_json,execution_reasons_json,signals_seen,signals_scored,
                orders_opened,orders_skipped,trade_outcome,authority,payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(underlying_name,instrument_key,observed_at) DO UPDATE SET
                overall_status=excluded.overall_status,
                reason=excluded.reason,
                blocking_reasons_json=excluded.blocking_reasons_json,
                advisory_reasons_json=excluded.advisory_reasons_json,
                execution_reasons_json=excluded.execution_reasons_json,
                signals_seen=excluded.signals_seen,
                signals_scored=excluded.signals_scored,
                orders_opened=excluded.orders_opened,
                orders_skipped=excluded.orders_skipped,
                trade_outcome=excluded.trade_outcome,
                payload_json=excluded.payload_json,
                authority='OBSERVATIONAL_ONLY'
            """,
            values,
        )
        connection.commit()
        return int(cursor.lastrowid or 0)


def read_global_readiness_snapshots(
    database_path: str | Path,
    *,
    underlying_name: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    path = Path(database_path)
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(_SCHEMA)
        if underlying_name:
            rows = connection.execute(
                "SELECT * FROM global_market_readiness_snapshots WHERE underlying_name=? ORDER BY julianday(observed_at) DESC, observed_at DESC LIMIT ?",
                (underlying_name, max(1, int(limit))),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM global_market_readiness_snapshots ORDER BY julianday(observed_at) DESC, observed_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["blocking_reasons"] = json.loads(item.pop("blocking_reasons_json") or "[]")
        item["advisory_reasons"] = json.loads(item.pop("advisory_reasons_json") or "[]")
        item["execution_reasons"] = json.loads(item.pop("execution_reasons_json") or "[]")
        result.append(item)
    return result
