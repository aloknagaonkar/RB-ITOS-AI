from __future__ import annotations

from datetime import datetime
from hashlib import sha1
import sqlite3
from typing import Mapping


SNAPSHOT_TYPES = frozenset({"ENTRY", "ACTIVE", "EXIT"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS option_telemetry_lifecycle (
    lifecycle_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    snapshot_type TEXT NOT NULL,
    observed_timestamp TEXT NOT NULL,
    source_timestamp TEXT,
    snapshot_source TEXT NOT NULL,
    pcr_oi REAL,
    delta REAL,
    call_oi_at_strike REAL,
    put_oi_at_strike REAL,
    iv REAL,
    best_bid REAL,
    best_ask REAL,
    spread_pct REAL,
    data_quality TEXT NOT NULL DEFAULT 'VALID',
    reason_code TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(order_id, snapshot_type, observed_timestamp)
);
CREATE INDEX IF NOT EXISTS idx_option_telemetry_lifecycle_lookup
ON option_telemetry_lifecycle(order_id, snapshot_type, observed_timestamp);
"""


def _database_path(database) -> str | None:
    value = getattr(database, "path", None)
    return str(value) if value else None


def initialize_option_telemetry_lifecycle(database) -> bool:
    path = _database_path(database)
    if not path:
        return False
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()
    return True


def record_option_telemetry_snapshot(
    database,
    *,
    order_id: str,
    snapshot_type: str,
    telemetry: Mapping[str, object] | None,
    observed_timestamp: str | None = None,
    snapshot_source: str = "PERSISTED_TELEMETRY",
    data_quality: str = "VALID",
    reason_code: str | None = None,
) -> bool:
    """Persist one observational lifecycle snapshot without affecting execution."""
    path = _database_path(database)
    kind = str(snapshot_type or "").upper()
    if not path or not order_id or kind not in SNAPSHOT_TYPES:
        return False
    initialize_option_telemetry_lifecycle(database)
    row = dict(telemetry or {})
    timestamp = str(
        observed_timestamp
        or row.get("observed_timestamp")
        or datetime.now().astimezone().isoformat()
    )
    raw = f"{order_id}|{kind}|{timestamp}|{snapshot_source}"
    lifecycle_id = "OTL-" + sha1(raw.encode("utf-8")).hexdigest()[:20].upper()
    created_at = datetime.now().astimezone().isoformat()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO option_telemetry_lifecycle (
                lifecycle_id, order_id, snapshot_type, observed_timestamp,
                source_timestamp, snapshot_source, pcr_oi, delta,
                call_oi_at_strike, put_oi_at_strike, iv, best_bid, best_ask,
                spread_pct, data_quality, reason_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lifecycle_id,
                order_id,
                kind,
                timestamp,
                row.get("observed_timestamp"),
                snapshot_source,
                row.get("pcr_oi"),
                row.get("delta"),
                row.get("call_oi_at_strike"),
                row.get("put_oi_at_strike"),
                row.get("iv"),
                row.get("best_bid"),
                row.get("best_ask"),
                row.get("spread_pct"),
                data_quality,
                reason_code,
                created_at,
            ),
        )
        conn.commit()
    return True


def record_active_telemetry_snapshot(database, order_id: str, telemetry: Mapping[str, object] | None) -> bool:
    """Store the first valid snapshot as ENTRY and later snapshots as ACTIVE."""
    if not telemetry:
        return False
    path = _database_path(database)
    if not path:
        return False
    initialize_option_telemetry_lifecycle(database)
    with sqlite3.connect(path) as conn:
        existing = conn.execute(
            "SELECT 1 FROM option_telemetry_lifecycle WHERE order_id=? AND snapshot_type='ENTRY' LIMIT 1",
            (order_id,),
        ).fetchone()
    kind = "ACTIVE" if existing else "ENTRY"
    return record_option_telemetry_snapshot(
        database,
        order_id=order_id,
        snapshot_type=kind,
        telemetry=telemetry,
        snapshot_source="ACTIVE_CAPTURE",
    )


def record_exit_telemetry_fallback(database, order_id: str, telemetry: Mapping[str, object] | None) -> bool:
    """Persist a non-blocking EXIT snapshot from the latest active telemetry."""
    quality = "FALLBACK" if telemetry else "UNAVAILABLE"
    reason = "LAST_ACTIVE_FALLBACK" if telemetry else "EXIT_SNAPSHOT_NOT_CAPTURED"
    return record_option_telemetry_snapshot(
        database,
        order_id=order_id,
        snapshot_type="EXIT",
        telemetry=telemetry,
        snapshot_source=reason,
        data_quality=quality,
        reason_code=reason,
    )


def read_option_telemetry_lifecycle(database, order_id: str) -> dict[str, dict[str, object] | None]:
    path = _database_path(database)
    empty = {"entry": None, "latest": None, "exit": None}
    if not path or not order_id:
        return empty
    initialize_option_telemetry_lifecycle(database)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM option_telemetry_lifecycle
            WHERE order_id=?
            ORDER BY observed_timestamp ASC
            """,
            (order_id,),
        ).fetchall()
    items = [dict(row) for row in rows]
    entry = next((row for row in items if row["snapshot_type"] == "ENTRY"), None)
    active = [row for row in items if row["snapshot_type"] == "ACTIVE"]
    exit_rows = [row for row in items if row["snapshot_type"] == "EXIT"]
    return {
        "entry": entry,
        "latest": active[-1] if active else entry,
        "exit": exit_rows[-1] if exit_rows else None,
    }


__all__ = [
    "initialize_option_telemetry_lifecycle",
    "read_option_telemetry_lifecycle",
    "record_active_telemetry_snapshot",
    "record_exit_telemetry_fallback",
    "record_option_telemetry_snapshot",
]
