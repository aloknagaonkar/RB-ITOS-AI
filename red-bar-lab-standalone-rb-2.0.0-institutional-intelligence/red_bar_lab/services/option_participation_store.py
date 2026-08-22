from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from red_bar_lab.services.option_participation import OptionParticipationSummary

_SCHEMA = """
CREATE TABLE IF NOT EXISTS option_participation_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    underlying_name TEXT NOT NULL,
    spot_price REAL,
    atm_strike REAL,
    expiry TEXT,
    pcr_oi REAL,
    underlying_rsi REAL,
    ce_score REAL NOT NULL,
    pe_score REAL NOT NULL,
    recommended_side TEXT NOT NULL,
    recommended_direction TEXT NOT NULL,
    grade TEXT NOT NULL,
    reason TEXT NOT NULL,
    option_type TEXT NOT NULL,
    distance_rank INTEGER NOT NULL,
    instrument_key TEXT,
    instrument_token INTEGER,
    tradingsymbol TEXT NOT NULL,
    strike REAL,
    lot_size INTEGER,
    current_price REAL,
    vwap REAL,
    price_vs_vwap_pct REAL,
    premium_change_pct REAL,
    volume REAL,
    contract_volume REAL,
    oi REAL,
    prev_oi REAL,
    oi_change REAL,
    oi_change_pct REAL,
    delta REAL,
    iv REAL,
    option_rsi REAL,
    participation_state TEXT,
    strike_score REAL,
    bid REAL,
    ask REAL,
    spread REAL,
    authority TEXT NOT NULL DEFAULT 'OBSERVATIONAL_ONLY',
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(underlying_name, observed_at, option_type, distance_rank)
);
CREATE INDEX IF NOT EXISTS idx_option_participation_latest
ON option_participation_snapshots(
    underlying_name, observed_at DESC, option_type, distance_rank
);
"""


def persist_option_participation(
    database_path: str | Path,
    summary: OptionParticipationSummary,
) -> int:
    rows = []
    for item in summary.rows:
        raw = dict(item)
        rows.append((
            summary.observed_at, summary.underlying_name, summary.spot_price,
            summary.atm_strike, summary.expiry, summary.pcr_oi,
            summary.underlying_rsi, summary.ce_score, summary.pe_score,
            summary.recommended_side, summary.recommended_direction,
            summary.grade, summary.reason,
            str(raw.get("option_type") or "UNAVAILABLE"),
            int(raw.get("distance_rank") or 0), raw.get("instrument_key"),
            raw.get("instrument_token"),
            str(raw.get("tradingsymbol") or "UNAVAILABLE"),
            raw.get("strike"), raw.get("lot_size"), raw.get("current_price"),
            raw.get("vwap"), raw.get("price_vs_vwap_pct"),
            raw.get("premium_change_pct"), raw.get("volume"),
            raw.get("contract_volume"), raw.get("oi"), raw.get("prev_oi"),
            raw.get("oi_change"), raw.get("oi_change_pct"), raw.get("delta"),
            raw.get("iv"), raw.get("option_rsi"),
            raw.get("participation_state"), raw.get("strike_score"),
            raw.get("bid"), raw.get("ask"), raw.get("spread"),
            summary.authority,
            json.dumps(raw, default=str, sort_keys=True),
        ))
    if not rows:
        return 0
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA)
        connection.executemany(
            """INSERT OR REPLACE INTO option_participation_snapshots (
                observed_at, underlying_name, spot_price, atm_strike, expiry,
                pcr_oi, underlying_rsi, ce_score, pe_score, recommended_side,
                recommended_direction, grade, reason, option_type,
                distance_rank, instrument_key, instrument_token, tradingsymbol,
                strike, lot_size, current_price, vwap, price_vs_vwap_pct,
                premium_change_pct, volume, contract_volume, oi, prev_oi,
                oi_change, oi_change_pct, delta, iv, option_rsi,
                participation_state, strike_score, bid, ask, spread,
                authority, payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        connection.commit()
    return len(rows)


def _snapshot_rows(
    connection: sqlite3.Connection,
    *,
    underlying_name: str,
    observed_at: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT * FROM option_participation_snapshots
           WHERE underlying_name=? AND observed_at=?
           ORDER BY CASE option_type WHEN 'CE' THEN 0 ELSE 1 END,
                    distance_rank ASC""",
        (underlying_name, observed_at),
    ).fetchall()
    return [dict(row) for row in rows]


def _side_totals(rows: list[dict[str, Any]], side: str) -> dict[str, float]:
    selected = [row for row in rows if str(row.get("option_type")) == side]
    return {
        "volume": sum(float(row.get("volume") or 0.0) for row in selected),
        "contracts": sum(
            float(row.get("contract_volume") or 0.0) for row in selected
        ),
        "oi": sum(float(row.get("oi") or 0.0) for row in selected),
        "oi_change": sum(float(row.get("oi_change") or 0.0) for row in selected),
    }


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


def read_latest_option_participation(
    database_path: str | Path,
    *,
    underlying_name: str = "NIFTY 50",
) -> list[dict[str, Any]]:
    """Read latest snapshot without creating tables or indexes."""
    path = Path(database_path)
    if not path.exists():
        return []
    try:
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            stamps = connection.execute(
                """SELECT DISTINCT observed_at
                   FROM option_participation_snapshots
                   WHERE underlying_name=?
                   ORDER BY julianday(observed_at) DESC, observed_at DESC
                   LIMIT 2""",
                (underlying_name,),
            ).fetchall()
            if not stamps:
                return []
            latest_rows = _snapshot_rows(
                connection,
                underlying_name=underlying_name,
                observed_at=str(stamps[0]["observed_at"]),
            )
            previous_rows = (
                _snapshot_rows(
                    connection,
                    underlying_name=underlying_name,
                    observed_at=str(stamps[1]["observed_at"]),
                )
                if len(stamps) > 1
                else []
            )
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise

    changes: dict[str, Any] = {
        "previous_observed_at": (
            previous_rows[0].get("observed_at") if previous_rows else None
        )
    }
    for side in ("CE", "PE"):
        current = _side_totals(latest_rows, side)
        previous = _side_totals(previous_rows, side)
        prefix = side.lower()
        for metric in ("volume", "contracts", "oi", "oi_change"):
            changes[f"{prefix}_{metric}_change_pct"] = (
                _pct_change(current[metric], previous[metric])
                if previous_rows
                else None
            )
    for row in latest_rows:
        row.update(changes)
    return latest_rows


def summarize_option_participation(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not rows:
        return {}
    first = rows[0]
    result: dict[str, Any] = {
        "observed_at": first.get("observed_at"),
        "previous_observed_at": first.get("previous_observed_at"),
        "spot_price": first.get("spot_price"),
        "atm_strike": first.get("atm_strike"),
        "expiry": first.get("expiry"),
        "pcr_oi": first.get("pcr_oi"),
        "underlying_rsi": first.get("underlying_rsi"),
        "ce_score": first.get("ce_score"),
        "pe_score": first.get("pe_score"),
        "recommended_side": first.get("recommended_side"),
        "recommended_direction": first.get("recommended_direction"),
        "grade": first.get("grade"),
        "reason": first.get("reason"),
        "authority": first.get("authority"),
    }
    for side in ("CE", "PE"):
        side_rows = [
            row for row in rows if str(row.get("option_type")) == side
        ]
        total_volume = sum(
            float(row.get("volume") or 0.0) for row in side_rows
        )
        total_contracts = sum(
            float(row.get("contract_volume") or 0.0) for row in side_rows
        )
        total_oi = sum(float(row.get("oi") or 0.0) for row in side_rows)
        total_oi_change = sum(
            float(row.get("oi_change") or 0.0) for row in side_rows
        )
        rsi_weight = sum(
            float(row.get("volume") or 0.0)
            for row in side_rows
            if row.get("option_rsi") is not None
        )
        weighted_rsi = (
            sum(
                float(row.get("option_rsi") or 0.0)
                * float(row.get("volume") or 0.0)
                for row in side_rows
                if row.get("option_rsi") is not None
            ) / rsi_weight
            if rsi_weight > 0 else None
        )
        oi_weight = sum(
            float(row.get("oi") or 0.0)
            for row in side_rows
            if row.get("delta") is not None
        )
        weighted_delta = (
            sum(
                float(row.get("delta") or 0.0)
                * float(row.get("oi") or 0.0)
                for row in side_rows
                if row.get("delta") is not None
            ) / oi_weight
            if oi_weight > 0 else None
        )
        vwap_weight = sum(
            float(row.get("volume") or 0.0)
            for row in side_rows
            if row.get("vwap") is not None
        )
        weighted_vwap = (
            sum(
                float(row.get("vwap") or 0.0)
                * float(row.get("volume") or 0.0)
                for row in side_rows
                if row.get("vwap") is not None
            ) / vwap_weight
            if vwap_weight > 0 else None
        )
        prefix = side.lower()
        result[f"{prefix}_total_volume"] = total_volume
        result[f"{prefix}_total_contracts"] = total_contracts
        result[f"{prefix}_total_oi"] = total_oi
        result[f"{prefix}_total_oi_change"] = total_oi_change
        result[f"{prefix}_weighted_delta"] = weighted_delta
        result[f"{prefix}_weighted_vwap"] = weighted_vwap
        result[f"{prefix}_weighted_rsi"] = weighted_rsi
        for metric in ("volume", "contracts", "oi", "oi_change"):
            result[f"{prefix}_{metric}_change_pct"] = first.get(
                f"{prefix}_{metric}_change_pct"
            )

    ce_volume = float(result.get("ce_total_volume") or 0.0)
    pe_volume = float(result.get("pe_total_volume") or 0.0)
    ce_oi = float(result.get("ce_total_oi") or 0.0)
    pe_oi = float(result.get("pe_total_oi") or 0.0)
    result["pe_ce_volume_ratio"] = pe_volume / ce_volume if ce_volume > 0 else None
    result["pe_ce_oi_ratio"] = pe_oi / ce_oi if ce_oi > 0 else None
    ce_change = float(result.get("ce_total_oi_change") or 0.0)
    pe_change = float(result.get("pe_total_oi_change") or 0.0)
    result["pe_ce_oi_change_ratio"] = (
        pe_change / ce_change if ce_change != 0 else None
    )
    return result
