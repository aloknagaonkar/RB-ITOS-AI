from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


_SCHEMA = """
CREATE TABLE IF NOT EXISTS nifty_futures_diagnostic_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    underlying_name TEXT NOT NULL,
    instrument_key TEXT,
    trading_symbol TEXT,
    expiry TEXT,
    contract_status TEXT NOT NULL,
    market_status TEXT NOT NULL,
    candle_status TEXT NOT NULL,
    volume_status TEXT NOT NULL,
    oi_status TEXT NOT NULL,
    positioning_status TEXT NOT NULL,
    positioning_state TEXT NOT NULL,
    strength_status TEXT NOT NULL,
    strength TEXT NOT NULL,
    readiness_status TEXT NOT NULL,
    latest_close REAL,
    latest_volume REAL,
    latest_oi REAL,
    latest_timestamp TEXT,
    bar_open_timestamp TEXT,
    bar_close_timestamp TEXT,
    price_change REAL,
    price_change_pct REAL,
    oi_change REAL,
    oi_change_pct REAL,
    relative_volume REAL,
    baseline_volume REAL,
    baseline_samples INTEGER NOT NULL DEFAULT 0,
    blocking_reasons_json TEXT NOT NULL DEFAULT '[]',
    advisory_reasons_json TEXT NOT NULL DEFAULT '[]',
    authority TEXT NOT NULL DEFAULT 'OBSERVATIONAL_ONLY',
    payload_json TEXT NOT NULL,
    UNIQUE(underlying_name, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_nifty_futures_snapshot_time
ON nifty_futures_diagnostic_snapshots(underlying_name, observed_at DESC);
"""


def _payload(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key, None))
    }


def _normalize_timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return text
    parseable = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(parseable).isoformat()
    except ValueError:
        return text


def _ensure_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(nifty_futures_diagnostic_snapshots)"
        ).fetchall()
    }
    for name in ("bar_open_timestamp", "bar_close_timestamp"):
        if name not in columns:
            connection.execute(
                f"ALTER TABLE nifty_futures_diagnostic_snapshots ADD COLUMN {name} TEXT"
            )


def persist_nifty_futures_snapshot(
    database_path: str | Path,
    *,
    observed_at: datetime | str,
    underlying_name: str,
    contract,
    market,
    positioning,
    strength,
    readiness,
) -> int:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    observed = _normalize_timestamp(observed_at)
    contract_data = _payload(contract)
    market_data = _payload(market)
    positioning_data = _payload(positioning)
    strength_data = _payload(strength)
    readiness_data = _payload(readiness)
    payload = {
        "contract": contract_data,
        "market": market_data,
        "positioning": positioning_data,
        "strength": strength_data,
        "readiness": readiness_data,
    }
    values = (
        observed,
        str(underlying_name),
        contract_data.get("instrument_key"),
        contract_data.get("trading_symbol"),
        contract_data.get("expiry"),
        str(contract_data.get("status") or "UNAVAILABLE"),
        str(market_data.get("status") or "UNAVAILABLE"),
        str(readiness_data.get("candle_status") or "UNAVAILABLE"),
        str(readiness_data.get("volume_status") or "MISSING"),
        str(readiness_data.get("oi_status") or "MISSING"),
        str(positioning_data.get("status") or "INSUFFICIENT_DATA"),
        str(positioning_data.get("state") or "NEUTRAL"),
        str(strength_data.get("status") or "INSUFFICIENT_DATA"),
        str(strength_data.get("strength") or "INSUFFICIENT"),
        str(readiness_data.get("status") or "UNAVAILABLE"),
        market_data.get("latest_close"),
        market_data.get("latest_volume"),
        market_data.get("latest_oi"),
        market_data.get("latest_timestamp"),
        market_data.get("bar_open_timestamp"),
        market_data.get("bar_close_timestamp"),
        positioning_data.get("price_change"),
        positioning_data.get("price_change_pct"),
        positioning_data.get("oi_change"),
        positioning_data.get("oi_change_pct"),
        positioning_data.get("relative_volume"),
        positioning_data.get("baseline_volume"),
        int(positioning_data.get("baseline_samples") or 0),
        json.dumps(list(readiness_data.get("blocking_reasons") or ())),
        json.dumps(list(readiness_data.get("advisory_reasons") or ())),
        "OBSERVATIONAL_ONLY",
        json.dumps(payload, default=str, sort_keys=True),
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA)
        _ensure_columns(connection)
        cursor = connection.execute(
            """INSERT INTO nifty_futures_diagnostic_snapshots (
                observed_at, underlying_name, instrument_key, trading_symbol, expiry,
                contract_status, market_status, candle_status, volume_status, oi_status,
                positioning_status, positioning_state, strength_status, strength,
                readiness_status, latest_close, latest_volume, latest_oi, latest_timestamp,
                bar_open_timestamp, bar_close_timestamp,
                price_change, price_change_pct, oi_change, oi_change_pct, relative_volume,
                baseline_volume, baseline_samples, blocking_reasons_json,
                advisory_reasons_json, authority, payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(underlying_name, observed_at) DO UPDATE SET
                payload_json=excluded.payload_json,
                readiness_status=excluded.readiness_status,
                latest_close=excluded.latest_close,
                latest_volume=excluded.latest_volume,
                latest_oi=excluded.latest_oi,
                latest_timestamp=excluded.latest_timestamp,
                bar_open_timestamp=excluded.bar_open_timestamp,
                bar_close_timestamp=excluded.bar_close_timestamp,
                authority=excluded.authority""",
            values,
        )
        connection.commit()
        return int(cursor.lastrowid or 0)


def read_nifty_futures_snapshots(
    database_path: str | Path,
    *,
    underlying_name: str = "NIFTY 50",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Read futures diagnostics without creating or altering schema."""
    path = Path(database_path)
    if not path.exists():
        return []
    try:
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(nifty_futures_diagnostic_snapshots)"
                ).fetchall()
            }
            if not columns:
                return []
            rows = connection.execute(
                """SELECT * FROM nifty_futures_diagnostic_snapshots
                   WHERE underlying_name = ?
                   ORDER BY julianday(observed_at) DESC,
                            observed_at DESC
                   LIMIT ?""",
                (underlying_name, max(1, int(limit))),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise
    result = []
    for row in rows:
        item = dict(row)
        item["blocking_reasons"] = json.loads(
            item.pop("blocking_reasons_json", "[]") or "[]"
        )
        item["advisory_reasons"] = json.loads(
            item.pop("advisory_reasons_json", "[]") or "[]"
        )
        try:
            payload = json.loads(item.get("payload_json") or "{}")
        except json.JSONDecodeError:
            payload = {}
        market = payload.get("market") if isinstance(payload.get("market"), dict) else {}
        item["bar_open_timestamp"] = (
            item.get("bar_open_timestamp") or market.get("bar_open_timestamp")
        )
        item["bar_close_timestamp"] = (
            item.get("bar_close_timestamp")
            or market.get("bar_close_timestamp")
            or item.get("latest_timestamp")
        )
        item["futures_bar_open_timestamp"] = item["bar_open_timestamp"]
        item["futures_bar_close_timestamp"] = item["bar_close_timestamp"]
        item["futures_vwap"] = market.get("futures_vwap")
        item["futures_vwap_timestamp"] = market.get("futures_vwap_timestamp")
        item["futures_close_vs_vwap_points"] = market.get(
            "futures_close_vs_vwap_points"
        )
        item["futures_close_vs_vwap_atr"] = market.get(
            "futures_close_vs_vwap_atr"
        )
        item["futures_vwap_slope"] = market.get("futures_vwap_slope")
        item["futures_vwap_acceptance"] = (
            market.get("futures_vwap_acceptance") or "UNAVAILABLE"
        )
        item["vwap"] = market.get("futures_vwap")
        item["vwap_slope"] = market.get("futures_vwap_slope")
        result.append(item)
    return result
