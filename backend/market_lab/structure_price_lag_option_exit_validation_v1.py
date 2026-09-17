from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

MODEL = "STRUCTURE_PRICE_LAG_OPTION_EXIT_VALIDATION_V1"

POLICIES = {
    "TIME_15": {
        "initial_stop_pct": None,
        "breakeven_trigger_pct": None,
        "trail_activation_pct": None,
        "trail_distance_pct": None,
        "max_hold_minutes": 15,
    },
    "SL5_TIME15": {
        "initial_stop_pct": 5.0,
        "breakeven_trigger_pct": None,
        "trail_activation_pct": None,
        "trail_distance_pct": None,
        "max_hold_minutes": 15,
    },
    "SL5_BE5_TRAIL3_AFTER10_TIME15": {
        "initial_stop_pct": 5.0,
        "breakeven_trigger_pct": 5.0,
        "trail_activation_pct": 10.0,
        "trail_distance_pct": 3.0,
        "max_hold_minutes": 15,
    },
    "SL5_BE5_TRAIL3_AFTER10_TIME30": {
        "initial_stop_pct": 5.0,
        "breakeven_trigger_pct": 5.0,
        "trail_activation_pct": 10.0,
        "trail_distance_pct": 3.0,
        "max_hold_minutes": 30,
    },
}

ROUND_TRIP_COST_PCT_POINTS = 0.5


def _num(v):
    if v in (None, "", "NA"):
        return None
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _parse_ts(s):
    return datetime.fromisoformat(str(s))


def _split_spec(spec):
    if "|" not in spec:
        raise ValueError(f"Expected BLOCK|path, got: {spec}")
    block, path = spec.split("|", 1)
    return block, Path(path)


def _first(row, *keys):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def load_csvs(specs):
    out = {}
    for spec in specs:
        block, path = _split_spec(spec)
        with path.open(newline="") as f:
            out[block] = list(csv.DictReader(f))
    return out


def _index_ohlc(rows):
    by_key = defaultdict(dict)
    for r in rows:
        key = _first(r, "instrument_key", "option_instrument_key")
        ts = _first(r, "timestamp", "ts")
        if key and ts:
            by_key[str(key)][str(ts)] = r
    return by_key


def _pct(entry, price):
    if entry is None or price is None or entry <= 0:
        return None
    return (price / entry - 1.0) * 100.0


def _net(gross):
    return None if gross is None else gross - ROUND_TRIP_COST_PCT_POINTS


def _bar_values(row):
    return {
        "open": _num(row.get("open")),
        "high": _num(row.get("high")),
        "low": _num(row.get("low")),
        "close": _num(row.get("close")),
    }


def replay_policy(trade, idx, policy_id, policy):
    key = trade["instrument_key"]
    entry_ts = trade["entry_timestamp"]
    entry = _num(trade["entry_open"])
    if entry is None:
        return None

    stop_pct = policy["initial_stop_pct"]
    be_trigger = policy["breakeven_trigger_pct"]
    trail_activation = policy["trail_activation_pct"]
    trail_distance = policy["trail_distance_pct"]
    max_hold = policy["max_hold_minutes"]

    stop_price = None if stop_pct is None else entry * (1.0 - stop_pct / 100.0)
    be_armed = False
    trail_armed = False
    best_price = entry
    exit_price = None
    exit_ts = None
    exit_reason = None
    bars_seen = 0

    start = _parse_ts(entry_ts)

    for minute in range(1, max_hold + 1):
        ts = (start + timedelta(minutes=minute)).isoformat()
        row = idx.get(key, {}).get(ts)
        if row is None:
            continue

        bars_seen += 1
        bar = _bar_values(row)
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        if None in (o, h, l, c):
            continue

        # Stop active at start of bar.
        active_stop = stop_price
        if active_stop is not None:
            if o <= active_stop:
                exit_price = o
                exit_ts = ts
                exit_reason = "STOP_GAP"
                break
            if l <= active_stop:
                exit_price = active_stop
                exit_ts = ts
                exit_reason = "STOP_TOUCH"
                break

        # Observe current bar for later activation. New BE/trail applies next bar only.
        if h > best_price:
            best_price = h

        if be_trigger is not None and not be_armed:
            if _pct(entry, h) is not None and _pct(entry, h) >= be_trigger:
                be_armed = True

        if trail_activation is not None and not trail_armed:
            if _pct(entry, h) is not None and _pct(entry, h) >= trail_activation:
                trail_armed = True

        next_stop = stop_price

        if be_armed:
            next_stop = max(next_stop if next_stop is not None else -math.inf, entry)

        if trail_armed and trail_distance is not None:
            trail_stop = best_price * (1.0 - trail_distance / 100.0)
            next_stop = max(next_stop if next_stop is not None else -math.inf, trail_stop)

        if next_stop == -math.inf:
            next_stop = None
        stop_price = next_stop

    if exit_price is None:
        ts = (start + timedelta(minutes=max_hold)).isoformat()
        row = idx.get(key, {}).get(ts)
        if row is None:
            return {
                "policy_id": policy_id,
                "available": False,
                "issue": "NO_EXACT_TIME_EXIT_BAR",
                "bars_seen": bars_seen,
            }
        exit_price = _num(row.get("close"))
        if exit_price is None:
            return {
                "policy_id": policy_id,
                "available": False,
                "issue": "NO_EXACT_TIME_EXIT_CLOSE",
                "bars_seen": bars_seen,
            }
        exit_ts = ts
        exit_reason = "TIME_EXIT"

    gross = _pct(entry, exit_price)
    return {
        "policy_id": policy_id,
        "available": True,
        "entry_price": entry,
        "exit_price": exit_price,
        "exit_timestamp": exit_ts,
        "exit_reason": exit_reason,
        "gross_return_pct": gross,
        "net_return_pct": _net(gross),
        "bars_seen": bars_seen,
        "be_armed": be_armed,
        "trail_armed": trail_armed,
    }


def load_trades(path):
    with Path(path).open(newline="") as f:
        return list(csv.DictReader(f))


def build_results(trades, ohlc_by_block):
    idx_by_block = {b: _index_ohlc(rows) for b, rows in ohlc_by_block.items()}
    results = []

    for t in trades:
        block = t["block"]
        if block not in idx_by_block:
            continue
        for policy_id, policy in POLICIES.items():
            r = replay_policy(t, idx_by_block[block], policy_id, policy)
            base = {
                "event_id": int(t["event_id"]),
                "session_date": t["session_date"],
                "block": block,
                "direction": t["direction"],
                "price_lag_class": t["price_lag_class"],
                "option_side": t["option_side"],
                "strike": _num(t["strike"]),
                "instrument_key": t["instrument_key"],
                "entry_timestamp": t["entry_timestamp"],
                "entry_open": _num(t["entry_open"]),
            }
            if r is None:
                base.update({
                    "policy_id": policy_id,
                    "available": False,
                    "issue": "REPLAY_FAILED",
                })
            else:
                base.update(r)
            results.append(base)
    return results


def _vals(rows, key):
    out = []
    for r in rows:
        v = _num(r.get(key))
        if v is not None:
            out.append(v)
    return out


def _summary(rows):
    avail = [r for r in rows if r.get("available") is True]
    vals = _vals(avail, "net_return_pct")
    return {
        "candidate_count": len(rows),
        "available_count": len(avail),
        "positive_count": sum(v > 0 for v in vals),
        "positive_rate": None if not vals else sum(v > 0 for v in vals) / len(vals),
        "mean_net_pct": None if not vals else mean(vals),
        "median_net_pct": None if not vals else median(vals),
        "sum_net_pct_points": None if not vals else sum(vals),
        "profit_factor": None if not vals else (
            sum(v for v in vals if v > 0) /
            abs(sum(v for v in vals if v < 0))
            if any(v < 0 for v in vals) else None
        ),
        "average_winner_pct": (
            None if not [v for v in vals if v > 0]
            else mean([v for v in vals if v > 0])
        ),
        "average_loser_pct": (
            None if not [v for v in vals if v < 0]
            else mean([v for v in vals if v < 0])
        ),
        "best_net_pct": None if not vals else max(vals),
        "worst_net_pct": None if not vals else min(vals),
        "exit_reason_counts": {
            k: sum(r.get("exit_reason") == k for r in avail)
            for k in ("STOP_TOUCH", "STOP_GAP", "TIME_EXIT")
        },
        "be_armed_count": sum(r.get("be_armed") is True for r in avail),
        "trail_armed_count": sum(r.get("trail_armed") is True for r in avail),
    }


def _policy_report(results, policy_id):
    rows = [r for r in results if r["policy_id"] == policy_id]
    lag = [r for r in rows if r["price_lag_class"] == "SPOT_LAG"]
    moved = [r for r in rows if r["price_lag_class"] == "SPOT_ALREADY_MOVED"]
    bull = [r for r in rows if r["direction"] == "BULLISH"]
    bear = [r for r in rows if r["direction"] == "BEARISH"]

    return {
        "all": _summary(rows),
        "by_price_lag": {
            "SPOT_LAG": _summary(lag),
            "SPOT_ALREADY_MOVED": _summary(moved),
        },
        "by_direction": {
            "BULLISH": {
                "all": _summary(bull),
                "SPOT_LAG": _summary([r for r in bull if r["price_lag_class"] == "SPOT_LAG"]),
                "SPOT_ALREADY_MOVED": _summary([r for r in bull if r["price_lag_class"] == "SPOT_ALREADY_MOVED"]),
            },
            "BEARISH": {
                "all": _summary(bear),
                "SPOT_LAG": _summary([r for r in bear if r["price_lag_class"] == "SPOT_LAG"]),
                "SPOT_ALREADY_MOVED": _summary([r for r in bear if r["price_lag_class"] == "SPOT_ALREADY_MOVED"]),
            },
        },
    }


def build_report(results):
    return {
        "status": "PASS",
        "model": MODEL,
        "role": "EXIT_POLICY_VALIDATION_DESCRIPTIVE_ONLY",
        "strategy_logic_changed": False,
        "entry_logic_changed": False,
        "threshold_optimization": False,
        "entry_source": "STRUCTURE_PRICE_LAG_EXACT_OPTION_REPLAY_V1",
        "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
        "execution_semantics": {
            "intrabar_stop_resolution": "OPEN_GAP_THEN_LOW_TOUCH",
            "breakeven_and_trail_activation": "NEXT_BAR_ONLY",
            "time_exit": "EXACT_MINUTE_CLOSE",
            "nearest_time_fallback": False,
        },
        "policies": POLICIES,
        "research_questions": [
            "Can dynamic exit management improve realized exact-option economics without changing the signal?",
            "Does the existing SL5/BE5/trail3-after10 policy preserve more of observed MFE?",
            "Do SPOT_LAG trades respond differently to exit policy than SPOT_ALREADY_MOVED trades?",
            "Are bullish CE and bearish PE exit characteristics materially different?",
        ],
        "policy_summaries": {
            policy_id: _policy_report(results, policy_id)
            for policy_id in POLICIES
        },
        "results": results,
    }


def write_csv(rows, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        p.write_text("")
        return
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True)
    ap.add_argument("--option-ohlc", action="append", required=True)
    ap.add_argument("--results-csv", required=True)
    ap.add_argument("--summary-json", required=True)
    a = ap.parse_args(argv)

    trades = load_trades(a.trades)
    ohlc = load_csvs(a.option_ohlc)
    results = build_results(trades, ohlc)
    report = build_report(results)

    write_csv(results, a.results_csv)
    out = Path(a.summary_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
