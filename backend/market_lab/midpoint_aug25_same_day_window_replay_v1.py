from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

RESEARCH_VERSION = "MIDPOINT_AUG25_SAME_DAY_WINDOW_REPLAY_V1"
SESSION_DATE = "2026-08-25"


def num(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except Exception:
        return None


def parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def pick(row: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def floor_5m(ts: datetime) -> datetime:
    return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)


def in_window(ts: datetime, start_hm: str, end_hm: str) -> bool:
    sh, sm = map(int, start_hm.split(":"))
    eh, em = map(int, end_hm.split(":"))
    start = ts.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = ts.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= ts <= end


def load_1m_ohlc(path: Path) -> list[dict[str, Any]]:
    out = []
    for r in load_csv(path):
        ts = parse_ts(pick(r, "timestamp", "datetime", "provider_timestamp", "time"))
        if not ts:
            continue
        session = str(pick(r, "session_date", "date") or ts.date().isoformat())
        if session != SESSION_DATE:
            continue
        out.append({
            "timestamp": ts,
            "open": num(pick(r, "open")),
            "high": num(pick(r, "high")),
            "low": num(pick(r, "low")),
            "close": num(pick(r, "close")),
            "volume": num(pick(r, "volume")),
        })
    out.sort(key=lambda x: x["timestamp"])
    return out


def aggregate_5m(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for r in rows:
        groups[floor_5m(r["timestamp"])].append(r)

    out = []
    for ts in sorted(groups):
        g = sorted(groups[ts], key=lambda x: x["timestamp"])
        o = g[0]["open"]
        c = g[-1]["close"]
        highs = [x["high"] for x in g if x["high"] is not None]
        lows = [x["low"] for x in g if x["low"] is not None]
        vols = [x["volume"] for x in g if x["volume"] is not None]
        if o is None or c is None or not highs or not lows:
            continue
        high = max(highs)
        low = min(lows)
        out.append({
            "timestamp": ts,
            "open": o,
            "high": high,
            "low": low,
            "close": c,
            "body_points": c - o,
            "range_points": high - low,
            "upper_wick_points": high - max(o, c),
            "lower_wick_points": min(o, c) - low,
            "volume": sum(vols) if vols else None,
        })
    return out


def load_futures_vwap(path: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for r in load_csv(path):
        ts = parse_ts(pick(r, "timestamp", "datetime", "provider_timestamp", "time"))
        if not ts or ts.date().isoformat() != SESSION_DATE:
            continue
        close = num(pick(r, "futures_close", "close"))
        vwap = num(pick(r, "futures_vwap", "session_vwap", "vwap"))
        if close is None or vwap is None:
            continue
        out[ts.isoformat()] = {
            "futures_close": close,
            "futures_vwap": vwap,
            "distance_points": close - vwap,
            "distance_pct": ((close - vwap) / vwap) * 100.0 if vwap else None,
        }
    return out


def latest_at_or_before(index: dict[str, dict[str, Any]], ts: datetime) -> dict[str, Any] | None:
    best_t = None
    best_v = None
    for k, v in index.items():
        kt = parse_ts(k)
        if kt and kt <= ts and (best_t is None or kt > best_t):
            best_t = kt
            best_v = v
    return best_v


def load_positioning(path: Path) -> list[dict[str, Any]]:
    out = []
    for r in load_csv(path):
        ts = parse_ts(pick(r, "timestamp", "datetime", "provider_timestamp", "time"))
        if not ts:
            continue
        session = str(pick(r, "session_date", "date") or ts.date().isoformat())
        if session != SESSION_DATE:
            continue
        off = num(pick(r, "strike_offset", "offset"))
        if off is not None and abs(off) > 1e-9:
            continue
        out.append({
            "timestamp": ts,
            "moving_atm": num(pick(r, "moving_atm", "atm", "atm_strike", "strike")),
            "ce_state": str(pick(r, "ce_5m_state", "ce_state") or ""),
            "pe_state": str(pick(r, "pe_5m_state", "pe_state") or ""),
            "ce_price_change_pct": num(pick(r, "ce_price_change_pct", "ce_change_pct")),
            "ce_oi_change_pct": num(pick(r, "ce_oi_change_pct")),
            "pe_price_change_pct": num(pick(r, "pe_price_change_pct", "pe_change_pct")),
            "pe_oi_change_pct": num(pick(r, "pe_oi_change_pct")),
        })
    out.sort(key=lambda x: x["timestamp"])
    return out


def latest_positioning(rows: list[dict[str, Any]], ts: datetime) -> dict[str, Any] | None:
    vals = [r for r in rows if r["timestamp"] <= ts]
    return vals[-1] if vals else None


def enrich_bars(bars, futures, positioning):
    out = []
    prev = None
    prev_dist = None
    prev_vwap = None

    for b in bars:
        close_ts = b["timestamp"] + timedelta(minutes=4)
        fut = latest_at_or_before(futures, close_ts)
        pos = latest_positioning(positioning, close_ts)

        close_change = None if prev is None else b["close"] - prev["close"]
        hh = None if prev is None else b["high"] > prev["high"]
        hl = None if prev is None else b["low"] > prev["low"]

        dist = fut.get("distance_points") if fut else None
        dist_change = None if dist is None or prev_dist is None else dist - prev_dist
        slope = None if not fut or prev_vwap is None else fut["futures_vwap"] - prev_vwap

        if b["body_points"] > 0:
            candle_direction = "GREEN"
        elif b["body_points"] < 0:
            candle_direction = "RED"
        else:
            candle_direction = "DOJI"

        if prev is None:
            structure_state = "START"
        elif hh and hl and close_change is not None and close_change > 0:
            structure_state = "BULLISH_PROGRESS"
        elif (hh is False) and (hl is False) and close_change is not None and close_change < 0:
            structure_state = "BEARISH_PROGRESS"
        elif close_change is not None and abs(close_change) <= max(1.0, b["range_points"] * 0.15):
            structure_state = "STALL"
        else:
            structure_state = "MIXED"

        out.append({
            **{k: (v.isoformat() if k == "timestamp" else v) for k, v in b.items()},
            "candle_direction": candle_direction,
            "close_change_points_vs_prev_5m": close_change,
            "higher_high": hh,
            "higher_low": hl,
            "structure_state": structure_state,
            "futures_close": fut.get("futures_close") if fut else None,
            "futures_vwap": fut.get("futures_vwap") if fut else None,
            "futures_vwap_distance_points": dist,
            "futures_vwap_distance_change_points": dist_change,
            "futures_vwap_slope_points_per_5m": slope,
            "futures_above_vwap": fut["futures_close"] > fut["futures_vwap"] if fut else None,
            "moving_atm": pos.get("moving_atm") if pos else None,
            "ce_state": pos.get("ce_state") if pos else None,
            "pe_state": pos.get("pe_state") if pos else None,
            "ce_price_change_pct": pos.get("ce_price_change_pct") if pos else None,
            "ce_oi_change_pct": pos.get("ce_oi_change_pct") if pos else None,
            "pe_price_change_pct": pos.get("pe_price_change_pct") if pos else None,
            "pe_oi_change_pct": pos.get("pe_oi_change_pct") if pos else None,
        })

        prev = b
        prev_dist = dist
        if fut:
            prev_vwap = fut["futures_vwap"]

    return out


def window_summary(rows):
    if not rows:
        return {"count": 0}
    dists = [r["futures_vwap_distance_points"] for r in rows if r["futures_vwap_distance_points"] is not None]
    dchg = [r["futures_vwap_distance_change_points"] for r in rows if r["futures_vwap_distance_change_points"] is not None]
    slopes = [r["futures_vwap_slope_points_per_5m"] for r in rows if r["futures_vwap_slope_points_per_5m"] is not None]
    return {
        "count": len(rows),
        "start_close": rows[0]["close"],
        "end_close": rows[-1]["close"],
        "net_close_change_points": rows[-1]["close"] - rows[0]["close"],
        "green_candles": sum(r["candle_direction"] == "GREEN" for r in rows),
        "red_candles": sum(r["candle_direction"] == "RED" for r in rows),
        "bullish_progress_candles": sum(r["structure_state"] == "BULLISH_PROGRESS" for r in rows),
        "stall_candles": sum(r["structure_state"] == "STALL" for r in rows),
        "start_vwap_distance_points": dists[0] if dists else None,
        "end_vwap_distance_points": dists[-1] if dists else None,
        "mean_vwap_distance_points": mean(dists) if dists else None,
        "positive_vwap_distance_expansion_count": sum(x > 0 for x in dchg),
        "negative_vwap_distance_expansion_count": sum(x < 0 for x in dchg),
        "mean_vwap_slope_points_per_5m": mean(slopes) if slopes else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--underlying", required=True)
    ap.add_argument("--futures-vwap", required=True)
    ap.add_argument("--positioning", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    one_min = load_1m_ohlc(Path(args.underlying))
    bars = aggregate_5m(one_min)
    futures = load_futures_vwap(Path(args.futures_vwap))
    positioning = load_positioning(Path(args.positioning))
    enriched = enrich_bars(bars, futures, positioning)

    early = [r for r in enriched if in_window(parse_ts(r["timestamp"]), "09:15", "09:55")]
    late = [r for r in enriched if in_window(parse_ts(r["timestamp"]), "13:40", "14:30")]

    out = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "session_date": SESSION_DATE,
        "windows": {
            "early_0915_0955": {"summary": window_summary(early), "bars": early},
            "late_1340_1430": {"summary": window_summary(late), "bars": late},
        },
        "integrity": {
            "strategy_rule_changed": False,
            "threshold_tuning_performed": False,
            "same_day_descriptive_replay_only": True,
            "paper_or_live_execution_allowed": False,
        },
    }

    p = Path(args.output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "research_version": RESEARCH_VERSION,
        "early_summary": out["windows"]["early_0915_0955"]["summary"],
        "late_summary": out["windows"]["late_1340_1430"]["summary"],
        "early_bars": early,
        "late_bars": late,
        "output": str(p),
    }, indent=2))


if __name__ == "__main__":
    main()
