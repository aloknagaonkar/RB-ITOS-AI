from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

import pandas as pd

_DISTANCE_WEIGHTS = {1: 1.00, 2: 0.90, 3: 0.75, 4: 0.55, 5: 0.35}


def _f(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _eligible(row: Mapping[str, object]) -> tuple[bool, str]:
    price = _f(row.get("current_price"))
    bid = _f(row.get("bid"))
    ask = _f(row.get("ask"))
    spread = _f(row.get("spread"))
    iv = _f(row.get("iv"))
    volume = _f(row.get("volume"))
    oi = _f(row.get("oi"))
    if price is None or price <= 0:
        return False, "MISSING_PRICE"
    if volume is None or volume <= 0 or oi is None or oi <= 0:
        return False, "ILLIQUID"
    if bid is not None and ask is not None and ask < bid:
        return False, "INVALID_QUOTE"
    effective_spread = spread
    if effective_spread is None and bid is not None and ask is not None:
        effective_spread = ask - bid
    if effective_spread is not None and effective_spread / price > 0.03:
        return False, "WIDE_SPREAD"
    if iv is not None and not 1.0 <= iv <= 150.0:
        return False, "IV_OUTLIER"
    return True, "ELIGIBLE"


def _strike_score(row: Mapping[str, object]) -> float:
    state = str(row.get("participation_state") or "INSUFFICIENT").upper()
    score = {
        "FRESH_BUYING": 30.0,
        "SHORT_COVERING": 22.0,
        "NEUTRAL": 8.0,
        "INSUFFICIENT": 0.0,
        "WRITING_PRESSURE": 0.0,
        "LONG_UNWINDING": 0.0,
    }.get(state, 0.0)

    price = _f(row.get("current_price"))
    vwap = _f(row.get("vwap"))
    if price is not None and vwap not in (None, 0) and price >= vwap:
        score += 20.0

    oi_pct = _f(row.get("oi_change_pct"))
    if oi_pct is not None:
        magnitude = min(abs(oi_pct), 20.0) / 20.0
        if state == "FRESH_BUYING":
            score += 15.0 * magnitude
        elif state == "SHORT_COVERING":
            score += 10.0 * magnitude

    option_rsi = _f(row.get("option_rsi"))
    if option_rsi is not None:
        if 55.0 <= option_rsi <= 70.0:
            score += 10.0
        elif 50.0 <= option_rsi < 55.0:
            score += 7.0
        elif 70.0 < option_rsi <= 75.0:
            score += 5.0
        elif 45.0 <= option_rsi < 50.0:
            score += 3.0

    delta = _f(row.get("delta"))
    if delta is not None:
        absolute = abs(delta)
        if 0.40 <= absolute <= 0.65:
            score += 10.0
        elif 0.30 <= absolute < 0.40 or 0.65 < absolute <= 0.75:
            score += 7.0
        elif 0.20 <= absolute < 0.30:
            score += 4.0

    # Volume is deliberately not awarded here. It is reported as participation
    # context, avoiding the previous score-plus-weight double counting.
    return round(min(100.0, score / 85.0 * 100.0), 2)


def corrected_option_summary(rows: Iterable[Mapping[str, object]]) -> dict[str, Any]:
    materialized = [dict(row) for row in rows]
    result: dict[str, Any] = {
        "ce_score": None,
        "pe_score": None,
        "eligible_ce": 0,
        "eligible_pe": 0,
        "rejected": 0,
        "rows": materialized,
    }
    for row in materialized:
        eligible, reason = _eligible(row)
        row["contract_eligibility"] = reason
        row["calibrated_strike_score"] = _strike_score(row) if eligible else None
        row["distance_weight"] = _DISTANCE_WEIGHTS.get(
            int(_f(row.get("distance_rank")) or 5), 0.25
        )
        if not eligible:
            result["rejected"] += 1

    for side in ("CE", "PE"):
        selected = [
            row for row in materialized
            if str(row.get("option_type") or "").upper() == side
            and row.get("calibrated_strike_score") is not None
        ]
        result[f"eligible_{side.lower()}"] = len(selected)
        if selected:
            weights = [float(row["distance_weight"]) for row in selected]
            result[f"{side.lower()}_score"] = round(
                sum(float(row["calibrated_strike_score"]) * weight for row, weight in zip(selected, weights))
                / sum(weights),
                2,
            )
        result[f"{side.lower()}_volume"] = sum(
            _f(row.get("volume")) or 0.0
            for row in materialized
            if str(row.get("option_type") or "").upper() == side
        )
        result[f"{side.lower()}_oi_change"] = sum(
            _f(row.get("oi_change")) or 0.0
            for row in materialized
            if str(row.get("option_type") or "").upper() == side
        )
    return result


def read_option_score_history(
    database_path: str | Path,
    *,
    underlying_name: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    path = Path(database_path)
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        stamps = connection.execute(
            """SELECT DISTINCT observed_at FROM option_participation_snapshots
               WHERE underlying_name=?
               ORDER BY julianday(observed_at) DESC, observed_at DESC LIMIT ?""",
            (underlying_name, max(1, int(limit))),
        ).fetchall()
        history = []
        for stamp in reversed(stamps):
            rows = connection.execute(
                """SELECT * FROM option_participation_snapshots
                   WHERE underlying_name=? AND observed_at=?""",
                (underlying_name, stamp["observed_at"]),
            ).fetchall()
            summary = corrected_option_summary(dict(row) for row in rows)
            summary["observed_at"] = stamp["observed_at"]
            history.append(summary)
    return history


def score_slope(history: list[Mapping[str, object]], side: str) -> float | None:
    values = [_f(item.get(f"{side.lower()}_score")) for item in history]
    clean = [value for value in values if value is not None]
    if len(clean) < 2:
        return None
    return round((clean[-1] - clean[0]) / (len(clean) - 1), 2)


def _rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    return 100.0 - 100.0 / (1.0 + rs)


def build_underlying_evidence(frame: pd.DataFrame | None) -> dict[str, Any]:
    unavailable = {
        "state": "UNAVAILABLE", "direction": "UNAVAILABLE",
        "momentum": "UNAVAILABLE", "rsi_view": "UNAVAILABLE",
        "observed_at": None, "reason": "Insufficient completed NIFTY candles.",
    }
    if frame is None or frame.empty:
        return unavailable
    work = frame.copy()
    timestamp_col = next((c for c in ("timestamp", "datetime", "date") if c in work.columns), None)
    if timestamp_col is None:
        return unavailable
    work[timestamp_col] = pd.to_datetime(work[timestamp_col], errors="coerce", utc=True)
    work = work.dropna(subset=[timestamp_col]).sort_values(timestamp_col).set_index(timestamp_col)
    for col in ("open", "high", "low", "close", "volume"):
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    if not {"open", "high", "low", "close"}.issubset(work.columns):
        return unavailable
    bars = work.resample("5min", origin="start_day", offset="15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    if len(bars) < 8:
        return unavailable

    previous_close = bars["close"].shift(1)
    true_range = pd.concat(
        [bars["high"] - bars["low"], (bars["high"] - previous_close).abs(), (bars["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(14, min_periods=5).mean().iloc[-1]
    latest = bars.iloc[-1]
    prior = bars.iloc[-6:-1]
    prior_high = float(prior["high"].max())
    prior_low = float(prior["low"].min())
    close = float(latest["close"])
    body = abs(float(latest["close"]) - float(latest["open"]))
    range_value = max(float(latest["high"]) - float(latest["low"]), 1e-9)
    body_atr = body / atr if atr and atr > 0 else 0.0
    net_atr = (close - float(bars["close"].iloc[-6])) / atr if atr and atr > 0 else 0.0
    close_location = (close - float(latest["low"])) / range_value

    bullish_break = close > prior_high and close_location >= 0.70
    bearish_break = close < prior_low and close_location <= 0.30
    if bullish_break and (body_atr >= 0.60 or net_atr >= 0.80):
        state, direction, momentum = "BULLISH_STRUCTURE", "BULLISH", "EXPANDING"
    elif bearish_break and (body_atr >= 0.60 or net_atr <= -0.80):
        state, direction, momentum = "BEARISH_STRUCTURE", "BEARISH", "EXPANDING"
    elif close > prior_high:
        state, direction, momentum = "TRANSITION_UP", "BULLISH", "EARLY"
    elif close < prior_low:
        state, direction, momentum = "TRANSITION_DOWN", "BEARISH", "EARLY"
    elif abs(net_atr) < 0.45:
        state, direction, momentum = "SIDEWAYS_COMPRESSION", "NEUTRAL", "COMPRESSED"
    else:
        direction = "BULLISH" if net_atr > 0 else "BEARISH"
        state, momentum = f"TRANSITION_{'UP' if net_atr > 0 else 'DOWN'}", "DEVELOPING"

    rsi = _rsi_series(bars["close"])
    latest_rsi = _f(rsi.iloc[-1])
    previous_rsi = _f(rsi.iloc[-3]) if len(rsi) >= 3 else None
    rsi_slope = latest_rsi - previous_rsi if latest_rsi is not None and previous_rsi is not None else None
    if latest_rsi is None or rsi_slope is None:
        rsi_view = "UNAVAILABLE"
    elif latest_rsi > 55 and rsi_slope > 0:
        rsi_view = "BULLISH"
    elif latest_rsi < 45 and rsi_slope < 0:
        rsi_view = "BEARISH"
    elif latest_rsi < 45 and rsi_slope > 0:
        rsi_view = "BULLISH_RECOVERY"
    elif latest_rsi > 55 and rsi_slope < 0:
        rsi_view = "BEARISH_FADE"
    else:
        rsi_view = "NEUTRAL"

    observed = bars.index[-1].to_pydatetime().astimezone(timezone.utc).isoformat()
    return {
        "state": state, "direction": direction, "momentum": momentum,
        "observed_at": observed, "atr": round(float(atr), 4) if atr else None,
        "body_atr": round(body_atr, 3), "net_move_atr": round(net_atr, 3),
        "rsi": round(latest_rsi, 2) if latest_rsi is not None else None,
        "rsi_slope": round(rsi_slope, 2) if rsi_slope is not None else None,
        "rsi_view": rsi_view,
        "reason": f"{state}; 5-bar move {net_atr:.2f} ATR; body {body_atr:.2f} ATR.",
    }


def read_underlying_evidence(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        return build_underlying_evidence(None)
    try:
        return build_underlying_evidence(pd.read_csv(source))
    except Exception:
        return build_underlying_evidence(None)
