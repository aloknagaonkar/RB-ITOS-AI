"""Opening Red Candle Midpoint Evidence Research V1.

Purpose
-------
Research whether a bearish 5-minute reference-candle midpoint/low breakdown
is supported by contemporaneous price, option OI/premium/volume, and PCR
evidence, and whether the move subsequently:

* BREAK_AND_GO
* BREAK_AND_BASE_THEN_GO
* SIDEWAYS_NO_CONTINUATION
* FALSE_BREAK_RECLAIM
* NO_LOW_BREAK
* NO_MIDPOINT_BREAK

This is research only. It does not emit BUY/SELL orders.

Frozen structure definition
---------------------------
1. Build exchange-session-anchored 5-minute OHLC bars from exact 1-minute
   underlying candles.
2. Ignore the first 09:15-09:19 candle regardless of color.
3. Use the first later completed RED candle (close < open) as the one and only
   session reference candle.
4. Reference midpoint = (high + low) / 2.
5. A downside midpoint break requires a 1-minute CLOSE below midpoint.
6. A low break requires a later/equal 1-minute CLOSE below reference low.
7. The original midpoint remains persistent for the entire session.
8. A reclaim requires a later 1-minute CLOSE above the original midpoint.
9. Outcome observation horizon after low break = 30 minutes.
10. Research continuation threshold =
    reference_low - max(10 NIFTY points, 0.50 * reference_range).
    This threshold labels future behaviour only; it is NOT a live entry input.
11. Reaching the continuation threshold within 5 minutes, before reclaim,
    is BREAK_AND_GO.
12. Reaching it in 6-30 minutes, before reclaim, is BREAK_AND_BASE_THEN_GO.
13. Reclaim before continuation threshold is FALSE_BREAK_RECLAIM.
14. Neither continuation nor reclaim in 30 minutes is SIDEWAYS_NO_CONTINUATION.

Evidence snapshots are taken at LOW_BREAK T0 and T+1/T+3/T+5, using only data
available at those exact timestamps. Future outcome labels are stored separately
and never used as an evidence feature.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

RESEARCH_VERSION = "OPENING_RED_MIDPOINT_EVIDENCE_V1_1"
IST = timezone(timedelta(hours=5, minutes=30))

ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
FORBIDDEN_BLOCKS = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}

SESSION_START = time(9, 15)
SESSION_END = time(15, 29)
FIRST_5M_START = time(9, 15)
FIRST_ELIGIBLE_REFERENCE_START = time(9, 20)

EVIDENCE_OFFSETS_MINUTES = (0, 1, 3, 5)
OUTCOME_HORIZON_MINUTES = 30
BREAK_AND_GO_MAX_MINUTES = 5
MIN_CONTINUATION_POINTS = 10.0
CONTINUATION_REFERENCE_RANGE_FRACTION = 0.50


@dataclass(frozen=True)
class BlockInput:
    name: str
    underlying_path: Path
    evidence_path: Path
    positioning_path: Path


def normalize_block_name(name: str) -> str:
    return name.strip().upper().replace("-", "_")


def parse_block(value: str) -> BlockInput:
    parts = value.split("|")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "--block must be NAME|UNDERLYING_1M_OHLC_CSV|EVIDENCE_CSV|POSITIONING_CSV"
        )
    name, underlying, evidence, positioning = parts
    name = normalize_block_name(name)
    if name in FORBIDDEN_BLOCKS:
        raise argparse.ArgumentTypeError(
            f"{name} is forbidden for V1 development research"
        )
    if name not in ALLOWED_BLOCKS:
        raise argparse.ArgumentTypeError(
            f"Unsupported block {name}; allowed={sorted(ALLOWED_BLOCKS)}"
        )
    return BlockInput(
        name,
        Path(underlying),
        Path(evidence),
        Path(positioning),
    )


def parse_dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST).replace(second=0, microsecond=0)


def f(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out if math.isfinite(out) else None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "unavailable"}:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def require_columns(
    rows: Sequence[dict[str, str]],
    required: set[str],
    path: Path,
) -> None:
    if not rows:
        raise ValueError(f"{path} has no rows")
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")


def minute_key(session_date: str, timestamp: str) -> tuple[str, datetime]:
    return session_date, parse_dt(timestamp)


def underlying_by_session(
    rows: Sequence[dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, datetime]] = set()

    for row in rows:
        session_date = row["session_date"]
        ts = parse_dt(row["timestamp"])
        key = (session_date, ts)
        if key in seen:
            raise ValueError(f"Duplicate underlying minute {key}")
        seen.add(key)

        open_ = f(row.get("open"))
        high = f(row.get("high"))
        low = f(row.get("low"))
        close = f(row.get("close"))
        if None in (open_, high, low, close):
            continue

        groups[session_date].append(
            {
                "session_date": session_date,
                "timestamp": ts,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": f(row.get("volume")),
            }
        )

    for session in groups.values():
        session.sort(key=lambda x: x["timestamp"])
    return dict(groups)


def bucket_start_5m(ts: datetime) -> datetime:
    anchor = ts.replace(hour=9, minute=15, second=0, microsecond=0)
    delta = int((ts - anchor).total_seconds() // 60)
    if delta < 0:
        raise ValueError("timestamp before 09:15 IST")
    bucket = (delta // 5) * 5
    return anchor + timedelta(minutes=bucket)


def aggregate_5m(
    minute_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in minute_rows:
        ts = row["timestamp"]
        local_t = ts.time().replace(tzinfo=None)
        if local_t < SESSION_START or local_t > SESSION_END:
            continue
        groups[bucket_start_5m(ts)].append(row)

    bars: list[dict[str, Any]] = []
    for start in sorted(groups):
        rows = sorted(groups[start], key=lambda x: x["timestamp"])

        expected = [start + timedelta(minutes=i) for i in range(5)]
        actual = [r["timestamp"] for r in rows]
        if actual != expected:
            continue

        bars.append(
            {
                "start": start,
                "end": start + timedelta(minutes=4),
                "open": rows[0]["open"],
                "high": max(r["high"] for r in rows),
                "low": min(r["low"] for r in rows),
                "close": rows[-1]["close"],
                "volume": (
                    sum(r["volume"] for r in rows if r["volume"] is not None)
                    if any(r["volume"] is not None for r in rows)
                    else None
                ),
            }
        )
    return bars


def select_reference_red_bar(
    bars: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    for bar in bars:
        start_t = bar["start"].time().replace(tzinfo=None)
        if start_t < FIRST_ELIGIBLE_REFERENCE_START:
            continue
        if bar["close"] < bar["open"]:
            return bar
    return None


def index_exact_rows(
    rows: Sequence[dict[str, str]],
) -> dict[tuple[str, datetime], dict[str, str]]:
    out: dict[tuple[str, datetime], dict[str, str]] = {}
    for row in rows:
        key = minute_key(row["session_date"], row["timestamp"])
        if key in out:
            raise ValueError(f"Duplicate exact minute row {key}")
        out[key] = row
    return out


def positioning_atm_index(
    rows: Sequence[dict[str, str]],
) -> dict[tuple[str, datetime], dict[str, str]]:
    out: dict[tuple[str, datetime], dict[str, str]] = {}
    for row in rows:
        offset = f(row.get("strike_offset"))
        if offset is None or abs(offset) > 1e-9:
            continue
        key = minute_key(row["session_date"], row["timestamp"])
        if key in out:
            raise ValueError(f"Duplicate ATM positioning row {key}")
        out[key] = row
    return out


def ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1.0 - alpha) * result[-1])
    return result


def exact_row_index(
    minute_rows: Sequence[dict[str, Any]],
) -> dict[datetime, int]:
    return {row["timestamp"]: i for i, row in enumerate(minute_rows)}


def spot_features(
    minute_rows: Sequence[dict[str, Any]],
    row_index: dict[datetime, int],
    ts: datetime,
    midpoint: float,
    reference_low: float,
    midpoint_cross_count: int,
) -> dict[str, Any]:
    """Return every price feature that is legitimately available at ``ts``.

    V1 incorrectly returned no price features at all until 15 minutes of
    history existed. V1.1 keeps shorter-horizon information when it exists:
    1m momentum needs 1 prior minute, 5m momentum needs 5, while 15m momentum
    and 15m realized volatility still require the full 15-minute history.
    """
    i = row_index.get(ts)
    if i is None:
        return {"price_status": "UNAVAILABLE"}

    closes = [r["close"] for r in minute_rows]
    close = closes[i]

    fast_series = ema(closes[: i + 1], 5)
    slow_series = ema(closes[: i + 1], 15)

    spot_momentum_1m = close - closes[i - 1] if i >= 1 else None
    spot_momentum_5m = close - closes[i - 5] if i >= 5 else None
    spot_momentum_15m = close - closes[i - 15] if i >= 15 else None

    ema_5 = fast_series[-1] if i >= 4 else None
    ema_15 = slow_series[-1] if i >= 14 else None
    ema_spread = (
        ema_5 - ema_15
        if ema_5 is not None and ema_15 is not None
        else None
    )
    ema_5_slope_3m = (
        fast_series[-1] - fast_series[-4]
        if i >= 4
        else None
    )

    realized_vol_15m = None
    if i >= 15:
        one_minute_changes = [
            closes[j] - closes[j - 1]
            for j in range(i - 14, i + 1)
        ]
        if len(one_minute_changes) >= 2:
            realized_vol_15m = statistics.pstdev(one_minute_changes)

    return {
        "price_status": "AVAILABLE_FULL" if i >= 15 else "AVAILABLE_PARTIAL",
        "history_minutes_available": i,
        "spot": close,
        "spot_momentum_1m": spot_momentum_1m,
        "spot_momentum_5m": spot_momentum_5m,
        "spot_momentum_15m": spot_momentum_15m,
        "ema_5": ema_5,
        "ema_15": ema_15,
        "ema_5_minus_ema_15": ema_spread,
        "ema_5_slope_3m": ema_5_slope_3m,
        "realized_vol_15m": realized_vol_15m,
        "distance_from_midpoint_points": close - midpoint,
        "distance_from_reference_low_points": close - reference_low,
        "midpoint_cross_count": midpoint_cross_count,
    }


def _count_level_crosses(
    rows: Sequence[dict[str, Any]],
    level: float,
) -> int:
    previous: str | None = None
    crosses = 0
    for row in rows:
        close = row["close"]
        side = "BELOW" if close < level else "ABOVE" if close > level else "AT"
        if side == "AT":
            continue
        if previous is not None and side != previous:
            crosses += 1
        previous = side
    return crosses


def _ending_streak(
    rows: Sequence[dict[str, Any]],
    predicate,
) -> int:
    streak = 0
    for row in reversed(rows):
        if predicate(row):
            streak += 1
        else:
            break
    return streak


def _record_low_count(rows: Sequence[dict[str, Any]]) -> int:
    running_low: float | None = None
    count = 0
    for row in rows:
        close = float(row["close"])
        if running_low is None or close < running_low:
            if running_low is not None:
                count += 1
            running_low = close
    return count


def post_break_acceptance_features(
    minute_rows: Sequence[dict[str, Any]],
    low_break_ts: datetime,
    ts: datetime,
    midpoint: float,
    reference_low: float,
) -> dict[str, Any]:
    """Measure acceptance/chop using only rows available by ``ts``."""
    observed = [
        row
        for row in minute_rows
        if low_break_ts <= row["timestamp"] <= ts
    ]
    if not observed or observed[-1]["timestamp"] != ts:
        return {"post_break_status": "UNAVAILABLE"}

    closes = [float(row["close"]) for row in observed]
    below_midpoint = sum(close < midpoint for close in closes)
    below_low = sum(close < reference_low for close in closes)
    n = len(observed)

    first_close = closes[0]
    current_close = closes[-1]
    minutes_since = int((ts - low_break_ts).total_seconds() // 60)
    denominator = max(1, minutes_since)

    return {
        "post_break_status": "AVAILABLE",
        "minutes_since_low_break": minutes_since,
        "post_break_observation_count": n,
        "closes_below_midpoint_count": below_midpoint,
        "closes_below_midpoint_pct": 100.0 * below_midpoint / n,
        "closes_below_reference_low_count": below_low,
        "closes_below_reference_low_pct": 100.0 * below_low / n,
        "consecutive_closes_below_midpoint": _ending_streak(
            observed, lambda row: row["close"] < midpoint
        ),
        "consecutive_closes_below_reference_low": _ending_streak(
            observed, lambda row: row["close"] < reference_low
        ),
        "reference_low_cross_count": _count_level_crosses(
            observed, reference_low
        ),
        "new_close_low_count_since_break": _record_low_count(observed),
        "net_downside_progress_points": first_close - current_close,
        "downside_velocity_points_per_minute": (
            (first_close - current_close) / denominator
        ),
        "post_break_close_range_points": max(closes) - min(closes),
        "post_break_full_range_points": (
            max(float(row["high"]) for row in observed)
            - min(float(row["low"]) for row in observed)
        ),
        "maximum_rebound_from_low_close_points": (
            max(closes) - min(closes)
        ),
        "current_close": current_close,
    }


def volume_change_pct(
    current: float | None,
    baseline: float | None,
) -> float | None:
    if current is None or baseline is None or baseline == 0:
        return None
    return ((current / baseline) - 1.0) * 100.0


def attach_context(
    session_date: str,
    ts: datetime,
    evidence_idx: dict[tuple[str, datetime], dict[str, str]],
    atm_idx: dict[tuple[str, datetime], dict[str, str]],
) -> dict[str, Any]:
    evidence = evidence_idx.get((session_date, ts))
    atm = atm_idx.get((session_date, ts))
    atm_5m = atm_idx.get((session_date, ts - timedelta(minutes=5)))

    context: dict[str, Any] = {
        "context_status": "AVAILABLE" if evidence or atm else "UNAVAILABLE",
        "fixed_pcr": f(evidence.get("fixed_pcr")) if evidence else None,
        "moving_pcr": f(evidence.get("moving_pcr")) if evidence else None,
        "full_pcr": f(evidence.get("full_pcr")) if evidence else None,
        "fixed_pcr_change_1m": f(evidence.get("fixed_pcr_change_1m"))
        if evidence
        else None,
        "fixed_pcr_change_5m": f(evidence.get("fixed_pcr_change_5m"))
        if evidence
        else None,
        "fixed_pcr_change_15m": f(evidence.get("fixed_pcr_change_15m"))
        if evidence
        else None,
        "moving_pcr_change_5m": f(evidence.get("moving_pcr_change_5m"))
        if evidence
        else None,
        "moving_pcr_change_15m": f(evidence.get("moving_pcr_change_15m"))
        if evidence
        else None,
    }

    if atm:
        ce_volume = f(atm.get("ce_volume"))
        pe_volume = f(atm.get("pe_volume"))
        ce_volume_5m = f(atm_5m.get("ce_volume")) if atm_5m else None
        pe_volume_5m = f(atm_5m.get("pe_volume")) if atm_5m else None

        context.update(
            {
                "moving_atm": f(atm.get("moving_atm")),
                "strike": f(atm.get("strike")),
                "ce_instrument_key": (atm.get("ce_instrument_key") or "").strip()
                or None,
                "pe_instrument_key": (atm.get("pe_instrument_key") or "").strip()
                or None,
                "ce_close": f(atm.get("ce_close")),
                "pe_close": f(atm.get("pe_close")),
                "ce_open_interest": f(atm.get("ce_open_interest")),
                "pe_open_interest": f(atm.get("pe_open_interest")),
                "ce_volume": ce_volume,
                "pe_volume": pe_volume,
                "ce_volume_change_5m_pct": volume_change_pct(
                    ce_volume, ce_volume_5m
                ),
                "pe_volume_change_5m_pct": volume_change_pct(
                    pe_volume, pe_volume_5m
                ),
                "ce_5m_premium_change_pct": f(
                    atm.get("ce_5m_premium_change_pct")
                ),
                "ce_5m_oi_change_pct": f(atm.get("ce_5m_oi_change_pct")),
                "ce_5m_state": atm.get("ce_5m_state") or None,
                "pe_5m_premium_change_pct": f(
                    atm.get("pe_5m_premium_change_pct")
                ),
                "pe_5m_oi_change_pct": f(atm.get("pe_5m_oi_change_pct")),
                "pe_5m_state": atm.get("pe_5m_state") or None,
                "combined_5m": atm.get("combined_5m") or None,
                "ce_15m_premium_change_pct": f(
                    atm.get("ce_15m_premium_change_pct")
                ),
                "ce_15m_oi_change_pct": f(atm.get("ce_15m_oi_change_pct")),
                "ce_15m_state": atm.get("ce_15m_state") or None,
                "pe_15m_premium_change_pct": f(
                    atm.get("pe_15m_premium_change_pct")
                ),
                "pe_15m_oi_change_pct": f(atm.get("pe_15m_oi_change_pct")),
                "pe_15m_state": atm.get("pe_15m_state") or None,
                "combined_15m": atm.get("combined_15m") or None,
            }
        )
    else:
        context.update(
            {
                "moving_atm": None,
                "strike": None,
                "ce_instrument_key": None,
                "pe_instrument_key": None,
                "ce_close": None,
                "pe_close": None,
                "ce_open_interest": None,
                "pe_open_interest": None,
                "ce_volume": None,
                "pe_volume": None,
                "ce_volume_change_5m_pct": None,
                "pe_volume_change_5m_pct": None,
                "ce_5m_premium_change_pct": None,
                "ce_5m_oi_change_pct": None,
                "ce_5m_state": None,
                "pe_5m_premium_change_pct": None,
                "pe_5m_oi_change_pct": None,
                "pe_5m_state": None,
                "combined_5m": None,
                "ce_15m_premium_change_pct": None,
                "ce_15m_oi_change_pct": None,
                "ce_15m_state": None,
                "pe_15m_premium_change_pct": None,
                "pe_15m_oi_change_pct": None,
                "pe_15m_state": None,
                "combined_15m": None,
            }
        )
    return context


def side_of_midpoint(close: float, midpoint: float) -> str:
    if close < midpoint:
        return "BELOW"
    if close > midpoint:
        return "ABOVE"
    return "AT"


def count_midpoint_crosses(
    rows: Sequence[dict[str, Any]],
    start_ts: datetime,
    end_ts: datetime,
    midpoint: float,
) -> int:
    relevant = [
        row
        for row in rows
        if start_ts <= row["timestamp"] <= end_ts
    ]
    if not relevant:
        return 0

    previous: str | None = None
    crosses = 0
    for row in relevant:
        side = side_of_midpoint(row["close"], midpoint)
        if side == "AT":
            continue
        if previous is not None and side != previous:
            crosses += 1
        previous = side
    return crosses


def first_close_below(
    rows: Sequence[dict[str, Any]],
    start_after: datetime,
    level: float,
) -> datetime | None:
    for row in rows:
        if row["timestamp"] <= start_after:
            continue
        if row["close"] < level:
            return row["timestamp"]
    return None


def first_close_above(
    rows: Sequence[dict[str, Any]],
    start_after: datetime,
    level: float,
    end_at: datetime | None = None,
) -> datetime | None:
    for row in rows:
        if row["timestamp"] <= start_after:
            continue
        if end_at is not None and row["timestamp"] > end_at:
            break
        if row["close"] > level:
            return row["timestamp"]
    return None


def first_close_at_or_below(
    rows: Sequence[dict[str, Any]],
    start_at: datetime,
    level: float,
    end_at: datetime,
) -> datetime | None:
    for row in rows:
        if row["timestamp"] < start_at:
            continue
        if row["timestamp"] > end_at:
            break
        if row["close"] <= level:
            return row["timestamp"]
    return None


def _path_metrics(
    rows: Sequence[dict[str, Any]],
    midpoint: float,
    reference_low: float,
) -> dict[str, Any]:
    if not rows:
        return {
            "observation_count": 0,
            "acceptance_below_midpoint_pct": None,
            "acceptance_below_reference_low_pct": None,
            "midpoint_cross_count": 0,
            "reference_low_cross_count": 0,
            "new_close_low_count": 0,
            "close_range_points": None,
            "full_range_points": None,
            "net_downside_progress_points": None,
        }

    closes = [float(row["close"]) for row in rows]
    return {
        "observation_count": len(rows),
        "acceptance_below_midpoint_pct": (
            100.0 * sum(close < midpoint for close in closes) / len(closes)
        ),
        "acceptance_below_reference_low_pct": (
            100.0 * sum(close < reference_low for close in closes) / len(closes)
        ),
        "midpoint_cross_count": _count_level_crosses(rows, midpoint),
        "reference_low_cross_count": _count_level_crosses(
            rows, reference_low
        ),
        "new_close_low_count": _record_low_count(rows),
        "close_range_points": max(closes) - min(closes),
        "full_range_points": (
            max(float(row["high"]) for row in rows)
            - min(float(row["low"]) for row in rows)
        ),
        "net_downside_progress_points": closes[0] - closes[-1],
    }


def classify_outcome(
    minute_rows: Sequence[dict[str, Any]],
    low_break_ts: datetime,
    midpoint: float,
    reference_low: float,
    reference_range: float,
) -> dict[str, Any]:
    horizon_end = low_break_ts + timedelta(minutes=OUTCOME_HORIZON_MINUTES)
    continuation_points = max(
        MIN_CONTINUATION_POINTS,
        CONTINUATION_REFERENCE_RANGE_FRACTION * reference_range,
    )
    continuation_level = reference_low - continuation_points

    continuation_ts = first_close_at_or_below(
        minute_rows,
        low_break_ts,
        continuation_level,
        horizon_end,
    )
    reclaim_ts = first_close_above(
        minute_rows,
        low_break_ts,
        midpoint,
        horizon_end,
    )

    if continuation_ts is not None and (
        reclaim_ts is None or continuation_ts < reclaim_ts
    ):
        minutes = int((continuation_ts - low_break_ts).total_seconds() // 60)
        label = (
            "BREAK_AND_GO"
            if minutes <= BREAK_AND_GO_MAX_MINUTES
            else "BREAK_AND_BASE_THEN_GO"
        )
        path_shape = (
            "IMMEDIATE_CONTINUATION"
            if minutes <= BREAK_AND_GO_MAX_MINUTES
            else "DELAYED_CONTINUATION"
        )
        resolution_ts = continuation_ts
    elif reclaim_ts is not None and (
        continuation_ts is None or reclaim_ts <= continuation_ts
    ):
        label = "FALSE_BREAK_RECLAIM"
        path_shape = "RECLAIM"
        minutes = None
        resolution_ts = reclaim_ts
    else:
        label = "SIDEWAYS_NO_CONTINUATION"
        path_shape = "UNRESOLVED_WITHIN_30M"
        minutes = None
        resolution_ts = horizon_end

    observed = [
        row
        for row in minute_rows
        if low_break_ts <= row["timestamp"] <= horizon_end
    ]
    pre_resolution = [
        row
        for row in minute_rows
        if low_break_ts <= row["timestamp"] <= resolution_ts
    ]
    min_close = min((row["close"] for row in observed), default=None)
    max_close = max((row["close"] for row in observed), default=None)

    return {
        "outcome_label": label,
        "outcome_path_shape": path_shape,
        "continuation_threshold_points": continuation_points,
        "continuation_level": continuation_level,
        "continuation_timestamp": continuation_ts.isoformat()
        if continuation_ts
        else None,
        "minutes_to_continuation": minutes,
        "midpoint_reclaim_timestamp": reclaim_ts.isoformat()
        if reclaim_ts
        else None,
        "minimum_close_within_30m": min_close,
        "maximum_close_within_30m": max_close,
        "pre_resolution_path_metrics": _path_metrics(
            pre_resolution,
            midpoint,
            reference_low,
        ),
        "full_30m_path_metrics": _path_metrics(
            observed,
            midpoint,
            reference_low,
        ),
    }


def research_session(
    *,
    block: str,
    session_date: str,
    minute_rows: Sequence[dict[str, Any]],
    evidence_idx: dict[tuple[str, datetime], dict[str, str]],
    atm_idx: dict[tuple[str, datetime], dict[str, str]],
) -> dict[str, Any]:
    bars = aggregate_5m(minute_rows)
    reference = select_reference_red_bar(bars)
    if reference is None:
        return {
            "block": block,
            "session_date": session_date,
            "status": "NO_REFERENCE_RED_CANDLE",
            "outcome_label": "NO_REFERENCE_RED_CANDLE",
        }

    high = reference["high"]
    low = reference["low"]
    midpoint = (high + low) / 2.0
    ref_range = high - low

    midpoint_break_ts = first_close_below(
        minute_rows,
        reference["end"],
        midpoint,
    )
    base = {
        "block": block,
        "session_date": session_date,
        "status": "AVAILABLE",
        "reference_start": reference["start"].isoformat(),
        "reference_end": reference["end"].isoformat(),
        "reference_open": reference["open"],
        "reference_high": high,
        "reference_low": low,
        "reference_close": reference["close"],
        "reference_range": ref_range,
        "reference_midpoint": midpoint,
        "reference_midpoint_formula": "(HIGH + LOW) / 2",
        "midpoint_break_timestamp": midpoint_break_ts.isoformat()
        if midpoint_break_ts
        else None,
    }
    if midpoint_break_ts is None:
        return {
            **base,
            "low_break_timestamp": None,
            "outcome_label": "NO_MIDPOINT_BREAK",
            "evidence_snapshots": [],
        }

    low_break_ts = first_close_below(
        minute_rows,
        midpoint_break_ts - timedelta(minutes=1),
        low,
    )
    if low_break_ts is None:
        reclaim_ts = first_close_above(
            minute_rows,
            midpoint_break_ts,
            midpoint,
        )
        return {
            **base,
            "low_break_timestamp": None,
            "midpoint_reclaim_timestamp": reclaim_ts.isoformat()
            if reclaim_ts
            else None,
            "outcome_label": "NO_LOW_BREAK",
            "evidence_snapshots": [],
        }

    row_idx = exact_row_index(minute_rows)
    snapshots: list[dict[str, Any]] = []

    for offset in EVIDENCE_OFFSETS_MINUTES:
        ts = low_break_ts + timedelta(minutes=offset)
        crosses = count_midpoint_crosses(
            minute_rows,
            midpoint_break_ts,
            ts,
            midpoint,
        )
        snapshot = {
            "offset_minutes": offset,
            "timestamp": ts.isoformat(),
            "feature_cutoff_timestamp": ts.isoformat(),
            "future_outcome_fields_used_as_features": False,
            **spot_features(
                minute_rows,
                row_idx,
                ts,
                midpoint,
                low,
                crosses,
            ),
            **post_break_acceptance_features(
                minute_rows,
                low_break_ts,
                ts,
                midpoint,
                low,
            ),
            **attach_context(
                session_date,
                ts,
                evidence_idx,
                atm_idx,
            ),
        }
        snapshots.append(snapshot)

    outcome = classify_outcome(
        minute_rows,
        low_break_ts,
        midpoint,
        low,
        ref_range,
    )

    return {
        **base,
        "low_break_timestamp": low_break_ts.isoformat(),
        "minutes_midpoint_to_low_break": int(
            (low_break_ts - midpoint_break_ts).total_seconds() // 60
        ),
        "midpoint_cross_count_30m": count_midpoint_crosses(
            minute_rows,
            midpoint_break_ts,
            low_break_ts + timedelta(minutes=OUTCOME_HORIZON_MINUTES),
            midpoint,
        ),
        "evidence_snapshots": snapshots,
        **outcome,
    }


def summarize_sessions(
    sessions: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    for row in sessions:
        counts[str(row.get("outcome_label", "UNAVAILABLE"))] += 1
    return {
        "session_count": len(sessions),
        "outcome_counts": dict(sorted(counts.items())),
        "midpoint_break_count": sum(
            row.get("midpoint_break_timestamp") is not None for row in sessions
        ),
        "low_break_count": sum(
            row.get("low_break_timestamp") is not None for row in sessions
        ),
        "reclaim_count": sum(
            row.get("midpoint_reclaim_timestamp") is not None for row in sessions
        ),
    }


def flatten_snapshot_rows(
    sessions: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for session in sessions:
        for snapshot in session.get("evidence_snapshots", []):
            rows.append(
                {
                    "block": session["block"],
                    "session_date": session["session_date"],
                    "outcome_label": session["outcome_label"],
                    "reference_start": session["reference_start"],
                    "reference_midpoint": session["reference_midpoint"],
                    "reference_low": session["reference_low"],
                    "midpoint_break_timestamp": session[
                        "midpoint_break_timestamp"
                    ],
                    "low_break_timestamp": session["low_break_timestamp"],
                    "midpoint_reclaim_timestamp": session.get(
                        "midpoint_reclaim_timestamp"
                    ),
                    **snapshot,
                }
            )
    return rows


def write_flat_csv(
    sessions: Sequence[dict[str, Any]], path: Path
) -> int:
    rows = flatten_snapshot_rows(sessions)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0

    preferred = [
        "block",
        "session_date",
        "outcome_label",
        "offset_minutes",
        "timestamp",
        "reference_start",
        "reference_midpoint",
        "reference_low",
        "midpoint_break_timestamp",
        "low_break_timestamp",
        "midpoint_reclaim_timestamp",
    ]
    all_keys = set().union(*(row.keys() for row in rows))
    fieldnames = preferred + sorted(all_keys - set(preferred))

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def analyze_snapshot_separation(
    sessions: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Descriptive, outcome-grouped feature summaries.

    This does not select thresholds or promote a trading rule.
    """
    numeric_features = (
        "spot_momentum_1m",
        "spot_momentum_5m",
        "spot_momentum_15m",
        "ema_5_minus_ema_15",
        "ema_5_slope_3m",
        "realized_vol_15m",
        "distance_from_midpoint_points",
        "distance_from_reference_low_points",
        "midpoint_cross_count",
        "minutes_since_low_break",
        "closes_below_midpoint_pct",
        "closes_below_reference_low_pct",
        "consecutive_closes_below_midpoint",
        "consecutive_closes_below_reference_low",
        "reference_low_cross_count",
        "new_close_low_count_since_break",
        "net_downside_progress_points",
        "downside_velocity_points_per_minute",
        "post_break_close_range_points",
        "post_break_full_range_points",
        "maximum_rebound_from_low_close_points",
        "ce_5m_premium_change_pct",
        "ce_5m_oi_change_pct",
        "pe_5m_premium_change_pct",
        "pe_5m_oi_change_pct",
        "ce_volume_change_5m_pct",
        "pe_volume_change_5m_pct",
        "fixed_pcr_change_5m",
        "moving_pcr_change_5m",
    )

    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for session in sessions:
        outcome = session.get("outcome_label")
        for snapshot in session.get("evidence_snapshots", []):
            grouped[(int(snapshot["offset_minutes"]), str(outcome))].append(
                snapshot
            )

    output: dict[str, Any] = {}
    for (offset, outcome), snapshots in sorted(grouped.items()):
        offset_key = f"T_PLUS_{offset}" if offset else "T0"
        group_key = f"{offset_key}|{outcome}"
        feature_summary: dict[str, Any] = {}

        for feature in numeric_features:
            values = [
                float(v)
                for snapshot in snapshots
                if (v := snapshot.get(feature)) is not None
                and isinstance(v, (int, float))
                and math.isfinite(float(v))
            ]
            feature_summary[feature] = {
                "available_count": len(values),
                "mean": statistics.fmean(values) if values else None,
                "median": statistics.median(values) if values else None,
            }

        pe_states: dict[str, int] = defaultdict(int)
        ce_states: dict[str, int] = defaultdict(int)
        combined: dict[str, int] = defaultdict(int)
        for snapshot in snapshots:
            if snapshot.get("pe_5m_state"):
                pe_states[str(snapshot["pe_5m_state"])] += 1
            if snapshot.get("ce_5m_state"):
                ce_states[str(snapshot["ce_5m_state"])] += 1
            if snapshot.get("combined_5m"):
                combined[str(snapshot["combined_5m"])] += 1

        output[group_key] = {
            "snapshot_count": len(snapshots),
            "numeric_features": feature_summary,
            "pe_5m_state_counts": dict(sorted(pe_states.items())),
            "ce_5m_state_counts": dict(sorted(ce_states.items())),
            "combined_5m_counts": dict(sorted(combined.items())),
        }

    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Opening red-candle midpoint evidence research V1"
    )
    parser.add_argument(
        "--block",
        action="append",
        required=True,
        type=parse_block,
        help=(
            "NAME|UNDERLYING_1M_OHLC_CSV|EVIDENCE_CSV|POSITIONING_CSV"
        ),
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--csv-output", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    blocks: list[BlockInput] = args.block
    names = [b.name for b in blocks]

    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate blocks: {names}")
    if set(names) != ALLOWED_BLOCKS:
        raise ValueError(
            "V1 development research requires exactly "
            f"{sorted(ALLOWED_BLOCKS)}; got={sorted(names)}"
        )

    all_sessions: list[dict[str, Any]] = []
    block_summaries: dict[str, Any] = {}

    for block in blocks:
        underlying_rows = load_csv(block.underlying_path)
        evidence_rows = load_csv(block.evidence_path)
        positioning_rows = load_csv(block.positioning_path)

        require_columns(
            underlying_rows,
            {
                "session_date",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
            },
            block.underlying_path,
        )
        require_columns(
            evidence_rows,
            {
                "session_date",
                "timestamp",
                "fixed_pcr",
                "moving_pcr",
                "full_pcr",
                "fixed_pcr_change_5m",
                "moving_pcr_change_5m",
            },
            block.evidence_path,
        )
        require_columns(
            positioning_rows,
            {
                "session_date",
                "timestamp",
                "moving_atm",
                "strike",
                "strike_offset",
                "ce_instrument_key",
                "pe_instrument_key",
                "ce_close",
                "pe_close",
                "ce_open_interest",
                "pe_open_interest",
                "ce_volume",
                "pe_volume",
                "ce_5m_premium_change_pct",
                "ce_5m_oi_change_pct",
                "ce_5m_state",
                "pe_5m_premium_change_pct",
                "pe_5m_oi_change_pct",
                "pe_5m_state",
                "combined_5m",
            },
            block.positioning_path,
        )

        by_session = underlying_by_session(underlying_rows)
        evidence_idx = index_exact_rows(evidence_rows)
        atm_idx = positioning_atm_index(positioning_rows)

        block_sessions: list[dict[str, Any]] = []
        for session_date, minute_rows in sorted(by_session.items()):
            block_sessions.append(
                research_session(
                    block=block.name,
                    session_date=session_date,
                    minute_rows=minute_rows,
                    evidence_idx=evidence_idx,
                    atm_idx=atm_idx,
                )
            )

        all_sessions.extend(block_sessions)
        block_summaries[block.name] = summarize_sessions(block_sessions)

    payload = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "research_status": "DEVELOPMENT_STRUCTURE_AND_EVIDENCE_ANALYSIS",
        "development_blocks": sorted(names),
        "methodology": {
            "first_5m_candle_ignored": True,
            "reference_candle": "FIRST_COMPLETED_RED_5M_CANDLE_AFTER_09_20",
            "one_reference_candle_per_session": True,
            "midpoint_formula": "(HIGH + LOW) / 2",
            "midpoint_break_rule": "ONE_MINUTE_CLOSE_BELOW_ORIGINAL_MIDPOINT",
            "low_break_rule": "ONE_MINUTE_CLOSE_BELOW_REFERENCE_LOW",
            "midpoint_reclaim_rule": "ONE_MINUTE_CLOSE_ABOVE_ORIGINAL_MIDPOINT",
            "persistent_original_midpoint": True,
            "evidence_offsets_minutes": list(EVIDENCE_OFFSETS_MINUTES),
            "partial_price_history_retained": True,
            "post_break_acceptance_features": True,
            "post_break_chop_features": True,
            "outcome_path_metrics_recorded": True,
            "outcome_horizon_minutes": OUTCOME_HORIZON_MINUTES,
            "continuation_threshold_definition": (
                "reference_low - max(10 points, 0.50 * reference_range)"
            ),
            "break_and_go_max_minutes": BREAK_AND_GO_MAX_MINUTES,
        },
        "leakage_guard": {
            "future_outcome_used_as_feature": False,
            "future_return_feature_used": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "evidence_snapshots_use_exact_or_backward_data_only": True,
            "partial_history_features_use_only_available_backwards_data": True,
            "post_break_acceptance_features_use_only_data_at_or_before_snapshot": True,
            "pcr_used_as_trade_rule": False,
            "oi_used_as_trade_rule": False,
            "volume_used_as_trade_rule": False,
            "research_emits_trade_order": False,
        },
        "important_note": (
            "This version measures whether OI/premium/volume/PCR evidence "
            "separates continuation, sideways, and reclaim outcomes. It does "
            "not yet convert those features into a live TRADE/WAIT rule."
        ),
        "summary": summarize_sessions(all_sessions),
        "block_summaries": block_summaries,
        "descriptive_evidence_by_offset_and_outcome": (
            analyze_snapshot_separation(all_sessions)
        ),
        "sessions": all_sessions,
    }

    output = Path(args.output)
    csv_output = Path(args.csv_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    csv_rows = write_flat_csv(all_sessions, csv_output)

    print(
        json.dumps(
            {
                "status": payload["status"],
                "research_version": RESEARCH_VERSION,
                "session_count": payload["summary"]["session_count"],
                "midpoint_break_count": payload["summary"][
                    "midpoint_break_count"
                ],
                "low_break_count": payload["summary"]["low_break_count"],
                "reclaim_count": payload["summary"]["reclaim_count"],
                "outcome_counts": payload["summary"]["outcome_counts"],
                "evidence_snapshot_row_count": csv_rows,
                "block_summaries": block_summaries,
                "output": str(output),
                "csv_output": str(csv_output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
