from __future__ import annotations

from typing import Iterable, Mapping

import pandas as pd


CALL_TYPES = {"CE", "CALL"}
PUT_TYPES = {"PE", "PUT"}


def _number(value):
    try:
        if value in (None, ""):
            return None
        result = float(value)
        if pd.isna(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def _first(row: Mapping[str, object], names: Iterable[str]):
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _option_type(row: Mapping[str, object]) -> str:
    return str(
        _first(row, ("option_type", "instrument_type", "contract_type", "type"))
        or ""
    ).upper().strip()


def _timestamp(row: Mapping[str, object]):
    value = _first(
        row,
        ("snapshot_timestamp", "timestamp", "captured_at", "created_at"),
    )
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("Asia/Kolkata")
        else:
            ts = ts.tz_convert("Asia/Kolkata")
        return ts
    except (TypeError, ValueError):
        return None


def _sum(rows, names):
    total = 0.0
    found = False
    for row in rows:
        value = _number(_first(row, names))
        if value is None:
            continue
        total += value
        found = True
    return total if found else None


def _freshness(timestamp, trading_date: str):
    if timestamp is None:
        return "UNKNOWN", None
    now = pd.Timestamp.now(tz="Asia/Kolkata")
    if pd.Timestamp(trading_date).date() != now.date():
        return "HISTORICAL", None
    age_seconds = max(0.0, (now - timestamp).total_seconds())
    return ("FRESH" if age_seconds <= 180.0 else "STALE"), age_seconds


def _nearest_expiry(rows, trading_date: str):
    selected_date = pd.Timestamp(trading_date).date()
    ranked = []
    for row in rows:
        raw = _first(row, ("option_expiry", "expiry", "expiry_date"))
        try:
            expiry = pd.Timestamp(raw).date()
        except (TypeError, ValueError):
            expiry = None
        rank = (
            0 if expiry is not None and expiry >= selected_date else 1,
            expiry or pd.Timestamp.max.date(),
        )
        ranked.append((rank, row))
    return min(ranked, key=lambda item: item[0])[1] if ranked else {}


def build_option_behaviour_snapshot(database, instrument_key: str, trading_date: str):
    """Build read-only context from aggregate option-chain snapshot records."""
    try:
        rows = list(
            database.read_option_chain_history(
                instrument_key,
                trading_date,
                trading_date,
                limit=500,
            )
            or []
        )
    except Exception as exc:
        return {
            "status": "NOT READY",
            "directional_bias": "UNAVAILABLE",
            "detail": f"Stored option history could not be read: {exc}",
            "rows": [],
        }

    if not rows:
        return {
            "status": "NOT READY",
            "directional_bias": "UNAVAILABLE",
            "detail": "No stored option-chain snapshot is available for the selected date.",
            "rows": [],
        }

    timestamps = [ts for ts in (_timestamp(row) for row in rows) if ts is not None]
    latest_ts = max(timestamps) if timestamps else None
    latest_rows = (
        [row for row in rows if _timestamp(row) == latest_ts]
        if latest_ts is not None else rows
    )
    snapshot = dict(_nearest_expiry(latest_rows, trading_date))
    call_oi = _number(snapshot.get("total_call_oi"))
    put_oi = _number(snapshot.get("total_put_oi"))
    call_change_oi = _number(snapshot.get("total_call_oi_change"))
    put_change_oi = _number(snapshot.get("total_put_oi_change"))
    pcr = _number(snapshot.get("pcr_oi"))
    if pcr is None and call_oi not in (None, 0) and put_oi is not None:
        pcr = put_oi / call_oi

    bullish = 0
    bearish = 0
    if put_change_oi is not None and put_change_oi > 0:
        bullish += 1
    if call_change_oi is not None and call_change_oi < 0:
        bullish += 1
    if call_change_oi is not None and call_change_oi > 0:
        bearish += 1
    if put_change_oi is not None and put_change_oi < 0:
        bearish += 1
    if bullish >= 2 and bearish == 0:
        bias = "BULLISH POSITIONING"
    elif bearish >= 2 and bullish == 0:
        bias = "BEARISH POSITIONING"
    elif bullish > bearish:
        bias = "BULLISH LEAN"
    elif bearish > bullish:
        bias = "BEARISH LEAN"
    elif bullish or bearish:
        bias = "CONFLICT"
    else:
        bias = "NEUTRAL"

    behaviour_fields = (
        call_oi,
        put_oi,
        call_change_oi,
        put_change_oi,
    )
    status = "READY" if any(value is not None for value in behaviour_fields) else "PARTIAL"
    execution_status = "NOT EVALUATED"
    expiry = _first(snapshot, ("option_expiry", "expiry", "expiry_date"))
    freshness, age_seconds = _freshness(latest_ts, trading_date)
    if freshness == "STALE" and status == "READY":
        status = "STALE"

    display_rows = [
        {"input": "Latest stored snapshot", "value": latest_ts.isoformat() if latest_ts is not None else "Timestamp unavailable"},
        {"input": "Snapshot freshness", "value": freshness},
        {"input": "Snapshot age seconds", "value": round(age_seconds, 1) if age_seconds is not None else None},
        {"input": "Expiry", "value": expiry or "Unavailable"},
        {"input": "Total CE open interest", "value": call_oi},
        {"input": "Total PE open interest", "value": put_oi},
        {"input": "Total CE change in OI", "value": call_change_oi},
        {"input": "Total PE change in OI", "value": put_change_oi},
        {"input": "PCR (OI)", "value": round(pcr, 3) if pcr is not None else None},
        {"input": "Call wall", "value": snapshot.get("call_wall_strike")},
        {"input": "Put wall", "value": snapshot.get("put_wall_strike")},
        {"input": "Max pain", "value": snapshot.get("max_pain_strike")},
        {"input": "ATM call IV", "value": snapshot.get("atm_call_iv")},
        {"input": "ATM put IV", "value": snapshot.get("atm_put_iv")},
        {"input": "OI positioning bias", "value": bias},
        {"input": "Contract executability", "value": "Not evaluated in Section 1"},
    ]

    return {
        "status": status,
        "execution_status": execution_status,
        "directional_bias": bias,
        "latest_timestamp": latest_ts,
        "expiry": expiry,
        "ce_contracts": None,
        "pe_contracts": None,
        "pcr": pcr,
        "freshness": freshness,
        "age_seconds": age_seconds,
        "detail": "Aggregate OI context is supporting evidence. Contract price, spread and liquidity are evaluated later during contract selection.",
        "rows": display_rows,
    }
