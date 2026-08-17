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


def build_option_behaviour_snapshot(database, instrument_key: str, trading_date: str):
    """Build read-only option readiness and directional context from stored rows."""
    try:
        rows = list(
            database.read_option_chain_history(
                instrument_key,
                trading_date,
                trading_date,
                limit=1000,
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
    if latest_ts is not None:
        latest_rows = [row for row in rows if _timestamp(row) == latest_ts]
    else:
        latest_rows = rows

    call_rows = [row for row in latest_rows if _option_type(row) in CALL_TYPES]
    put_rows = [row for row in latest_rows if _option_type(row) in PUT_TYPES]

    call_oi = _sum(call_rows, ("open_interest", "oi", "call_oi", "ce_oi"))
    put_oi = _sum(put_rows, ("open_interest", "oi", "put_oi", "pe_oi"))
    call_change_oi = _sum(
        call_rows,
        ("change_in_oi", "change_oi", "oi_change", "call_change_oi", "ce_change_oi"),
    )
    put_change_oi = _sum(
        put_rows,
        ("change_in_oi", "change_oi", "oi_change", "put_change_oi", "pe_change_oi"),
    )
    call_volume = _sum(call_rows, ("volume", "traded_volume", "call_volume", "ce_volume"))
    put_volume = _sum(put_rows, ("volume", "traded_volume", "put_volume", "pe_volume"))

    pcr = None
    if call_oi not in (None, 0) and put_oi is not None:
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
    if call_volume is not None and put_volume is not None:
        if call_volume > put_volume:
            bullish += 1
        elif put_volume > call_volume:
            bearish += 1

    if bullish >= 3 and bearish == 0:
        bias = "STRONG BULLISH"
    elif bearish >= 3 and bullish == 0:
        bias = "STRONG BEARISH"
    elif bullish > bearish:
        bias = "BULLISH"
    elif bearish > bullish:
        bias = "BEARISH"
    elif bullish or bearish:
        bias = "CONFLICT"
    else:
        bias = "NEUTRAL"

    behaviour_fields = (
        call_oi,
        put_oi,
        call_change_oi,
        put_change_oi,
        call_volume,
        put_volume,
    )
    status = "READY" if any(value is not None for value in behaviour_fields) else "PARTIAL"
    execution_status = (
        "READY" if call_rows and put_rows else "PARTIAL"
    )
    expiry = _first(latest_rows[0], ("option_expiry", "expiry", "expiry_date"))

    display_rows = [
        {"input": "Latest stored snapshot", "value": latest_ts.isoformat() if latest_ts is not None else "Timestamp unavailable"},
        {"input": "Expiry", "value": expiry or "Unavailable"},
        {"input": "CE contracts", "value": len(call_rows)},
        {"input": "PE contracts", "value": len(put_rows)},
        {"input": "CE open interest", "value": call_oi},
        {"input": "PE open interest", "value": put_oi},
        {"input": "CE change in OI", "value": call_change_oi},
        {"input": "PE change in OI", "value": put_change_oi},
        {"input": "CE volume", "value": call_volume},
        {"input": "PE volume", "value": put_volume},
        {"input": "PCR (OI)", "value": round(pcr, 3) if pcr is not None else None},
        {"input": "Option directional bias", "value": bias},
    ]

    return {
        "status": status,
        "execution_status": execution_status,
        "directional_bias": bias,
        "latest_timestamp": latest_ts,
        "expiry": expiry,
        "ce_contracts": len(call_rows),
        "pe_contracts": len(put_rows),
        "pcr": pcr,
        "detail": "Stored option data is supporting evidence; price structure remains the primary strategy authority.",
        "rows": display_rows,
    }
