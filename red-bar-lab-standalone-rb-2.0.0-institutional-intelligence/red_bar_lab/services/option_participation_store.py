from __future__ import annotations

import json
from statistics import median
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


# Every column except payload_json, which is written for forensics but never
# read back. It is ~62% of each row's bytes, so selecting it dominates the
# cost of this read path.
_READ_COLUMNS = (
    "id, observed_at, underlying_name, spot_price, atm_strike, expiry, pcr_oi, "
    "underlying_rsi, ce_score, pe_score, recommended_side, "
    "recommended_direction, grade, reason, option_type, distance_rank, "
    "instrument_key, instrument_token, tradingsymbol, strike, lot_size, "
    "current_price, vwap, price_vs_vwap_pct, premium_change_pct, volume, "
    "contract_volume, oi, prev_oi, oi_change, oi_change_pct, delta, iv, "
    "option_rsi, participation_state, strike_score, bid, ask, spread, authority"
)


def _snapshot_rows_by_stamp(
    connection: sqlite3.Connection,
    *,
    underlying_name: str,
    stamps: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Fetch all rows for the given stamps in one query, grouped by stamp.

    Issued as a single ``IN`` lookup rather than one query per stamp; the
    per-stamp ordering (CE before PE, then distance_rank) is preserved because
    grouping keeps the relative order of the result set.
    """
    if not stamps:
        return {}
    placeholders = ",".join("?" * len(stamps))
    rows = connection.execute(
        f"""SELECT {_READ_COLUMNS} FROM option_participation_snapshots
           WHERE underlying_name=? AND observed_at IN ({placeholders})
           ORDER BY CASE option_type WHEN 'CE' THEN 0 ELSE 1 END,
                    distance_rank ASC""",
        (underlying_name, *stamps),
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {stamp: [] for stamp in stamps}
    for row in rows:
        grouped[str(row["observed_at"])].append(dict(row))
    return grouped


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


def _number_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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
            # julianday() is required, not incidental: observed_at is stored in
            # mixed ISO forms ("...T10:02:00+05:30" and "... 15:39:00+05:30").
            # Space sorts before "T", so plain text ordering would rank a later
            # space-form timestamp below an earlier T-form one. It costs a temp
            # B-tree sort; removing it needs the stored values normalised first.
            stamps = connection.execute(
                """SELECT DISTINCT observed_at
                   FROM option_participation_snapshots
                   WHERE underlying_name=?
                   ORDER BY julianday(observed_at) DESC, observed_at DESC
                   LIMIT 14""",
                (underlying_name,),
            ).fetchall()
            if not stamps:
                return []
            stamp_values = [str(stamp["observed_at"]) for stamp in stamps]
            grouped = _snapshot_rows_by_stamp(
                connection,
                underlying_name=underlying_name,
                stamps=stamp_values,
            )
            latest_rows = grouped.get(stamp_values[0], [])
            previous_rows = (
                grouped.get(stamp_values[1], []) if len(stamp_values) > 1 else []
            )
            historical_rows = [
                grouped.get(stamp, []) for stamp in stamp_values[1:]
            ]
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise

    changes: dict[str, Any] = {
        "previous_observed_at": (
            previous_rows[0].get("observed_at") if previous_rows else None
        )
    }
    previous_by_identity = {
        str(row.get("instrument_key") or row.get("tradingsymbol") or ""): row
        for row in previous_rows
        if row.get("instrument_key") or row.get("tradingsymbol")
    }
    historical_by_identity: dict[str, list[float]] = {}
    for snapshot_rows in historical_rows:
        for historical in snapshot_rows:
            identity = str(
                historical.get("instrument_key")
                or historical.get("tradingsymbol")
                or ""
            )
            volume = _number_or_none(historical.get("volume"))
            if identity and volume is not None:
                historical_by_identity.setdefault(identity, []).append(volume)
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
        identity = str(row.get("instrument_key") or row.get("tradingsymbol") or "")
        previous = previous_by_identity.get(identity)
        previous_price = _number_or_none(previous.get("current_price")) if previous else None
        previous_oi = _number_or_none(previous.get("oi")) if previous else None
        previous_volume = _number_or_none(previous.get("volume")) if previous else None
        current_price = _number_or_none(row.get("current_price"))
        current_oi = _number_or_none(row.get("oi"))
        current_volume = _number_or_none(row.get("volume"))
        row["previous_refresh_price"] = previous_price
        row["premium_change_from_previous_refresh_pct"] = (
            _pct_change(current_price, previous_price)
            if current_price is not None and previous_price is not None
            else None
        )
        row["previous_refresh_oi"] = previous_oi
        row["oi_change_from_previous_refresh"] = (
            current_oi - previous_oi
            if current_oi is not None and previous_oi is not None
            else None
        )
        row["previous_refresh_volume"] = previous_volume
        interval_volume = (
            current_volume - previous_volume
            if current_volume is not None
            and previous_volume is not None
            and current_volume >= previous_volume
            else None
        )
        history = historical_by_identity.get(identity, [])
        prior_intervals = [
            newer - older
            for newer, older in zip(history, history[1:])
            if newer >= older
        ][:12]
        baseline = (
            float(median(prior_intervals))
            if len(prior_intervals) >= 3
            else None
        )
        row["interval_volume"] = interval_volume
        row["median_interval_volume"] = baseline
        row["option_relative_volume"] = (
            interval_volume / baseline
            if interval_volume is not None and baseline is not None and baseline > 0
            else None
        )
        row["volume_change_from_previous_refresh_pct"] = (
            _pct_change(current_volume, previous_volume)
            if current_volume is not None and previous_volume is not None
            else None
        )
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
