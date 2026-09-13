"""Exact-option economics for frozen midpoint V3.2 confirmations.

This module does NOT tune or modify MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2.
It measures what happens to the exact ATM option after a T+3
CONFIRM_CONTINUATION decision.

Inputs
------
- Frozen V3.2 state-machine JSON.
- V2.2 diagnostics JSON, used only to recover the exact T+3 checkpoint timestamp.
- Per-block positioning CSV, used to freeze the exact ATM CE/PE contract at T+3.
- Per-block exact-instrument 1-minute option OHLC CSV.

Entry
-----
- BEARISH confirmation -> exact ATM PE.
- BULLISH confirmation -> exact ATM CE.
- Entry = exact next-minute OPEN after T+3.
- No nearest-strike fallback.
- No later-contract substitution.

Research outputs
----------------
- Gross/net returns at +1/+3/+5/+10/+15 minutes.
- 15-minute MFE/MAE.
- First-touch outcomes for:
  +5/-5, +5/-10, +10/-5, +10/-10.
- Segments by direction, block, OI quality, T+1 observation state,
  and primary outcome (BREAK_AND_GO / BASE_THEN_GO where present).

This is descriptive economics only. No P&L-based rule selection. No orders.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Sequence

RESEARCH_VERSION = "MIDPOINT_V3_2_EXACT_OPTION_ECONOMICS_V1"
STATE_MACHINE_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"
DIAGNOSTICS_VERSION = "MIDPOINT_FAILURE_DIAGNOSTICS_V2_2"

ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
HORIZONS = (1, 3, 5, 10, 15)
TARGET_STOP_PAIRS = ((5, 5), (5, 10), (10, 5), (10, 10))
ROUND_TRIP_COST_PCT_POINTS = 0.50

IST = timezone(timedelta(hours=5, minutes=30))

@dataclass(frozen=True)
class BlockInput:
    name: str
    positioning_path: Path
    option_ohlc_path: Path

def normalize_block(name: str) -> str:
    return name.strip().upper().replace("-", "_")

def parse_block(value: str) -> BlockInput:
    parts = value.split("|")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "--block must be NAME|POSITIONING_CSV|OPTION_OHLC_CSV"
        )
    name = normalize_block(parts[0])
    if name not in ALLOWED_BLOCKS:
        raise argparse.ArgumentTypeError(
            f"unsupported block {name}; allowed={sorted(ALLOWED_BLOCKS)}"
        )
    return BlockInput(name, Path(parts[1]), Path(parts[2]))

def load_json(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return x

def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

def f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None

def parse_dt(value: Any) -> datetime:
    if value is None:
        raise ValueError("timestamp is missing")
    text = str(value).strip()
    if not text:
        raise ValueError("timestamp is empty")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST).replace(second=0, microsecond=0)

def minute_iso(value: Any) -> str:
    return parse_dt(value).isoformat()

def validate_sources(state: dict[str, Any], diag: dict[str, Any]) -> None:
    if state.get("research_version") != STATE_MACHINE_VERSION:
        raise ValueError(
            f"state machine must be {STATE_MACHINE_VERSION}, "
            f"got {state.get('research_version')!r}"
        )
    if diag.get("research_version") != DIAGNOSTICS_VERSION:
        raise ValueError(
            f"diagnostics must be {DIAGNOSTICS_VERSION}, "
            f"got {diag.get('research_version')!r}"
        )
    for label, payload in (("state", state), ("diagnostics", diag)):
        guard = payload.get("leakage_guard") or {}
        if guard.get("oos_e_f_g_h_used") is not False:
            raise ValueError(f"{label} source does not prove E/F/G/H excluded")
        if guard.get("oos_h_used") is not False:
            raise ValueError(f"{label} source does not prove H excluded")

def event_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        normalize_block(str(row.get("block"))),
        str(row.get("session_date")),
        str(row.get("setup_type")),
        str(row.get("primary_outcome")),
    )

def checkpoint_timestamp(row: dict[str, Any]) -> datetime | None:
    """Read timestamp from known/likely schema aliases without inventing one."""
    aliases = (
        "checkpoint_timestamp",
        "timestamp",
        "checkpoint_at",
        "at",
        "observed_at",
        "snapshot_timestamp",
    )
    for key in aliases:
        if row.get(key):
            try:
                return parse_dt(row[key])
            except ValueError:
                pass
    # A nested source/snapshot object is tolerated if present.
    for parent in ("checkpoint", "snapshot", "source_snapshot"):
        obj = row.get(parent)
        if isinstance(obj, dict):
            for key in aliases:
                if obj.get(key):
                    try:
                        return parse_dt(obj[key])
                    except ValueError:
                        pass
    return None

def build_t3_timestamp_index(diag: dict[str, Any]) -> dict[tuple[Any, ...], datetime]:
    out = {}
    duplicates = set()
    for r in diag.get("rows", []):
        if int(r.get("checkpoint_minutes", -1)) != 3:
            continue
        key = event_key(r)
        ts = checkpoint_timestamp(r)
        if ts is None:
            continue
        if key in out and out[key] != ts:
            duplicates.add(key)
        else:
            out[key] = ts
    if duplicates:
        raise ValueError(
            f"conflicting T+3 timestamps for {len(duplicates)} event(s)"
        )
    return out

def option_side(direction: str) -> str:
    if direction == "BEARISH":
        return "PE"
    if direction == "BULLISH":
        return "CE"
    raise ValueError(f"unsupported direction {direction!r}")

def positioning_index(rows: Sequence[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    out = {}
    for r in rows:
        date = str(r.get("session_date") or "").strip()
        ts = r.get("timestamp")
        if not date or not ts:
            continue
        try:
            key = (date, minute_iso(ts))
        except ValueError:
            continue
        # Require moving ATM row itself, if strike_offset exists.
        offset = f(r.get("strike_offset"))
        if offset is not None and abs(offset) > 1e-9:
            continue
        if key in out:
            # Prefer explicit ATM row over duplicates only if unique; ambiguity is unsafe.
            raise ValueError(f"duplicate ATM positioning row: {key}")
        out[key] = r
    return out

def exact_atm_contract(
    positioning: dict[tuple[str, str], dict[str, str]],
    session_date: str,
    t3: datetime,
    side: str,
) -> dict[str, Any] | None:
    row = positioning.get((session_date, t3.isoformat()))
    if row is None:
        return None

    strike = f(row.get("moving_atm"))
    if strike is None:
        strike = f(row.get("strike"))
    if strike is None:
        return None

    key_name = "pe_instrument_key" if side == "PE" else "ce_instrument_key"
    instrument_key = str(row.get(key_name) or "").strip()
    if not instrument_key:
        return None

    return {
        "strike": strike,
        "instrument_key": instrument_key,
        "positioning_timestamp": t3.isoformat(),
    }

def option_ohlc_index(
    rows: Sequence[dict[str, str]],
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    out: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        date = str(r.get("session_date") or "").strip()
        instrument = str(r.get("instrument_key") or "").strip()
        ts = r.get("timestamp")
        if not date or not instrument or not ts:
            continue
        try:
            t = parse_dt(ts)
        except ValueError:
            continue
        out[(date, instrument)][t.isoformat()] = {
            "timestamp": t,
            "open": f(r.get("open")),
            "high": f(r.get("high")),
            "low": f(r.get("low")),
            "close": f(r.get("close")),
            "strike": f(r.get("strike")),
            "side": str(r.get("side") or "").strip(),
        }
    return out

def pct_return(entry: float, exit_price: float) -> float:
    if entry <= 0:
        raise ValueError("entry must be positive")
    return ((exit_price / entry) - 1.0) * 100.0

def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses == 0:
        return None
    return gains / losses

def first_touch(
    entry: float,
    candles: Sequence[dict[str, Any]],
    target_pct: float,
    stop_pct: float,
) -> str:
    target = entry * (1.0 + target_pct / 100.0)
    stop = entry * (1.0 - stop_pct / 100.0)
    for c in candles:
        hi = c.get("high")
        lo = c.get("low")
        if hi is None or lo is None:
            continue
        th = hi >= target
        sh = lo <= stop
        if th and sh:
            return "AMBIGUOUS_SAME_BAR"
        if th:
            return "TARGET_FIRST"
        if sh:
            return "STOP_FIRST"
    return "NEITHER_WITHIN_15M"

def outcome_family(primary_outcome: str) -> str:
    text = primary_outcome.upper()
    if "BASE_THEN_GO" in text:
        return "BASE_THEN_GO"
    if "BREAK_AND_GO" in text:
        return "BREAK_AND_GO"
    return "OTHER"

def build_trade(
    event: dict[str, Any],
    t3: datetime,
    pos_idx: dict[tuple[str, str], dict[str, str]],
    ohlc_idx: dict[tuple[str, str], dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    date = str(event["session_date"])
    direction = str(event["direction"])
    side = option_side(direction)
    contract = exact_atm_contract(pos_idx, date, t3, side)

    base = {
        "block": event["block"],
        "session_date": date,
        "direction": direction,
        "option_side": side,
        "setup_type": event.get("setup_type"),
        "primary_outcome": event.get("primary_outcome"),
        "outcome_family": outcome_family(str(event.get("primary_outcome") or "")),
        "t1_observation_state": event.get("t1_observation_state"),
        "t3_state": event.get("t3_state"),
        "t3_timestamp": t3.isoformat(),
        "oi_quality": (event.get("t3_score") or {}).get("oi_quality"),
        "exact_oi_transition_t1_to_t3": event.get("exact_oi_transition_t1_to_t3"),
        "instrument_available": contract is not None,
        "entry_available": False,
        "complete_15m_path": False,
        "issue": None,
    }

    if contract is None:
        base["issue"] = "EXACT_ATM_CONTRACT_UNAVAILABLE_AT_T3"
        return base

    base.update(contract)
    series = ohlc_idx.get((date, contract["instrument_key"]), {})

    entry_ts = t3 + timedelta(minutes=1)
    entry_candle = series.get(entry_ts.isoformat())
    if not entry_candle or entry_candle.get("open") is None:
        base["issue"] = "EXACT_NEXT_MINUTE_OPEN_UNAVAILABLE"
        return base

    entry = entry_candle["open"]
    if entry is None or entry <= 0:
        base["issue"] = "INVALID_ENTRY_OPEN"
        return base

    base["entry_available"] = True
    base["entry_timestamp"] = entry_ts.isoformat()
    base["entry_price"] = entry

    returns = {}
    for h in HORIZONS:
        c = series.get((entry_ts + timedelta(minutes=h)).isoformat())
        close = c.get("close") if c else None
        returns[f"{h}m"] = pct_return(entry, close) if close is not None else None

    path = []
    for i in range(15):
        c = series.get((entry_ts + timedelta(minutes=i)).isoformat())
        if c is None:
            break
        path.append(c)

    base["complete_15m_path"] = len(path) == 15
    if path:
        highs = [c["high"] for c in path if c.get("high") is not None]
        lows = [c["low"] for c in path if c.get("low") is not None]
        base["mfe_pct_15m"] = (
            pct_return(entry, max(highs)) if highs else None
        )
        base["mae_pct_15m"] = (
            pct_return(entry, min(lows)) if lows else None
        )
    else:
        base["mfe_pct_15m"] = None
        base["mae_pct_15m"] = None

    base["gross_returns_pct"] = returns
    base["net_returns_pct"] = {
        k: (v - ROUND_TRIP_COST_PCT_POINTS if v is not None else None)
        for k, v in returns.items()
    }

    target_stop = {}
    for target, stop in TARGET_STOP_PAIRS:
        key = f"TARGET_{target}_STOP_{stop}"
        target_stop[key] = first_touch(entry, path, target, stop)
    base["target_stop"] = target_stop

    return base

def metric_summary(rows: Sequence[dict[str, Any]], field: str, net: bool = False) -> dict[str, Any]:
    key = "net_returns_pct" if net else "gross_returns_pct"
    vals = [
        r.get(key, {}).get(field)
        for r in rows
        if r.get(key, {}).get(field) is not None
    ]
    if not vals:
        return {
            "available_count": 0, "positive_count": 0, "positive_pct": None,
            "mean_pct": None, "median_pct": None, "profit_factor": None,
        }
    positives = sum(v > 0 for v in vals)
    return {
        "available_count": len(vals),
        "positive_count": positives,
        "positive_pct": positives / len(vals) * 100.0,
        "mean_pct": sum(vals) / len(vals),
        "median_pct": median(vals),
        "profit_factor": profit_factor(vals),
    }

def path_metric(rows: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    vals = [r.get(field) for r in rows if r.get(field) is not None]
    if not vals:
        return {"available_count": 0, "mean_pct": None, "median_pct": None}
    return {
        "available_count": len(vals),
        "mean_pct": sum(vals) / len(vals),
        "median_pct": median(vals),
    }

def target_stop_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for target, stop in TARGET_STOP_PAIRS:
        key = f"TARGET_{target}_STOP_{stop}"
        vals = [
            r.get("target_stop", {}).get(key)
            for r in rows
            if r.get("target_stop", {}).get(key)
        ]
        counts = Counter(vals)
        decisive = counts["TARGET_FIRST"] + counts["STOP_FIRST"]
        out[key] = {
            "available_count": len(vals),
            "target_first": counts["TARGET_FIRST"],
            "stop_first": counts["STOP_FIRST"],
            "ambiguous_same_bar": counts["AMBIGUOUS_SAME_BAR"],
            "neither_within_15m": counts["NEITHER_WITHIN_15M"],
            "target_first_pct_of_decisive": (
                counts["TARGET_FIRST"] / decisive * 100.0 if decisive else None
            ),
        }
    return out

def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out = {
        "trade_candidate_count": len(rows),
        "instrument_available_count": sum(bool(r.get("instrument_available")) for r in rows),
        "entry_available_count": sum(bool(r.get("entry_available")) for r in rows),
        "complete_15m_path_count": sum(bool(r.get("complete_15m_path")) for r in rows),
        "mfe_15m": path_metric(rows, "mfe_pct_15m"),
        "mae_15m": path_metric(rows, "mae_pct_15m"),
        "target_stop": target_stop_summary(rows),
    }
    for h in HORIZONS:
        out[f"gross_return_{h}m"] = metric_summary(rows, f"{h}m", net=False)
        out[f"net_return_{h}m"] = metric_summary(rows, f"{h}m", net=True)
    return out

def segmented(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        value = str(r.get(field) or "UNAVAILABLE")
        groups[value].append(r)
    return {k: summarize(v) for k, v in sorted(groups.items())}

def analyze(
    state: dict[str, Any],
    diagnostics: dict[str, Any],
    blocks: Sequence[BlockInput],
) -> dict[str, Any]:
    validate_sources(state, diagnostics)

    block_names = {b.name for b in blocks}
    if block_names != ALLOWED_BLOCKS:
        raise ValueError(
            f"blocks must be exactly {sorted(ALLOWED_BLOCKS)}, got {sorted(block_names)}"
        )

    t3_index = build_t3_timestamp_index(diagnostics)

    block_data = {}
    for b in blocks:
        block_data[b.name] = {
            "positioning": positioning_index(load_csv(b.positioning_path)),
            "ohlc": option_ohlc_index(load_csv(b.option_ohlc_path)),
        }

    confirmed = [
        e for e in state.get("events", [])
        if e.get("t3_state") == "CONFIRM_CONTINUATION"
        and normalize_block(str(e.get("block"))) in ALLOWED_BLOCKS
    ]

    trades = []
    missing_t3 = 0
    for e in confirmed:
        key = event_key(e)
        t3 = t3_index.get(key)
        if t3 is None:
            missing_t3 += 1
            trades.append({
                "block": e.get("block"),
                "session_date": e.get("session_date"),
                "direction": e.get("direction"),
                "setup_type": e.get("setup_type"),
                "primary_outcome": e.get("primary_outcome"),
                "t1_observation_state": e.get("t1_observation_state"),
                "t3_state": e.get("t3_state"),
                "instrument_available": False,
                "entry_available": False,
                "complete_15m_path": False,
                "issue": "T3_TIMESTAMP_UNAVAILABLE_IN_DIAGNOSTICS",
            })
            continue

        name = normalize_block(str(e["block"]))
        trades.append(
            build_trade(
                e, t3,
                block_data[name]["positioning"],
                block_data[name]["ohlc"],
            )
        )

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "state_machine_version": STATE_MACHINE_VERSION,
        "entry_rule": "EXACT_NEXT_MINUTE_OPEN_AFTER_T3",
        "contract_rule": "EXACT_MOVING_ATM_AT_T3_NO_NEAREST_FALLBACK",
        "direction_contract_map": {"BEARISH": "PE", "BULLISH": "CE"},
        "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
        "confirmed_candidate_count": len(confirmed),
        "missing_t3_timestamp_count": missing_t3,
        "overall_summary": summarize(trades),
        "direction_summaries": {
            d: summarize([r for r in trades if r.get("direction") == d])
            for d in ("BEARISH", "BULLISH")
        },
        "block_summaries": {
            b: summarize([r for r in trades if normalize_block(str(r.get("block"))) == b])
            for b in ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D")
        },
        "segments": {
            "oi_quality": segmented(trades, "oi_quality"),
            "t1_observation_state": segmented(trades, "t1_observation_state"),
            "outcome_family": segmented(trades, "outcome_family"),
        },
        "leakage_guard": {
            "state_machine_rules_modified": False,
            "pnl_used_for_state_selection": False,
            "pnl_used_for_threshold_selection": False,
            "entry_rule_selected_from_pnl": False,
            "target_stop_pairs_descriptive_only": True,
            "oos_a_b_c_d_used_as_development_economics": True,
            "oos_e_f_g_h_used": False,
            "oos_h_used": False,
            "research_only": True,
            "research_emits_trade_order": False,
        },
        "trades": trades,
    }

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--state-machine", required=True)
    p.add_argument("--diagnostics", required=True)
    p.add_argument("--block", action="append", required=True, type=parse_block)
    p.add_argument("--output", required=True)
    a = p.parse_args()

    result = analyze(
        load_json(Path(a.state_machine)),
        load_json(Path(a.diagnostics)),
        a.block,
    )
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": result["status"],
        "research_version": result["research_version"],
        "confirmed_candidate_count": result["confirmed_candidate_count"],
        "missing_t3_timestamp_count": result["missing_t3_timestamp_count"],
        "overall_summary": result["overall_summary"],
        "direction_summaries": result["direction_summaries"],
        "block_summaries": result["block_summaries"],
        "leakage_guard": result["leakage_guard"],
        "output": str(out),
    }, indent=2))

if __name__ == "__main__":
    main()
