from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from statistics import median
from typing import Any, Iterable, Mapping

import pandas as pd

_DISTANCE_WEIGHTS = {0: 1.00, 1: 0.90, 2: 0.75, 3: 0.55, 4: 0.35}
_MAX_HISTORY_GAP_SECONDS = 180


def _f(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dt(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _strike_step(rows: list[Mapping[str, object]]) -> float | None:
    values = {_f(row.get("strike")) for row in rows}
    strikes = sorted(value for value in values if value is not None)
    differences = [b - a for a, b in zip(strikes, strikes[1:]) if b > a]
    return float(median(differences)) if differences else None


def _distance_steps(row: Mapping[str, object], *, step: float | None) -> int:
    explicit = _f(row.get("strike_offset_steps"))
    if explicit is not None:
        return max(0, int(round(abs(explicit))))
    strike = _f(row.get("strike"))
    atm = _f(row.get("atm_strike"))
    if strike is not None and atm is not None and step not in (None, 0):
        return max(0, int(round(abs(strike - atm) / float(step))))
    rank = int(_f(row.get("distance_rank")) or 1)
    return max(0, (rank - 1 + 1) // 2)


def _eligible(row: Mapping[str, object]) -> tuple[bool, str]:
    price = _f(row.get("current_price"))
    bid = _f(row.get("bid"))
    ask = _f(row.get("ask"))
    supplied_spread = _f(row.get("spread"))
    iv = _f(row.get("iv"))
    volume = _f(row.get("volume"))
    oi = _f(row.get("oi"))
    if price is None or price <= 0:
        return False, "MISSING_PRICE"
    if volume is None or volume <= 0 or oi is None or oi <= 0:
        return False, "ILLIQUID"
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return False, "QUOTE_UNAVAILABLE"
    if ask < bid:
        return False, "INVALID_QUOTE"
    midpoint = (bid + ask) / 2.0
    if midpoint <= 0:
        return False, "INVALID_QUOTE"
    quote_spread = ask - bid
    effective_spread = max(quote_spread, supplied_spread or 0.0)
    spread_pct = effective_spread / midpoint * 100.0
    if spread_pct > 3.0:
        return False, "WIDE_SPREAD"
    if iv is None:
        return False, "IV_UNAVAILABLE"
    if not 1.0 <= iv <= 150.0:
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
    step = _strike_step(materialized)
    for row in materialized:
        eligible, reason = _eligible(row)
        row["contract_eligibility"] = reason
        row["normalized_strike_score"] = _strike_score(row) if eligible else None
        distance = min(4, _distance_steps(row, step=step))
        row["strike_distance_steps"] = distance
        row["distance_weight"] = _DISTANCE_WEIGHTS[distance]
        if not eligible:
            result["rejected"] += 1

    for side in ("CE", "PE"):
        selected = [
            row for row in materialized
            if str(row.get("option_type") or "").upper() == side
            and row.get("normalized_strike_score") is not None
        ]
        result[f"eligible_{side.lower()}"] = len(selected)
        if selected:
            weights = [float(row["distance_weight"]) for row in selected]
            result[f"{side.lower()}_score"] = round(
                sum(float(row["normalized_strike_score"]) * weight for row, weight in zip(selected, weights))
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
    try:
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            latest = connection.execute(
                """SELECT observed_at, expiry FROM option_participation_snapshots
                   WHERE underlying_name=?
                   ORDER BY julianday(observed_at) DESC, observed_at DESC LIMIT 1""",
                (underlying_name,),
            ).fetchone()
            if latest is None:
                return []
            latest_time = _dt(latest["observed_at"])
            if latest_time is None:
                return []
            trading_date = latest_time.date().isoformat()
            expiry = latest["expiry"]
            stamps = connection.execute(
                """SELECT DISTINCT observed_at FROM option_participation_snapshots
                   WHERE underlying_name=? AND substr(observed_at,1,10)=?
                     AND (expiry=? OR (expiry IS NULL AND ? IS NULL))
                   ORDER BY julianday(observed_at) DESC, observed_at DESC LIMIT ?""",
                (underlying_name, trading_date, expiry, expiry, max(1, int(limit))),
            ).fetchall()
            history: list[dict[str, Any]] = []
            previous_time: datetime | None = None
            for stamp in reversed(stamps):
                observed = _dt(stamp["observed_at"])
                if observed is None:
                    continue
                if previous_time is not None and (observed - previous_time).total_seconds() > _MAX_HISTORY_GAP_SECONDS:
                    history = []
                rows = connection.execute(
                    """SELECT * FROM option_participation_snapshots
                       WHERE underlying_name=? AND observed_at=?""",
                    (underlying_name, stamp["observed_at"]),
                ).fetchall()
                summary = corrected_option_summary(dict(row) for row in rows)
                summary["observed_at"] = stamp["observed_at"]
                history.append(summary)
                previous_time = observed
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise
    return history


def score_slope(history: list[Mapping[str, object]], side: str) -> float | None:
    points = [
        (_dt(item.get("observed_at")), _f(item.get(f"{side.lower()}_score")))
        for item in history
    ]
    clean = [(stamp, value) for stamp, value in points if stamp is not None and value is not None]
    if len(clean) < 2:
        return None
    elapsed_minutes = (clean[-1][0] - clean[0][0]).total_seconds() / 60.0
    if elapsed_minutes <= 0:
        return None
    return round((clean[-1][1] - clean[0][1]) / elapsed_minutes, 2)


def _rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    return 100.0 - 100.0 / (1.0 + rs)


def _completed_five_minute_bars(work: pd.DataFrame, *, as_of_timestamp: datetime) -> pd.DataFrame:
    bars = work.resample("5min", origin="start_day", offset="15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["open", "high", "low", "close"])
    as_of = as_of_timestamp.astimezone(timezone.utc)
    completed_cutoff = pd.Timestamp(as_of).floor("5min")
    return bars[bars.index + pd.Timedelta(minutes=5) <= completed_cutoff]


def build_underlying_evidence(
    frame: pd.DataFrame | None,
    *,
    as_of_timestamp: datetime | None = None,
) -> dict[str, Any]:
    unavailable = {
        "state": "UNAVAILABLE",
        "direction": "UNAVAILABLE",
        "momentum": "UNAVAILABLE",
        "rsi_view": "UNAVAILABLE",
        "observed_at": None,
        "reason": "Insufficient completed NIFTY candles.",
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
    if "volume" not in work.columns:
        work["volume"] = 0.0
    if not {"open", "high", "low", "close"}.issubset(work.columns):
        return unavailable
    as_of = as_of_timestamp or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    bars = _completed_five_minute_bars(work, as_of_timestamp=as_of)
    if bars.empty:
        return unavailable
    observed = bars.index[-1].to_pydatetime().astimezone(timezone.utc).isoformat()
    if len(bars) < 9:
        return {
            **unavailable,
            "observed_at": observed,
            "reason": "Latest completed NIFTY candle is available, but structure history is insufficient.",
        }

    previous_close = bars["close"].shift(1)
    true_range = pd.concat(
        [bars["high"] - bars["low"], (bars["high"] - previous_close).abs(), (bars["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    atr_series = true_range.rolling(14, min_periods=5).mean()
    atr = _f(atr_series.iloc[-1])
    if atr in (None, 0):
        return {
            **unavailable,
            "observed_at": observed,
            "reason": "Latest completed NIFTY candle is available, but ATR is unavailable.",
        }

    latest = bars.iloc[-1]
    breakout = bars.iloc[-2]
    prior = bars.iloc[-7:-2]
    prior_high = float(prior["high"].max())
    prior_low = float(prior["low"].min())
    breakout_close = float(breakout["close"])
    latest_close = float(latest["close"])
    breakout_range = max(float(breakout["high"]) - float(breakout["low"]), 1e-9)
    breakout_body = abs(float(breakout["close"]) - float(breakout["open"]))
    breakout_body_atr = breakout_body / atr
    breakout_location = (breakout_close - float(breakout["low"])) / breakout_range
    breakout_net_atr = (breakout_close - float(bars["close"].iloc[-7])) / atr

    bullish_break = breakout_close > prior_high and breakout_location >= 0.70
    bearish_break = breakout_close < prior_low and breakout_location <= 0.30
    bullish_expansion = breakout_body_atr >= 0.60 or breakout_net_atr >= 0.80
    bearish_expansion = breakout_body_atr >= 0.60 or breakout_net_atr <= -0.80
    bullish_hold = latest_close > prior_high
    bearish_hold = latest_close < prior_low

    current_prior = bars.iloc[-6:-1]
    current_high = float(current_prior["high"].max())
    current_low = float(current_prior["low"].min())
    current_range = max(float(latest["high"]) - float(latest["low"]), 1e-9)
    current_location = (latest_close - float(latest["low"])) / current_range
    current_body_atr = abs(float(latest["close"]) - float(latest["open"])) / atr
    current_net_atr = (latest_close - float(bars["close"].iloc[-6])) / atr
    live_bull_break = latest_close > current_high and current_location >= 0.70
    live_bear_break = latest_close < current_low and current_location <= 0.30

    if bullish_break and bullish_expansion and bullish_hold:
        state, direction, momentum, acceptance = "BULLISH_STRUCTURE", "BULLISH", "EXPANDING", "HOLD_CONFIRMED"
    elif bearish_break and bearish_expansion and bearish_hold:
        state, direction, momentum, acceptance = "BEARISH_STRUCTURE", "BEARISH", "EXPANDING", "HOLD_CONFIRMED"
    elif bullish_break and not bullish_hold:
        state, direction, momentum, acceptance = "FAILED_RECLAIM", "NEUTRAL", "FAILED", "FAILED_RECLAIM"
    elif bearish_break and not bearish_hold:
        state, direction, momentum, acceptance = "FAILED_RECLAIM", "NEUTRAL", "FAILED", "FAILED_RECLAIM"
    elif live_bull_break:
        state, direction, momentum, acceptance = "BREAK_DETECTED_UP", "BULLISH", "EARLY", "HOLD_PENDING"
    elif live_bear_break:
        state, direction, momentum, acceptance = "BREAK_DETECTED_DOWN", "BEARISH", "EARLY", "HOLD_PENDING"
    else:
        recent_range_atr = (float(bars["high"].iloc[-5:].max()) - float(bars["low"].iloc[-5:].min())) / atr
        direction_changes = int((bars["close"].diff().iloc[-5:].apply(lambda x: 1 if x > 0 else -1 if x < 0 else 0).diff().abs() > 0).sum())
        if abs(current_net_atr) < 0.45 and recent_range_atr < 1.5 and direction_changes >= 2:
            state, direction, momentum, acceptance = "SIDEWAYS_COMPRESSION", "NEUTRAL", "COMPRESSED", "NO_BREAK"
        elif abs(current_net_atr) < 0.45:
            state, direction, momentum, acceptance = "SIDEWAYS_VOLATILE", "NEUTRAL", "VOLATILE", "NO_BREAK"
        else:
            direction = "BULLISH" if current_net_atr > 0 else "BEARISH"
            state, momentum, acceptance = f"TRANSITION_{'UP' if current_net_atr > 0 else 'DOWN'}", "DEVELOPING", "NO_BREAK"

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

    return {
        "state": state,
        "direction": direction,
        "momentum": momentum,
        "acceptance_state": acceptance,
        "observed_at": observed,
        "atr": round(float(atr), 4),
        "body_atr": round(current_body_atr, 3),
        "net_move_atr": round(current_net_atr, 3),
        "rsi": round(latest_rsi, 2) if latest_rsi is not None else None,
        "rsi_slope": round(rsi_slope, 2) if rsi_slope is not None else None,
        "rsi_view": rsi_view,
        "reason": f"{state}/{acceptance}; 5-bar move {current_net_atr:.2f} ATR; body {current_body_atr:.2f} ATR.",
    }


def read_underlying_evidence(
    path: str | Path,
    *,
    as_of_timestamp: datetime | None = None,
) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        return build_underlying_evidence(None, as_of_timestamp=as_of_timestamp)
    try:
        return build_underlying_evidence(pd.read_csv(source), as_of_timestamp=as_of_timestamp)
    except Exception:
        return build_underlying_evidence(None, as_of_timestamp=as_of_timestamp)
