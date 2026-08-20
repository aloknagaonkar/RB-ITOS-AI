from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_candidate_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    underlying_name TEXT NOT NULL,
    recommendation_source TEXT NOT NULL,
    direction TEXT NOT NULL,
    rank INTEGER NOT NULL,
    role TEXT NOT NULL,
    instrument_token INTEGER,
    tradingsymbol TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike REAL,
    expiry TEXT,
    current_price REAL,
    vwap REAL,
    price_vs_vwap_pct REAL,
    delta REAL,
    iv REAL,
    volume REAL,
    oi REAL,
    bid REAL,
    ask REAL,
    spread REAL,
    candidate_score REAL,
    lot_size INTEGER,
    estimated_value REAL,
    pcr_oi REAL,
    pcr_oi_change REAL,
    pcr_status TEXT,
    pcr_view TEXT,
    pcr_snapshot_timestamp TEXT,
    underlying_rsi REAL,
    option_rsi REAL,
    rsi_timeframe TEXT,
    rsi_view TEXT,
    rsi_snapshot_timestamp TEXT,
    evidence_grade TEXT,
    suggested_action TEXT,
    authority TEXT NOT NULL DEFAULT 'OBSERVATIONAL_ONLY',
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(underlying_name, recommendation_source, observed_at, rank)
);
CREATE INDEX IF NOT EXISTS idx_trade_candidate_snapshot_latest
ON trade_candidate_snapshots(underlying_name, recommendation_source, observed_at DESC, rank);
"""


def _f(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def persist_trade_candidate_snapshots(
    database_path: str | Path,
    *,
    observed_at: datetime | str,
    underlying_name: str,
    recommendation_source: str,
    direction: str,
    candidates: Iterable[Mapping[str, object]],
) -> int:
    """Persist at most three ranked observational candidates.

    This store is independent of execution tables and is never consulted by
    signal admission, option selection, order entry, stop handling or exits.
    """
    observed = observed_at.isoformat() if isinstance(observed_at, datetime) else str(observed_at)
    roles = {1: "PRIMARY", 2: "SAFER", 3: "AGGRESSIVE"}
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for rank, raw in enumerate(list(candidates)[:3], start=1):
        item = dict(raw)
        current = _f(item.get("current_price") or item.get("ltp") or item.get("entry_price"))
        vwap = _f(item.get("vwap"))
        price_vs_vwap = None if current is None or not vwap else ((current - vwap) / vwap) * 100.0
        lot_size = int(item.get("lot_size") or 0) or None
        estimated_value = None if current is None or lot_size is None else current * lot_size
        rows.append((
            observed, underlying_name, recommendation_source, direction, rank,
            str(item.get("role") or roles[rank]), item.get("instrument_token"),
            str(item.get("tradingsymbol") or item.get("symbol") or "UNAVAILABLE"),
            str(item.get("option_type") or "UNAVAILABLE"), _f(item.get("strike")),
            item.get("expiry"), current, vwap, price_vs_vwap, _f(item.get("delta")),
            _f(item.get("iv")), _f(item.get("volume")), _f(item.get("oi")),
            _f(item.get("bid")), _f(item.get("ask")), _f(item.get("spread")),
            _f(item.get("candidate_score") or item.get("score")), lot_size, estimated_value,
            _f(item.get("pcr_oi")), _f(item.get("pcr_oi_change")), item.get("pcr_status"),
            item.get("pcr_view"), item.get("pcr_snapshot_timestamp"),
            _f(item.get("underlying_rsi")), _f(item.get("option_rsi")),
            str(item.get("rsi_timeframe") or "5m/1m RSI(14)"), item.get("rsi_view"),
            item.get("rsi_snapshot_timestamp"), item.get("evidence_grade"),
            item.get("suggested_action"), "OBSERVATIONAL_ONLY",
            json.dumps(item, default=str, sort_keys=True),
        ))
    if not rows:
        return 0
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA)
        connection.executemany(
            """INSERT OR REPLACE INTO trade_candidate_snapshots (
                observed_at, underlying_name, recommendation_source, direction, rank, role,
                instrument_token, tradingsymbol, option_type, strike, expiry, current_price,
                vwap, price_vs_vwap_pct, delta, iv, volume, oi, bid, ask, spread,
                candidate_score, lot_size, estimated_value, pcr_oi, pcr_oi_change,
                pcr_status, pcr_view, pcr_snapshot_timestamp, underlying_rsi, option_rsi,
                rsi_timeframe, rsi_view, rsi_snapshot_timestamp, evidence_grade,
                suggested_action, authority, payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        connection.commit()
    return len(rows)


def read_latest_trade_candidates(
    database_path: str | Path,
    *,
    underlying_name: str = "NIFTY 50",
    recommendation_source: str = "INDEPENDENT_MARKET",
    limit: int = 3,
) -> list[dict[str, Any]]:
    path = Path(database_path)
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(_SCHEMA)
        latest = connection.execute(
            """SELECT observed_at FROM trade_candidate_snapshots
               WHERE underlying_name=? AND recommendation_source=?
               ORDER BY julianday(observed_at) DESC, observed_at DESC LIMIT 1""",
            (underlying_name, recommendation_source),
        ).fetchone()
        if not latest:
            return []
        rows = connection.execute(
            """SELECT * FROM trade_candidate_snapshots
               WHERE underlying_name=? AND recommendation_source=? AND observed_at=?
               ORDER BY rank ASC LIMIT ?""",
            (underlying_name, recommendation_source, latest["observed_at"], max(1, int(limit))),
        ).fetchall()
    return [dict(row) for row in rows]
