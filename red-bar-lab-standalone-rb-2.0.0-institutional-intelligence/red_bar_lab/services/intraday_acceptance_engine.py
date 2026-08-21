from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


def _f(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _prepare(frame: pd.DataFrame | None, *, as_of_timestamp: datetime) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    timestamp_col = next((name for name in ("timestamp", "datetime", "date") if name in work.columns), None)
    if timestamp_col is None:
        return pd.DataFrame()
    work[timestamp_col] = pd.to_datetime(work[timestamp_col], errors="coerce", utc=True)
    work = work.dropna(subset=[timestamp_col]).sort_values(timestamp_col).set_index(timestamp_col)
    for column in ("open", "high", "low", "close", "volume"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce")
    if not {"open", "high", "low", "close"}.issubset(work.columns):
        return pd.DataFrame()
    if "volume" not in work.columns:
        work["volume"] = 0.0

    # Normalize inconsistent provider/test OHLC rows before any range logic.
    work["high"] = work[["open", "high", "low", "close"]].max(axis=1)
    work["low"] = work[["open", "high", "low", "close"]].min(axis=1)

    cutoff = pd.Timestamp(as_of_timestamp.astimezone(timezone.utc)).floor("min")
    # A row stamped 10:17 represents the 10:17–10:17:59 candle and is usable
    # only after 10:18 begins.
    return work[work.index + pd.Timedelta(minutes=1) <= cutoff]


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period, min_periods=5).mean()


def build_spot_vwap_acceptance(
    frame: pd.DataFrame | None,
    *,
    as_of_timestamp: datetime | None = None,
) -> dict[str, Any]:
    now = as_of_timestamp or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    work = _prepare(frame, as_of_timestamp=now)
    unavailable = {
        "state": "UNAVAILABLE",
        "direction": "UNAVAILABLE",
        "vwap": None,
        "vwap_slope": None,
        "gap_atr": None,
        "observed_at": None,
        "reason": "Spot VWAP unavailable.",
    }
    if len(work) < 15:
        return unavailable
    positive = work["volume"].fillna(0.0) > 0
    if int(positive.sum()) < 5:
        unavailable["state"] = "VWAP_UNAVAILABLE_ZERO_VOLUME"
        unavailable["reason"] = "Provider supplied no usable NIFTY spot volume; no synthetic VWAP was invented."
        unavailable["observed_at"] = work.index[-1].to_pydatetime().isoformat()
        return unavailable

    typical = (work["high"] + work["low"] + work["close"]) / 3.0
    volume = work["volume"].fillna(0.0)
    cumulative_volume = volume.cumsum().replace(0.0, pd.NA)
    vwap_series = (typical * volume).cumsum() / cumulative_volume
    vwap = _f(vwap_series.iloc[-1])
    prior_vwap = _f(vwap_series.iloc[-6]) if len(vwap_series) >= 6 else None
    atr = _f(_atr(work).iloc[-1])
    close = _f(work["close"].iloc[-1])
    if None in (vwap, prior_vwap, atr, close) or atr == 0:
        return unavailable
    slope = float(vwap) - float(prior_vwap)
    gap_atr = (float(close) - float(vwap)) / float(atr)
    if gap_atr >= 0.20 and slope > 0:
        state, direction = "BULLISH_ACCEPTANCE", "BULLISH"
    elif gap_atr <= -0.20 and slope < 0:
        state, direction = "BEARISH_ACCEPTANCE", "BEARISH"
    elif abs(gap_atr) <= 0.10:
        state, direction = "VWAP_BALANCED", "NEUTRAL"
    else:
        state, direction = "VWAP_TRANSITION", "NEUTRAL"
    return {
        "state": state,
        "direction": direction,
        "vwap": round(float(vwap), 4),
        "vwap_slope": round(slope, 4),
        "gap_atr": round(gap_atr, 3),
        "observed_at": work.index[-1].to_pydatetime().isoformat(),
        "reason": f"{state}; close-to-VWAP gap {gap_atr:.2f} ATR; 5m VWAP slope {slope:.2f}.",
    }


def build_one_minute_early_evidence(
    frame: pd.DataFrame | None,
    *,
    as_of_timestamp: datetime | None = None,
    vwap_acceptance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    now = as_of_timestamp or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    work = _prepare(frame, as_of_timestamp=now)
    unavailable = {
        "state": "UNAVAILABLE",
        "direction": "UNAVAILABLE",
        "observed_at": None,
        "body_atr": None,
        "reason": "Insufficient completed one-minute candles.",
    }
    if len(work) < 16:
        return unavailable
    atr = _f(_atr(work).iloc[-1])
    if atr in (None, 0):
        return unavailable
    latest = work.iloc[-1]
    prior = work.iloc[-11:-1]
    close = float(latest["close"])
    prior_high = float(prior["high"].max())
    prior_low = float(prior["low"].min())
    candle_range = max(float(latest["high"]) - float(latest["low"]), 1e-9)
    close_location = (close - float(latest["low"])) / candle_range
    body_atr = abs(float(latest["close"]) - float(latest["open"])) / float(atr)

    # Early detection is intentionally less strict than 5m confirmation. A
    # completed 1m close must clear the prior range, close in the directional
    # half of its candle, and show a non-trivial body. It can only create an
    # EARLY state; completed 5m hold remains the confirmation authority.
    bullish_break = close > prior_high and close_location >= 0.50 and body_atr >= 0.25
    bearish_break = close < prior_low and close_location <= 0.50 and body_atr >= 0.25

    vwap_direction = str((vwap_acceptance or {}).get("direction") or "UNAVAILABLE").upper()
    if bullish_break and vwap_direction != "BEARISH":
        state, direction = "BREAK_DETECTED_UP", "BULLISH"
    elif bearish_break and vwap_direction != "BULLISH":
        state, direction = "BREAK_DETECTED_DOWN", "BEARISH"
    elif bullish_break or bearish_break:
        state, direction = "BREAK_VWAP_CONFLICT", "NEUTRAL"
    else:
        state, direction = "NO_BREAK", "NEUTRAL"
    return {
        "state": state,
        "direction": direction,
        "observed_at": work.index[-1].to_pydatetime().isoformat(),
        "body_atr": round(body_atr, 3),
        "reason": f"{state}; completed 1m body {body_atr:.2f} ATR; VWAP {vwap_direction}.",
    }


def build_futures_vwap_acceptance(futures: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    raw_payload = futures.get("payload_json")
    if isinstance(raw_payload, str) and raw_payload.strip():
        try:
            parsed = json.loads(raw_payload)
            payload = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            payload = {}
    market = payload.get("market") if isinstance(payload.get("market"), dict) else {}
    latest = _f(futures.get("latest_close") or market.get("latest_close"))
    vwap = _f(
        futures.get("vwap")
        or futures.get("latest_vwap")
        or market.get("vwap")
        or market.get("latest_vwap")
    )
    slope = _f(futures.get("vwap_slope") or market.get("vwap_slope"))
    if latest is None or vwap is None:
        return {
            "state": "UNAVAILABLE",
            "direction": "UNAVAILABLE",
            "reason": "Futures snapshot does not yet expose VWAP.",
        }
    gap_pct = (latest - vwap) / vwap * 100.0 if vwap else 0.0
    if gap_pct >= 0.03 and (slope is None or slope >= 0):
        state, direction = "BULLISH_ACCEPTANCE", "BULLISH"
    elif gap_pct <= -0.03 and (slope is None or slope <= 0):
        state, direction = "BEARISH_ACCEPTANCE", "BEARISH"
    else:
        state, direction = "VWAP_BALANCED", "NEUTRAL"
    return {
        "state": state,
        "direction": direction,
        "vwap": vwap,
        "gap_pct": round(gap_pct, 4),
        "vwap_slope": slope,
        "reason": f"{state}; futures close-to-VWAP gap {gap_pct:.3f}%.",
    }


def read_intraday_acceptance(
    path: str | Path,
    *,
    as_of_timestamp: datetime | None = None,
) -> dict[str, Any]:
    source = Path(path)
    frame = pd.read_csv(source) if source.exists() else None
    vwap = build_spot_vwap_acceptance(frame, as_of_timestamp=as_of_timestamp)
    early = build_one_minute_early_evidence(
        frame,
        as_of_timestamp=as_of_timestamp,
        vwap_acceptance=vwap,
    )
    return {"spot_vwap": vwap, "early_1m": early}


__all__ = [
    "build_futures_vwap_acceptance",
    "build_one_minute_early_evidence",
    "build_spot_vwap_acceptance",
    "read_intraday_acceptance",
]
