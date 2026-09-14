from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

RESEARCH_VERSION = "MIDPOINT_V2_RED_MIDPOINT_STRUCTURAL_STOP_V1"
EXPECTED_STATE_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"
EXPECTED_ECONOMICS_VERSION = "MIDPOINT_V3_2_EXACT_OPTION_ECONOMICS_V1"
FROZEN_POLICY_ID = "SL5_BE5_TRAIL3_AFTER10_TIME15"

ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
SETUP_TYPE = "RED_BREAK"
DIRECTION = "BEARISH"
T3_STATE = "CONFIRM_CONTINUATION"
MAX_HOLD_MINUTES = 15
ROUND_TRIP_COST_PCT_POINTS = 0.5


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def parse_dt(v: str) -> datetime:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def ffloat(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def walk_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def first_existing(headers, names):
    lower = {h.lower(): h for h in headers}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    raise ValueError(f"missing one of {names}; available={headers}")


def optional_existing(headers, names):
    lower = {h.lower(): h for h in headers}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def parse_block_specs(specs, loader):
    out = {}
    for spec in specs:
        if "|" not in spec:
            raise ValueError("expected BLOCK|path.csv")
        block, raw = spec.split("|", 1)
        block = block.strip()
        if block not in ALLOWED_BLOCKS:
            raise ValueError(f"block {block!r} is not allowed")
        out[block] = loader(Path(raw.strip()))
    return out


def load_underlying(path: Path):
    out = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        headers = list(rd.fieldnames or [])
        ts_col = first_existing(headers, ("timestamp", "datetime", "time", "ts"))
        close_col = first_existing(headers, ("close", "c"))
        high_col = first_existing(headers, ("high", "h"))
        low_col = first_existing(headers, ("low", "l"))
        date_col = optional_existing(headers, ("session_date", "date", "trading_date"))
        for r in rd:
            raw = r.get(ts_col)
            if not raw:
                continue
            try:
                ts = parse_dt(raw)
            except ValueError:
                continue
            sd = str(r.get(date_col)) if date_col and r.get(date_col) else ts.date().isoformat()
            c, h, l = ffloat(r.get(close_col)), ffloat(r.get(high_col)), ffloat(r.get(low_col))
            if None in (c, h, l):
                continue
            out[(sd, ts.isoformat())] = {"close": c, "high": h, "low": l}
    return out


def load_option_ohlc(path: Path):
    out = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        headers = list(rd.fieldnames or [])
        ts_col = first_existing(headers, ("timestamp", "datetime", "time", "ts"))
        inst_col = first_existing(headers, ("instrument_key", "instrument", "instrument_token"))
        open_col = first_existing(headers, ("open", "o"))
        high_col = first_existing(headers, ("high", "h"))
        low_col = first_existing(headers, ("low", "l"))
        close_col = first_existing(headers, ("close", "c"))
        for r in rd:
            raw = r.get(ts_col)
            inst = r.get(inst_col)
            if not raw or not inst:
                continue
            try:
                ts = parse_dt(raw)
            except ValueError:
                continue
            vals = {
                "open": ffloat(r.get(open_col)),
                "high": ffloat(r.get(high_col)),
                "low": ffloat(r.get(low_col)),
                "close": ffloat(r.get(close_col)),
            }
            if any(v is None for v in vals.values()):
                continue
            out[(str(inst), ts.isoformat())] = vals
    return out


def event_key(r):
    return (
        str(r.get("block")),
        str(r.get("session_date")),
        str(r.get("setup_type")),
        str(r.get("direction")),
    )


def candidate_events(state):
    out = []
    for e in state.get("events") or []:
        if str(e.get("block")) not in ALLOWED_BLOCKS:
            continue
        if e.get("setup_type") != SETUP_TYPE:
            continue
        if e.get("direction") != DIRECTION:
            continue
        if e.get("t3_state") != T3_STATE:
            continue
        out.append(e)
    return out


def extract_framework_midpoints(doc):
    idx = {}
    for r in walk_dicts(doc):
        if r.get("setup_type") != SETUP_TYPE:
            continue
        if r.get("session_date") is None or r.get("reference_midpoint") is None:
            continue
        key = (str(r.get("session_date")), SETUP_TYPE)
        if key not in idx:
            idx[key] = {
                "reference_high": ffloat(r.get("reference_high")),
                "reference_low": ffloat(r.get("reference_low")),
                "reference_midpoint": ffloat(r.get("reference_midpoint")),
            }
    return idx


def extract_economics_rows(doc):
    out, seen = [], set()
    for r in walk_dicts(doc):
        if r.get("t3_state") != T3_STATE:
            continue
        if not all(r.get(k) is not None for k in (
            "block", "session_date", "setup_type", "direction",
            "entry_timestamp", "entry_price", "instrument_key"
        )):
            continue
        sig = event_key(r)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
    return out


def extract_frozen_exit_rows(doc):
    out = []
    seen = set()
    for r in walk_dicts(doc):
        if r.get("policy_id") != FROZEN_POLICY_ID:
            continue
        required = ("block", "session_date", "direction", "entry_timestamp",
                    "exit_timestamp", "exit_reason", "net_return_pct")
        if not all(r.get(k) is not None for k in required):
            continue
        sig = (
            str(r.get("block")),
            str(r.get("session_date")),
            str(r.get("direction")),
            str(r.get("entry_timestamp")),
        )
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
    return out


def replay_midpoint_stop(
    underlying_market,
    option_market,
    session_date: str,
    instrument_key: str,
    entry_timestamp: str,
    entry_price: float,
    midpoint: float,
):
    """
    Experimental arm:
      - no premium SL / BE / trailing
      - bearish structure remains valid while 1m underlying CLOSE <= RED midpoint
      - first 1m CLOSE > RED midpoint schedules exit at next-minute option OPEN
      - if no midpoint invalidation before the hard horizon, exit option at +15m CLOSE
      - costs remain 0.5 percentage points

    No wick-only invalidation.
    """
    entry_ts = parse_dt(entry_timestamp)

    option_bars = []
    invalidation = None

    for minute in range(MAX_HOLD_MINUTES + 1):
        ts = entry_ts + timedelta(minutes=minute)
        opt = option_market.get((instrument_key, ts.isoformat()))
        und = underlying_market.get((session_date, ts.isoformat()))
        if opt is None:
            return {"available": False, "issue": f"MISSING_OPTION_BAR_{minute}M"}
        if und is None:
            return {"available": False, "issue": f"MISSING_UNDERLYING_BAR_{minute}M"}

        option_bars.append((minute, ts, opt))

        # To keep max hold fixed at 15m, only invalidations through +14 can
        # produce a next-minute-open structural exit.
        if minute < MAX_HOLD_MINUTES and float(und["close"]) > midpoint:
            invalidation = {
                "timestamp": ts.isoformat(),
                "underlying_close": float(und["close"]),
                "minute": minute,
            }
            exit_ts = ts + timedelta(minutes=1)
            exit_bar = option_market.get((instrument_key, exit_ts.isoformat()))
            if exit_bar is None:
                return {"available": False, "issue": "MISSING_NEXT_MINUTE_OPTION_OPEN"}
            exit_price = float(exit_bar["open"])
            gross = (exit_price / entry_price - 1.0) * 100.0

            path_bars = option_bars + [(minute + 1, exit_ts, exit_bar)]
            highs = [float(x[2]["high"]) for x in path_bars]
            lows = [float(x[2]["low"]) for x in path_bars]
            mfe = (max(highs) / entry_price - 1.0) * 100.0
            mae = (min(lows) / entry_price - 1.0) * 100.0

            return {
                "available": True,
                "exit_reason": "MIDPOINT_CLOSE_RECLAIM_NEXT_OPEN",
                "exit_timestamp": exit_ts.isoformat(),
                "exit_price": exit_price,
                "gross_return_pct": gross,
                "net_return_pct": gross - ROUND_TRIP_COST_PCT_POINTS,
                "duration_minutes": minute + 1,
                "midpoint_invalidation": invalidation,
                "option_mfe_pct": mfe,
                "option_mae_pct": mae,
            }

    # No structural invalidation before horizon: hard time exit at +15 close.
    minute, ts, opt = option_bars[-1]
    exit_price = float(opt["close"])
    gross = (exit_price / entry_price - 1.0) * 100.0
    highs = [float(x[2]["high"]) for x in option_bars]
    lows = [float(x[2]["low"]) for x in option_bars]
    mfe = (max(highs) / entry_price - 1.0) * 100.0
    mae = (min(lows) / entry_price - 1.0) * 100.0

    return {
        "available": True,
        "exit_reason": "TIME15_NO_MIDPOINT_RECLAIM",
        "exit_timestamp": ts.isoformat(),
        "exit_price": exit_price,
        "gross_return_pct": gross,
        "net_return_pct": gross - ROUND_TRIP_COST_PCT_POINTS,
        "duration_minutes": MAX_HOLD_MINUTES,
        "midpoint_invalidation": None,
        "option_mfe_pct": mfe,
        "option_mae_pct": mae,
    }


def metric_summary(values):
    if not values:
        return {
            "trade_count": 0,
            "winner_count": 0,
            "win_rate_pct": None,
            "mean_net_pct": None,
            "median_net_pct": None,
            "sum_net_pct_points": None,
            "profit_factor": None,
            "average_winner_pct": None,
            "average_loser_pct": None,
            "best_trade_pct": None,
            "worst_trade_pct": None,
        }
    winners = [x for x in values if x > 0]
    losers = [x for x in values if x <= 0]
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    return {
        "trade_count": len(values),
        "winner_count": len(winners),
        "win_rate_pct": 100.0 * len(winners) / len(values),
        "mean_net_pct": mean(values),
        "median_net_pct": median(values),
        "sum_net_pct_points": sum(values),
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
        "average_winner_pct": mean(winners) if winners else None,
        "average_loser_pct": mean(losers) if losers else None,
        "best_trade_pct": max(values),
        "worst_trade_pct": min(values),
    }


def block_summaries(rows):
    out = {}
    for block in sorted(ALLOWED_BLOCKS):
        subset = [r for r in rows if r["block"] == block and r["midpoint_stop"].get("available")]
        if not subset:
            continue
        baseline = [float(r["frozen_v1"]["net_return_pct"]) for r in subset]
        midpoint = [float(r["midpoint_stop"]["net_return_pct"]) for r in subset]
        out[block] = {
            "frozen_v1": metric_summary(baseline),
            "midpoint_stop": metric_summary(midpoint),
            "delta_sum_net_pct_points": sum(midpoint) - sum(baseline),
            "delta_mean_net_pct": mean(midpoint) - mean(baseline),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--framework", required=True)
    ap.add_argument("--economics", required=True)
    ap.add_argument("--exit-research", required=True)
    ap.add_argument("--underlying", action="append", required=True)
    ap.add_argument("--option-ohlc", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    state = load_json(Path(args.state))
    framework = load_json(Path(args.framework))
    economics = load_json(Path(args.economics))
    exits = load_json(Path(args.exit_research))

    if state.get("research_version") != EXPECTED_STATE_VERSION:
        raise SystemExit(f"unexpected state version={state.get('research_version')!r}")
    if economics.get("research_version") != EXPECTED_ECONOMICS_VERSION:
        raise SystemExit(f"unexpected economics version={economics.get('research_version')!r}")

    underlying = parse_block_specs(args.underlying, load_underlying)
    option_ohlc = parse_block_specs(args.option_ohlc, load_option_ohlc)

    framework_idx = extract_framework_midpoints(framework)
    econ_idx = {event_key(r): r for r in extract_economics_rows(economics)}

    exit_idx = {}
    for r in extract_frozen_exit_rows(exits):
        exit_idx[(
            str(r["block"]),
            str(r["session_date"]),
            str(r["direction"]),
            str(r["entry_timestamp"]),
        )] = r

    rows = []
    issue_counts = Counter()

    for e in candidate_events(state):
        key = event_key(e)
        block = key[0]
        sd = key[1]
        econ = econ_idx.get(key)
        fw = framework_idx.get((sd, SETUP_TYPE))

        if econ is None:
            issue_counts["MISSING_EXACT_ECONOMICS"] += 1
            continue
        if fw is None or fw.get("reference_midpoint") is None:
            issue_counts["MISSING_REFERENCE_MIDPOINT"] += 1
            continue

        frozen = exit_idx.get((
            block, sd, DIRECTION, str(econ["entry_timestamp"])
        ))
        if frozen is None:
            issue_counts["MISSING_FROZEN_V1_EXIT"] += 1
            continue

        midpoint_result = replay_midpoint_stop(
            underlying.get(block, {}),
            option_ohlc.get(block, {}),
            sd,
            str(econ["instrument_key"]),
            str(econ["entry_timestamp"]),
            float(econ["entry_price"]),
            float(fw["reference_midpoint"]),
        )
        if not midpoint_result.get("available"):
            issue_counts[midpoint_result.get("issue", "UNKNOWN_MIDPOINT_REPLAY_ISSUE")] += 1

        rows.append({
            "block": block,
            "session_date": sd,
            "setup_type": SETUP_TYPE,
            "direction": DIRECTION,
            "reference_high": fw.get("reference_high"),
            "reference_low": fw.get("reference_low"),
            "reference_midpoint": fw.get("reference_midpoint"),
            "instrument_key": econ.get("instrument_key"),
            "entry_timestamp": econ.get("entry_timestamp"),
            "entry_price": econ.get("entry_price"),
            "frozen_v1": {
                "exit_timestamp": frozen.get("exit_timestamp"),
                "exit_reason": frozen.get("exit_reason"),
                "net_return_pct": frozen.get("net_return_pct"),
            },
            "midpoint_stop": midpoint_result,
            "delta_net_pct": (
                None if not midpoint_result.get("available")
                else float(midpoint_result["net_return_pct"]) - float(frozen["net_return_pct"])
            ),
        })

    available = [r for r in rows if r["midpoint_stop"].get("available")]
    baseline_returns = [float(r["frozen_v1"]["net_return_pct"]) for r in available]
    midpoint_returns = [float(r["midpoint_stop"]["net_return_pct"]) for r in available]

    initial_sl5_rows = [
        r for r in available
        if abs(float(r["frozen_v1"]["net_return_pct"]) + 5.5) < 1e-6
    ]
    initial_sl5_baseline = [float(r["frozen_v1"]["net_return_pct"]) for r in initial_sl5_rows]
    initial_sl5_midpoint = [float(r["midpoint_stop"]["net_return_pct"]) for r in initial_sl5_rows]

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "candidate_scope": {
            "blocks": sorted(ALLOWED_BLOCKS),
            "setup_type": SETUP_TYPE,
            "direction": DIRECTION,
            "t3_state": T3_STATE,
            "population_source": "LEAKAGE_SAFE_V3_2_CONFIRMED_EVENTS",
            "legacy_future_outcome_label_used": False,
        },
        "comparison": {
            "A_FROZEN_V1": {
                "policy_id": FROZEN_POLICY_ID,
                "description": "Frozen premium SL5 / BE5 / trail3-after10 / time15",
            },
            "B_RED_MIDPOINT_STRUCTURAL_STOP": {
                "premium_initial_sl_removed": True,
                "premium_breakeven_removed": True,
                "premium_trailing_removed": True,
                "structural_invalidation": "first 1m underlying CLOSE > original RED reference midpoint",
                "structural_exit_execution": "next-minute exact option OPEN",
                "wick_only_invalidation": False,
                "hard_time_exit_minutes": MAX_HOLD_MINUTES,
                "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
            },
        },
        "summary": {
            "candidate_event_count": len(candidate_events(state)),
            "joined_trade_count": len(rows),
            "midpoint_replay_available_count": len(available),
            "issue_counts": dict(issue_counts),
            "frozen_v1": metric_summary(baseline_returns),
            "midpoint_stop": metric_summary(midpoint_returns),
            "delta_sum_net_pct_points": (
                sum(midpoint_returns) - sum(baseline_returns)
                if midpoint_returns else None
            ),
            "delta_mean_net_pct": (
                mean(midpoint_returns) - mean(baseline_returns)
                if midpoint_returns else None
            ),
            "midpoint_exit_reason_counts": dict(Counter(
                r["midpoint_stop"]["exit_reason"] for r in available
            )),
            "mean_midpoint_option_mae_pct": mean(
                r["midpoint_stop"]["option_mae_pct"] for r in available
            ) if available else None,
            "median_midpoint_option_mae_pct": median(
                r["midpoint_stop"]["option_mae_pct"] for r in available
            ) if available else None,
        },
        "initial_sl5_subset": {
            "trade_count": len(initial_sl5_rows),
            "frozen_v1": metric_summary(initial_sl5_baseline),
            "midpoint_stop": metric_summary(initial_sl5_midpoint),
            "delta_sum_net_pct_points": (
                sum(initial_sl5_midpoint) - sum(initial_sl5_baseline)
                if initial_sl5_midpoint else None
            ),
            "improved_trade_count": sum(
                1 for r in initial_sl5_rows if r["delta_net_pct"] > 0
            ),
            "worsened_trade_count": sum(
                1 for r in initial_sl5_rows if r["delta_net_pct"] < 0
            ),
        },
        "block_summaries": block_summaries(available),
        "sep7_reference": next((r for r in rows if r["session_date"] == "2026-09-07"), None),
        "rows": rows,
        "integrity": {
            "v1_entries_unchanged": True,
            "v1_contracts_unchanged": True,
            "v1_baseline_exit_loaded_from_frozen_research": True,
            "midpoint_uses_original_red_reference": True,
            "underlying_close_only": True,
            "midpoint_exit_executes_next_option_open": True,
            "time15_preserved": True,
            "no_stop_threshold_sweep": True,
            "no_oi_filter_added": True,
            "no_entry_rule_changed": True,
            "oos_h_used": False,
            "e_f_g_used": False,
        },
        "governance": {
            "development_research_only": True,
            "v1_freeze_unchanged": True,
            "midpoint_stop_not_promoted": True,
            "fresh_oos_required_before_any_promotion": True,
            "paper_or_live_order_emission_allowed": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
