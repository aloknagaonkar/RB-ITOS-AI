from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")


OPTION_CONTEXT_COLUMNS = (
    "signal_id",
    "instrument_key",
    "trading_date",
    "entry_timestamp",
    "option_expiry",
    "option_snapshot_timestamp",
    "option_snapshot_delay_seconds",
    "entry_aligned",
    "option_spot_price",
    "atm_strike",
    "total_call_oi",
    "total_put_oi",
    "pcr_oi",
    "total_call_oi_change",
    "total_put_oi_change",
    "pcr_oi_change",
    "call_wall_strike",
    "put_wall_strike",
    "max_pain_strike",
    "atm_call_iv",
    "atm_put_iv",
    "atm_call_delta",
    "atm_put_delta",
    "atm_call_gamma",
    "atm_put_gamma",
    "atm_call_theta",
    "atm_put_theta",
    "atm_call_vega",
    "atm_put_vega",
    "chain_artifact_path",
)


def _safe_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _max_pain_strike(chain: pd.DataFrame) -> float | None:
    if chain is None or chain.empty:
        return None

    strikes = pd.to_numeric(chain["strike"], errors="coerce").dropna()
    if strikes.empty:
        return None

    work = chain.copy()
    work["strike"] = pd.to_numeric(work["strike"], errors="coerce")
    work["call_oi"] = pd.to_numeric(
        work["call_oi"], errors="coerce"
    ).fillna(0.0)
    work["put_oi"] = pd.to_numeric(
        work["put_oi"], errors="coerce"
    ).fillna(0.0)

    best_strike = None
    best_pain = None

    for settlement in strikes:
        call_pain = (
            (float(settlement) - work["strike"]).clip(lower=0.0)
            * work["call_oi"]
        ).sum()
        put_pain = (
            (work["strike"] - float(settlement)).clip(lower=0.0)
            * work["put_oi"]
        ).sum()
        total = float(call_pain + put_pain)
        if best_pain is None or total < best_pain:
            best_pain = total
            best_strike = float(settlement)

    return best_strike


def summarize_option_chain(
    *,
    signal: dict[str, object],
    instrument_key: str,
    expiry: str,
    chain: pd.DataFrame,
    snapshot_timestamp: datetime | None = None,
    alignment_tolerance_seconds: int = 120,
    chain_artifact_path: str | None = None,
) -> dict[str, object]:
    if chain is None or chain.empty:
        raise ValueError("Option chain is empty.")

    snapshot_timestamp = snapshot_timestamp or datetime.now(IST)
    snap_ts = pd.Timestamp(snapshot_timestamp)
    if snap_ts.tzinfo is None:
        snap_ts = snap_ts.tz_localize("Asia/Kolkata")
    else:
        snap_ts = snap_ts.tz_convert("Asia/Kolkata")

    entry_ts = pd.Timestamp(signal["confirmation_timestamp"])
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize("Asia/Kolkata")
    else:
        entry_ts = entry_ts.tz_convert("Asia/Kolkata")

    delay = (snap_ts - entry_ts).total_seconds()
    entry_aligned = (
        delay >= 0
        and delay <= float(alignment_tolerance_seconds)
    )

    work = chain.copy()
    numeric_cols = (
        "spot", "strike", "call_oi", "put_oi",
        "call_oi_change", "put_oi_change",
        "call_iv", "put_iv", "call_delta", "put_delta",
        "call_gamma", "put_gamma", "call_theta", "put_theta",
        "call_vega", "put_vega",
    )
    for col in numeric_cols:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    spot_values = work["spot"].dropna()
    if spot_values.empty:
        raise ValueError("Option chain does not contain spot price.")
    spot = float(spot_values.iloc[0])

    valid_strikes = work.dropna(subset=["strike"])
    if valid_strikes.empty:
        raise ValueError("Option chain does not contain valid strikes.")

    atm_index = (valid_strikes["strike"] - spot).abs().idxmin()
    atm = work.loc[atm_index]

    total_call_oi = float(work["call_oi"].fillna(0.0).sum())
    total_put_oi = float(work["put_oi"].fillna(0.0).sum())
    call_change = float(work["call_oi_change"].fillna(0.0).sum())
    put_change = float(work["put_oi_change"].fillna(0.0).sum())

    pcr = (
        total_put_oi / total_call_oi
        if total_call_oi > 0 else None
    )
    pcr_change = (
        put_change / call_change
        if call_change != 0 else None
    )

    call_wall = None
    put_wall = None
    if total_call_oi > 0:
        call_wall = float(
            work.loc[work["call_oi"].fillna(0.0).idxmax(), "strike"]
        )
    if total_put_oi > 0:
        put_wall = float(
            work.loc[work["put_oi"].fillna(0.0).idxmax(), "strike"]
        )

    return {
        "signal_id": signal.get("signal_id"),
        "instrument_key": instrument_key,
        "trading_date": str(signal.get("trading_date")),
        "entry_timestamp": entry_ts.isoformat(),
        "option_expiry": expiry,
        "option_snapshot_timestamp": snap_ts.isoformat(),
        "option_snapshot_delay_seconds": float(delay),
        "entry_aligned": 1 if entry_aligned else 0,
        "option_spot_price": spot,
        "atm_strike": _safe_float(atm.get("strike")),
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "pcr_oi": pcr,
        "total_call_oi_change": call_change,
        "total_put_oi_change": put_change,
        "pcr_oi_change": pcr_change,
        "call_wall_strike": call_wall,
        "put_wall_strike": put_wall,
        "max_pain_strike": _max_pain_strike(work),
        "atm_call_iv": _safe_float(atm.get("call_iv")),
        "atm_put_iv": _safe_float(atm.get("put_iv")),
        "atm_call_delta": _safe_float(atm.get("call_delta")),
        "atm_put_delta": _safe_float(atm.get("put_delta")),
        "atm_call_gamma": _safe_float(atm.get("call_gamma")),
        "atm_put_gamma": _safe_float(atm.get("put_gamma")),
        "atm_call_theta": _safe_float(atm.get("call_theta")),
        "atm_put_theta": _safe_float(atm.get("put_theta")),
        "atm_call_vega": _safe_float(atm.get("call_vega")),
        "atm_put_vega": _safe_float(atm.get("put_vega")),
        "chain_artifact_path": chain_artifact_path,
    }


def write_option_context_csv(rows, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(list(rows))
    for col in OPTION_CONTEXT_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    frame.loc[:, list(OPTION_CONTEXT_COLUMNS)].to_csv(
        output_path, index=False
    )
    return output_path
