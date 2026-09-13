"""Exit-management research for frozen Midpoint V3.2 confirmations.

This module does NOT change the V3.2 entry classifier.

It replays the exact option contract already chosen by
MIDPOINT_V3_2_EXACT_OPTION_ECONOMICS_V1 and evaluates a small, pre-declared
family of exit policies.

Leakage discipline
------------------
- Entry selection remains frozen.
- Candidate exit policies are declared a priori in this module.
- TRAIN is used only to nominate a candidate policy.
- OOS_A/B/C/D are reported unchanged for validation.
- E/F/G/H are forbidden; H remains pristine.
- No live orders are emitted.

Execution convention
--------------------
- Entry is the economics module's exact next-minute OPEN after T+3.
- Active stop is checked against the current 1-minute bar.
- Gap-through stop exits at the bar OPEN.
- Otherwise a touched stop exits at the stop price.
- Trailing / breakeven updates are calculated only AFTER a bar completes and
  become active on the NEXT bar. This avoids same-bar lookahead.
- Time exit uses the close of the 15th replay bar.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict, Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Sequence

RESEARCH_VERSION = "MIDPOINT_V3_2_EXIT_MANAGEMENT_RESEARCH_V1"
ECON_VERSION = "MIDPOINT_V3_2_EXACT_OPTION_ECONOMICS_V1"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
ROUND_TRIP_COST_PCT_POINTS = 0.50
IST = timezone(timedelta(hours=5, minutes=30))

@dataclass(frozen=True)
class BlockInput:
    name: str
    option_ohlc_path: Path

@dataclass(frozen=True)
class Policy:
    policy_id: str
    initial_stop_pct: float | None
    breakeven_trigger_pct: float | None
    trail_activate_pct: float | None
    trail_distance_pct: float | None
    time_exit_minutes: int = 15

POLICIES = (
    Policy("TIME_15", None, None, None, None, 15),
    Policy("SL10_TIME15", 10.0, None, None, None, 15),
    Policy("SL5_TIME15", 5.0, None, None, None, 15),
    Policy("SL10_BE5_TRAIL5_AFTER10_TIME15", 10.0, 5.0, 10.0, 5.0, 15),
    Policy("SL10_TRAIL5_AFTER5_TIME15", 10.0, None, 5.0, 5.0, 15),
    Policy("SL5_BE5_TRAIL3_AFTER10_TIME15", 5.0, 5.0, 10.0, 3.0, 15),
)

def normalize_block(v: Any) -> str:
    return str(v).strip().upper().replace("-", "_")

def parse_block(value: str) -> BlockInput:
    parts = value.split("|")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("--block must be NAME|OPTION_OHLC_CSV")
    name = normalize_block(parts[0])
    if name not in ALLOWED_BLOCKS:
        raise argparse.ArgumentTypeError(f"unsupported block {name}")
    return BlockInput(name, Path(parts[1]))

def load_json(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise ValueError("JSON root must be object")
    return x

def f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None

def parse_dt(v: Any) -> datetime:
    text = str(v).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST).replace(second=0, microsecond=0)

def load_ohlc(path: Path) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    out: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    with path.open("r", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            date = str(r.get("session_date") or "").strip()
            instrument = str(r.get("instrument_key") or "").strip()
            ts = r.get("timestamp")
            if not date or not instrument or not ts:
                continue
            t = parse_dt(ts)
            out[(date, instrument)][t.isoformat()] = {
                "timestamp": t,
                "open": f(r.get("open")),
                "high": f(r.get("high")),
                "low": f(r.get("low")),
                "close": f(r.get("close")),
            }
    return out

def pct_return(entry: float, exit_price: float) -> float:
    return ((exit_price / entry) - 1.0) * 100.0

def replay_policy(
    *,
    entry: float,
    entry_ts: datetime,
    series: dict[str, dict[str, Any]],
    policy: Policy,
) -> dict[str, Any]:
    if entry <= 0:
        raise ValueError("entry must be positive")

    active_stop = (
        entry * (1.0 - policy.initial_stop_pct / 100.0)
        if policy.initial_stop_pct is not None
        else None
    )
    high_watermark = entry
    bars_seen = 0

    for i in range(policy.time_exit_minutes):
        ts = entry_ts + timedelta(minutes=i)
        bar = series.get(ts.isoformat())
        if bar is None:
            return {"status": "UNAVAILABLE", "reason": f"MISSING_BAR_{i}"}

        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        if None in (o, h, l, c):
            return {"status": "UNAVAILABLE", "reason": f"INCOMPLETE_BAR_{i}"}

        bars_seen += 1

        # Stop active from previous completed bar.
        if active_stop is not None:
            if o <= active_stop:
                exit_price = o
                return {
                    "status": "EXITED",
                    "exit_reason": "STOP_GAP",
                    "exit_timestamp": ts.isoformat(),
                    "exit_price": exit_price,
                    "gross_return_pct": pct_return(entry, exit_price),
                    "bars_seen": bars_seen,
                }
            if l <= active_stop:
                exit_price = active_stop
                return {
                    "status": "EXITED",
                    "exit_reason": "STOP_TOUCH",
                    "exit_timestamp": ts.isoformat(),
                    "exit_price": exit_price,
                    "gross_return_pct": pct_return(entry, exit_price),
                    "bars_seen": bars_seen,
                }

        # Completed-bar information only. Any new stop applies NEXT bar.
        high_watermark = max(high_watermark, h)
        excursion_pct = pct_return(entry, high_watermark)

        candidates = []
        if active_stop is not None:
            candidates.append(active_stop)

        if (
            policy.breakeven_trigger_pct is not None
            and excursion_pct >= policy.breakeven_trigger_pct
        ):
            candidates.append(entry)

        if (
            policy.trail_activate_pct is not None
            and policy.trail_distance_pct is not None
            and excursion_pct >= policy.trail_activate_pct
        ):
            candidates.append(
                high_watermark * (1.0 - policy.trail_distance_pct / 100.0)
            )

        if candidates:
            active_stop = max(candidates)

        if i == policy.time_exit_minutes - 1:
            return {
                "status": "EXITED",
                "exit_reason": "TIME_EXIT",
                "exit_timestamp": ts.isoformat(),
                "exit_price": c,
                "gross_return_pct": pct_return(entry, c),
                "bars_seen": bars_seen,
            }

    raise AssertionError("unreachable")

def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses == 0:
        return None
    return gains / losses

def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    vals = [r["net_return_pct"] for r in rows if r.get("status") == "EXITED"]
    gross = [r["gross_return_pct"] for r in rows if r.get("status") == "EXITED"]
    reasons = Counter(r.get("exit_reason") for r in rows if r.get("status") == "EXITED")
    if not vals:
        return {
            "candidate_count": len(rows),
            "realized_count": 0,
            "positive_count": 0,
            "positive_pct": None,
            "mean_net_pct": None,
            "median_net_pct": None,
            "net_profit_factor": None,
            "mean_gross_pct": None,
            "gross_profit_factor": None,
            "exit_reasons": dict(reasons),
        }
    return {
        "candidate_count": len(rows),
        "realized_count": len(vals),
        "positive_count": sum(v > 0 for v in vals),
        "positive_pct": sum(v > 0 for v in vals) / len(vals) * 100.0,
        "mean_net_pct": sum(vals) / len(vals),
        "median_net_pct": median(vals),
        "net_profit_factor": profit_factor(vals),
        "mean_gross_pct": sum(gross) / len(gross),
        "gross_profit_factor": profit_factor(gross),
        "best_net_pct": max(vals),
        "worst_net_pct": min(vals),
        "exit_reasons": dict(reasons),
    }

def policy_rank_key(summary: dict[str, Any]) -> tuple[float, float, float]:
    # TRAIN-only nomination. Prefer PF, then mean, then positive rate.
    pf = summary.get("net_profit_factor")
    mean = summary.get("mean_net_pct")
    pos = summary.get("positive_pct")
    return (
        pf if pf is not None else -1.0,
        mean if mean is not None else -1e9,
        pos if pos is not None else -1.0,
    )

def analyze(econ: dict[str, Any], blocks: Sequence[BlockInput]) -> dict[str, Any]:
    if econ.get("research_version") != ECON_VERSION:
        raise ValueError(f"expected {ECON_VERSION}")
    guard = econ.get("leakage_guard") or {}
    if guard.get("oos_e_f_g_h_used") is not False or guard.get("oos_h_used") is not False:
        raise ValueError("economics source leakage guard is not clean")

    names = {b.name for b in blocks}
    if names != ALLOWED_BLOCKS:
        raise ValueError(f"blocks must be exactly {sorted(ALLOWED_BLOCKS)}")

    ohlc = {b.name: load_ohlc(b.option_ohlc_path) for b in blocks}

    base_trades = [
        r for r in econ.get("trades", [])
        if r.get("entry_available")
        and r.get("instrument_key")
        and normalize_block(r.get("block")) in ALLOWED_BLOCKS
    ]

    policy_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for trade in base_trades:
        block = normalize_block(trade["block"])
        key = (str(trade["session_date"]), str(trade["instrument_key"]))
        series = ohlc[block].get(key, {})
        entry = float(trade["entry_price"])
        entry_ts = parse_dt(trade["entry_timestamp"])

        for policy in POLICIES:
            result = replay_policy(
                entry=entry,
                entry_ts=entry_ts,
                series=series,
                policy=policy,
            )
            row = {
                "policy_id": policy.policy_id,
                "block": block,
                "session_date": trade["session_date"],
                "direction": trade.get("direction"),
                "oi_quality": trade.get("oi_quality"),
                "t1_observation_state": trade.get("t1_observation_state"),
                "outcome_family": trade.get("outcome_family"),
                **result,
            }
            if result.get("status") == "EXITED":
                row["net_return_pct"] = (
                    result["gross_return_pct"] - ROUND_TRIP_COST_PCT_POINTS
                )
            policy_rows[policy.policy_id].append(row)

    summaries = {}
    for policy in POLICIES:
        rows = policy_rows[policy.policy_id]
        summaries[policy.policy_id] = {
            "overall": summarize(rows),
            "TRAIN": summarize([r for r in rows if r["block"] == "TRAIN"]),
            "OOS_A": summarize([r for r in rows if r["block"] == "OOS_A"]),
            "OOS_B": summarize([r for r in rows if r["block"] == "OOS_B"]),
            "OOS_C": summarize([r for r in rows if r["block"] == "OOS_C"]),
            "OOS_D": summarize([r for r in rows if r["block"] == "OOS_D"]),
            "BEARISH": summarize([r for r in rows if r["direction"] == "BEARISH"]),
            "BULLISH": summarize([r for r in rows if r["direction"] == "BULLISH"]),
        }

    ranked = sorted(
        POLICIES,
        key=lambda p: policy_rank_key(summaries[p.policy_id]["TRAIN"]),
        reverse=True,
    )
    nominated = ranked[0].policy_id if ranked else None

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_version": ECON_VERSION,
        "policy_definitions": [
            {
                "policy_id": p.policy_id,
                "initial_stop_pct": p.initial_stop_pct,
                "breakeven_trigger_pct": p.breakeven_trigger_pct,
                "trail_activate_pct": p.trail_activate_pct,
                "trail_distance_pct": p.trail_distance_pct,
                "time_exit_minutes": p.time_exit_minutes,
            }
            for p in POLICIES
        ],
        "execution_semantics": {
            "entry": "FROZEN_EXACT_NEXT_MINUTE_OPEN_FROM_ECONOMICS_V1",
            "stop_gap": "BAR_OPEN_IF_OPEN_BELOW_ACTIVE_STOP",
            "stop_touch": "ACTIVE_STOP_PRICE",
            "trailing_update": "AFTER_COMPLETED_BAR_ACTIVE_NEXT_BAR",
            "time_exit": "CLOSE_OF_15TH_REPLAY_BAR",
            "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
        },
        "train_only_nominated_policy": nominated,
        "train_policy_ranking": [p.policy_id for p in ranked],
        "policy_summaries": summaries,
        "leakage_guard": {
            "entry_state_machine_modified": False,
            "candidate_exit_policies_declared_before_oos_validation": True,
            "policy_nomination_uses_train_only": True,
            "oos_a_b_c_d_used_for_policy_nomination": False,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "research_only": True,
            "research_emits_trade_order": False,
        },
        "rows": [r for pid in policy_rows for r in policy_rows[pid]],
    }

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--economics", required=True)
    p.add_argument("--block", action="append", required=True, type=parse_block)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    result = analyze(load_json(Path(a.economics)), a.block)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": result["status"],
        "research_version": result["research_version"],
        "train_only_nominated_policy": result["train_only_nominated_policy"],
        "train_policy_ranking": result["train_policy_ranking"],
        "policy_summaries": result["policy_summaries"],
        "leakage_guard": result["leakage_guard"],
        "output": str(out),
    }, indent=2))

if __name__ == "__main__":
    main()
