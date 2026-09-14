from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_V2_OI_FUTURES_VWAP_CONFLUENCE_V1"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
STRONG_BULLISH = "STRONG_BULLISH"
STRONG_BEARISH = "STRONG_BEARISH"


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def walk_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def first(row, names):
    for n in names:
        if row.get(n) not in (None, ""):
            return row.get(n)
    return None


def metric_summary(values):
    values = [float(x) for x in values]
    if not values:
        return {
            "trade_count": 0, "winner_count": 0, "win_rate_pct": None,
            "mean_net_pct": None, "median_net_pct": None,
            "sum_net_pct_points": None, "profit_factor": None,
            "average_winner_pct": None, "average_loser_pct": None,
            "best_trade_pct": None, "worst_trade_pct": None,
        }
    wins = [x for x in values if x > 0]
    losses = [x for x in values if x <= 0]
    gp, gl = sum(wins), abs(sum(losses))
    return {
        "trade_count": len(values),
        "winner_count": len(wins),
        "win_rate_pct": 100.0 * len(wins) / len(values),
        "mean_net_pct": mean(values),
        "median_net_pct": median(values),
        "sum_net_pct_points": sum(values),
        "profit_factor": gp / gl if gl > 0 else None,
        "average_winner_pct": mean(wins) if wins else None,
        "average_loser_pct": mean(losses) if losses else None,
        "best_trade_pct": max(values),
        "worst_trade_pct": min(values),
    }


def load_futures_vwap(path: Path):
    idx = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        for r in rd:
            idx[(str(r["session_date"]), str(r["timestamp"]))] = {
                "close": float(r["close"]),
                "vwap": float(r["session_vwap"]),
                "instrument_key": r["instrument_key"],
                "expiry": r["expiry"],
            }
    return idx


def normalize_direction(value):
    s = str(value or "").upper()
    if s in {"BULLISH", "BUY_CE", "CE"}:
        return "BULLISH"
    if s in {"BEARISH", "BUY_PE", "PE"}:
        return "BEARISH"
    return None


def normalize_strong_oi(row):
    for name in (
        "t3_oi_direction", "oi_direction_t3", "oi_strength_direction",
        "oi_direction", "t3_oi_strength", "oi_strength",
    ):
        raw = row.get(name)
        if raw not in (None, ""):
            s = str(raw).upper()
            if "STRONG" in s and "BULL" in s:
                return STRONG_BULLISH
            if "STRONG" in s and "BEAR" in s:
                return STRONG_BEARISH

    ce = str(first(row, ("t3_ce_oi_state", "ce_oi_state", "ce_build_up", "ce_buildup")) or "").upper()
    pe = str(first(row, ("t3_pe_oi_state", "pe_oi_state", "pe_build_up", "pe_buildup")) or "").upper()

    if ce == "LONG_BUILDUP" and pe == "SHORT_BUILDUP":
        return STRONG_BULLISH
    if ce == "SHORT_BUILDUP" and pe == "LONG_BUILDUP":
        return STRONG_BEARISH
    return None


def event_identity(row):
    block = str(first(row, ("block", "dataset_block", "cohort")) or "")
    session_date = str(first(row, ("session_date", "date", "trading_date")) or "")
    direction = normalize_direction(first(row, ("direction", "signal_direction", "trade_direction")))
    ts = first(row, (
        "t3_timestamp", "decision_timestamp", "confirmation_timestamp",
        "signal_timestamp", "timestamp",
    ))
    return block, session_date, direction, str(ts or "")


def collect_events(doc):
    rows, seen = [], set()
    for r in walk_dicts(doc):
        block, sd, direction, ts = event_identity(r)
        if block not in ALLOWED_BLOCKS or not sd or direction is None or not ts:
            continue
        t3 = first(r, ("t3_state", "decision", "decision_state"))
        if t3 is not None and str(t3).upper() != "CONFIRM_CONTINUATION":
            continue
        key = (block, sd, direction, ts)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "block": block,
            "session_date": sd,
            "direction": direction,
            "decision_timestamp": ts,
            "strong_oi": normalize_strong_oi(r),
        })
    return rows


def collect_returns(doc):
    idx = {}
    for r in walk_dicts(doc):
        block = str(first(r, ("block", "dataset_block", "cohort")) or "")
        sd = str(first(r, ("session_date", "date", "trading_date")) or "")
        direction = normalize_direction(first(r, ("direction", "signal_direction", "trade_direction")))
        ts = first(r, (
            "t3_timestamp", "decision_timestamp", "confirmation_timestamp",
            "signal_timestamp",
        ))
        net = first(r, ("net_return_pct", "net_pct", "net_return"))
        if block in ALLOWED_BLOCKS and sd and direction and ts and net is not None:
            idx[(block, sd, direction, str(ts))] = float(net)
    return idx


def summarize_by_block(rows, predicate):
    out = {}
    for block in sorted(ALLOWED_BLOCKS):
        vals = [
            r["net_return_pct"]
            for r in rows
            if r["block"] == block and predicate(r)
        ]
        out[block] = metric_summary(vals)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--economics", required=True)
    ap.add_argument("--futures-vwap", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    events_doc = load_json(Path(args.events))
    economics_doc = load_json(Path(args.economics))
    fut = load_futures_vwap(Path(args.futures_vwap))

    events = collect_events(events_doc)
    returns = collect_returns(economics_doc)

    rows = []
    issues = Counter()

    for e in events:
        key = (e["block"], e["session_date"], e["direction"], e["decision_timestamp"])
        net = returns.get(key)
        if net is None:
            issues["MISSING_EXACT_OPTION_RETURN"] += 1
            continue

        f = fut.get((e["session_date"], e["decision_timestamp"]))
        if f is None:
            issues["MISSING_FUTURES_VWAP_AT_DECISION"] += 1
            continue

        vwap_aligned = (
            (e["direction"] == "BULLISH" and f["close"] > f["vwap"]) or
            (e["direction"] == "BEARISH" and f["close"] < f["vwap"])
        )
        strong_oi_aligned = (
            (e["direction"] == "BULLISH" and e["strong_oi"] == STRONG_BULLISH) or
            (e["direction"] == "BEARISH" and e["strong_oi"] == STRONG_BEARISH)
        )

        rows.append({
            **e,
            "net_return_pct": net,
            "futures_close": f["close"],
            "futures_vwap": f["vwap"],
            "futures_vwap_distance_points": f["close"] - f["vwap"],
            "futures_vwap_aligned": vwap_aligned,
            "strong_oi_aligned": strong_oi_aligned,
            "strong_oi_plus_vwap_aligned": strong_oi_aligned and vwap_aligned,
            "futures_instrument_key": f["instrument_key"],
            "futures_expiry": f["expiry"],
        })

    all_sel = lambda r: True
    oi_sel = lambda r: r["strong_oi_aligned"]
    both_sel = lambda r: r["strong_oi_plus_vwap_aligned"]

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "rules": {
            "trigger": "existing price-structure T+3 confirmation only",
            "oi_role": "confirmation only",
            "bullish_pass": "STRONG_BULLISH and NIFTY FUT close > prospective session VWAP",
            "bearish_pass": "STRONG_BEARISH and NIFTY FUT close < prospective session VWAP",
            "vwap_formula": "cumulative(((high+low+close)/3)*volume)/cumulative(volume)",
            "no_vwap_slope": True,
            "no_vwap_distance_filter": True,
            "no_stop_change": True,
            "no_entry_timing_change": True,
        },
        "summary": {
            "candidate_events_loaded": len(events),
            "joined_trade_count": len(rows),
            "issues": dict(issues),
            "all_confirmed": metric_summary([r["net_return_pct"] for r in rows]),
            "strong_oi_only": metric_summary([r["net_return_pct"] for r in rows if oi_sel(r)]),
            "strong_oi_plus_futures_vwap": metric_summary(
                [r["net_return_pct"] for r in rows if both_sel(r)]
            ),
            "counts": {
                "strong_oi_aligned": sum(1 for r in rows if oi_sel(r)),
                "vwap_aligned": sum(1 for r in rows if r["futures_vwap_aligned"]),
                "strong_oi_plus_vwap_aligned": sum(1 for r in rows if both_sel(r)),
            },
        },
        "block_summaries": {
            "all_confirmed": summarize_by_block(rows, all_sel),
            "strong_oi_only": summarize_by_block(rows, oi_sel),
            "strong_oi_plus_futures_vwap": summarize_by_block(rows, both_sel),
        },
        "sep7_reference": next(
            (r for r in rows if r["session_date"] == "2026-09-07"),
            None,
        ),
        "rows": rows,
        "governance": {
            "development_research_only": True,
            "allowed_blocks": sorted(ALLOWED_BLOCKS),
            "e_f_g_h_used": False,
            "v1_freeze_changed": False,
            "paper_or_live_order_emission_allowed": False,
            "fresh_oos_required_before_promotion": True,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
