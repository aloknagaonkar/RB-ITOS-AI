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
    option_vwap REAL,
    option_rsi14 REAL,
    indicator_source TEXT,
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


def _number(value: object) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _first_depth_price(quote: Mapping[str, object], side: str) -> float | None:
    depth = quote.get("depth")
    if not isinstance(depth, Mapping):
        return None
    levels = depth.get(side)
    if not isinstance(levels, list) or not levels:
        return None
    first = levels[0]
    return _number(first.get("price")) if isinstance(first, Mapping) else None


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(option_telemetry_lifecycle)")}
    for name, declaration in (
        ("option_vwap", "REAL"),
        ("option_rsi14", "REAL"),
        ("indicator_source", "TEXT"),
    ):
        if name not in existing:
            conn.execute(f"ALTER TABLE option_telemetry_lifecycle ADD COLUMN {name} {declaration}")


def initialize_option_telemetry_lifecycle(database) -> bool:
    path = _database_path(database)
    if not path:
        return False
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA)
        _ensure_columns(conn)
        conn.commit()
    return True


def _rsi14(prices: list[float]) -> float | None:
    if len(prices) < 15:
        return None
    changes = [prices[index] - prices[index - 1] for index in range(1, len(prices))]
    gains = [max(change, 0.0) for change in changes[-14:]]
    losses = [max(-change, 0.0) for change in changes[-14:]]
    average_gain = sum(gains) / 14.0
    average_loss = sum(losses) / 14.0
    if average_loss == 0.0:
        return 100.0 if average_gain > 0.0 else 50.0
    rs = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + rs))


def derive_persisted_option_indicators(database, order_id: str) -> dict[str, object]:
    """Derive option VWAP and RSI-14 from persisted option telemetry only."""
    path = _database_path(database)
    if not path or not order_id:
        return {"option_vwap": None, "option_rsi14": None, "indicator_source": "NOT_AVAILABLE"}
    try:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT current_price, volume
                FROM option_execution_telemetry
                WHERE order_id=? AND current_price IS NOT NULL
                ORDER BY observed_timestamp ASC
                """,
                (order_id,),
            ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    prices = [float(row["current_price"]) for row in rows if row["current_price"] is not None]
    weighted_sum = 0.0
    weight_total = 0.0
    previous_volume: float | None = None
    for row in rows:
        if row["current_price"] is None or row["volume"] is None:
            continue
        price = float(row["current_price"])
        cumulative_volume = float(row["volume"])
        incremental = cumulative_volume if previous_volume is None else max(0.0, cumulative_volume - previous_volume)
        previous_volume = cumulative_volume
        if incremental > 0.0:
            weighted_sum += price * incremental
            weight_total += incremental
    return {
        "option_vwap": weighted_sum / weight_total if weight_total > 0.0 else None,
        "option_rsi14": _rsi14(prices),
        "indicator_source": "PERSISTED_OPTION_TELEMETRY" if rows else "NOT_AVAILABLE",
    }


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
    path = _database_path(database)
    kind = str(snapshot_type or "").upper()
    if not path or not order_id or kind not in SNAPSHOT_TYPES:
        return False
    initialize_option_telemetry_lifecycle(database)
    row = dict(telemetry or {})
    indicators = derive_persisted_option_indicators(database, order_id)
    timestamp = str(observed_timestamp or row.get("observed_timestamp") or datetime.now().astimezone().isoformat())
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
                spread_pct, option_vwap, option_rsi14, indicator_source,
                data_quality, reason_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lifecycle_id, order_id, kind, timestamp, row.get("observed_timestamp"),
                snapshot_source, row.get("pcr_oi"), row.get("delta"),
                row.get("call_oi_at_strike"), row.get("put_oi_at_strike"),
                row.get("iv"), row.get("best_bid"), row.get("best_ask"), row.get("spread_pct"),
                row.get("option_vwap", indicators["option_vwap"]),
                row.get("option_rsi14", indicators["option_rsi14"]),
                row.get("indicator_source", indicators["indicator_source"]),
                data_quality, reason_code, created_at,
            ),
        )
        conn.commit()
    return True


def record_active_telemetry_snapshot(database, order_id: str, telemetry: Mapping[str, object] | None) -> bool:
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
    return record_option_telemetry_snapshot(
        database,
        order_id=order_id,
        snapshot_type="ACTIVE" if existing else "ENTRY",
        telemetry=telemetry,
        snapshot_source="ACTIVE_CAPTURE",
    )


def record_exit_telemetry_exact(
    database,
    order_id: str,
    quote: Mapping[str, object] | None,
    latest_telemetry: Mapping[str, object] | None,
    *,
    observed_timestamp: str | None = None,
) -> bool:
    if not quote:
        return record_exit_telemetry_fallback(database, order_id, latest_telemetry)
    current = dict(latest_telemetry or {})
    provider = dict(quote)
    best_bid = _first_depth_price(provider, "buy")
    best_ask = _first_depth_price(provider, "sell")
    spread_points = None
    spread_pct = None
    if best_bid is not None and best_ask is not None and best_ask >= best_bid:
        spread_points = best_ask - best_bid
        midpoint = (best_bid + best_ask) / 2.0
        spread_pct = spread_points / midpoint * 100.0 if midpoint > 0 else None
    exact_delta = _number(provider.get("delta"))
    exact_iv = _number(provider.get("iv"))
    exact_pcr = _number(provider.get("pcr_oi") or provider.get("pcr"))
    indicators = derive_persisted_option_indicators(database, order_id)
    telemetry = {
        **current,
        "observed_timestamp": observed_timestamp,
        "current_price": _number(provider.get("last_price")),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_points": spread_points,
        "spread_pct": spread_pct,
        "iv": exact_iv if exact_iv is not None else current.get("iv"),
        "delta": exact_delta if exact_delta is not None else current.get("delta"),
        "gamma": provider.get("gamma") if provider.get("gamma") is not None else current.get("gamma"),
        "theta": provider.get("theta") if provider.get("theta") is not None else current.get("theta"),
        "vega": provider.get("vega") if provider.get("vega") is not None else current.get("vega"),
        "pcr_oi": exact_pcr if exact_pcr is not None else current.get("pcr_oi"),
        "option_vwap": indicators["option_vwap"],
        "option_rsi14": indicators["option_rsi14"],
        "indicator_source": indicators["indicator_source"],
    }
    fully_exact = exact_pcr is not None and exact_delta is not None
    return record_option_telemetry_snapshot(
        database,
        order_id=order_id,
        snapshot_type="EXIT",
        telemetry=telemetry,
        observed_timestamp=observed_timestamp,
        snapshot_source="EXACT_EXIT_QUOTE" if fully_exact else "EXACT_EXIT_QUOTE_WITH_ACTIVE_CONTEXT",
        data_quality="VALID" if fully_exact else "PARTIAL_EXACT",
        reason_code=None if fully_exact else "CHAIN_FIELDS_FROM_LAST_ACTIVE",
    )


def record_exit_telemetry_fallback(database, order_id: str, telemetry: Mapping[str, object] | None) -> bool:
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
            "SELECT * FROM option_telemetry_lifecycle WHERE order_id=? ORDER BY observed_timestamp ASC",
            (order_id,),
        ).fetchall()
    items = [dict(row) for row in rows]
    entry = next((row for row in items if row["snapshot_type"] == "ENTRY"), None)
    active = [row for row in items if row["snapshot_type"] == "ACTIVE"]
    exit_rows = [row for row in items if row["snapshot_type"] == "EXIT"]
    return {"entry": entry, "latest": active[-1] if active else entry, "exit": exit_rows[-1] if exit_rows else None}


__all__ = [
    "derive_persisted_option_indicators",
    "initialize_option_telemetry_lifecycle",
    "read_option_telemetry_lifecycle",
    "record_active_telemetry_snapshot",
    "record_exit_telemetry_exact",
    "record_exit_telemetry_fallback",
    "record_option_telemetry_snapshot",
]
