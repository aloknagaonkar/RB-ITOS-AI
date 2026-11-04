from __future__ import annotations

"""
Controlled Arm D research:
MIDPOINT_5M_CLOSE_PLUS_OI_VWAP

This module does NOT modify frozen V1, Arm A, or Arm C.

Arm D rule
----------
1. Use an existing opening midpoint structural event.
2. Require its original-direction 1m boundary break to have occurred.
3. Wait for the FIRST fully completed 5-minute price candle AFTER that break.
4. RED / bearish: completed 5m close must be below the original RED midpoint.
   GREEN / bullish: completed 5m close must be above the original GREEN midpoint.
5. At that SAME 5m checkpoint:
      bearish = CE SHORT_BUILDUP + PE LONG_BUILDUP + FUT close < session VWAP
      bullish = CE LONG_BUILDUP + PE SHORT_BUILDUP + FUT close > session VWAP
6. Use exact moving ATM at that checkpoint. No nearest strike/time fallback.
7. Enter next-minute option OPEN.
8. Report passive net returns at 1/3/5/10/15m after 0.5 pp round-trip cost.

No T+3 features are used by Arm D.
No OOS E/F/G/H data is allowed.
Research only; no order emission.
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_ARM_D_5M_CLOSE_OI_VWAP_COMPARISON_V1"
ARM_D = "ARM_D_MIDPOINT_5M_CLOSE_PLUS_OI_VWAP"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
FORBIDDEN_BLOCKS = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}
HORIZONS = (1, 3, 5, 10, 15)
COST = 0.5


def parse_ts(v: str) -> datetime:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pick(row: dict[str, Any], *names: str) -> Any:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return None


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def validate_block(block: str) -> str:
    b = block.strip().upper()
    if b in FORBIDDEN_BLOCKS:
        raise ValueError(f"{b} is forbidden in Arm D development research")
    if b not in ALLOWED_BLOCKS:
        raise ValueError(f"Unsupported block {b}; allowed={sorted(ALLOWED_BLOCKS)}")
    return b


def parse_block_arg(v: str) -> tuple[str, Path]:
    parts = v.split("|", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected BLOCK|PATH")
    return validate_block(parts[0]), Path(parts[1])


def pct(entry: float, exit_: float) -> float:
    if entry <= 0:
        raise ValueError("entry must be positive")
    return ((exit_ / entry) - 1.0) * 100.0


def profit_factor(values: list[float]) -> float | None:
    gp = sum(x for x in values if x > 0)
    gl = abs(sum(x for x in values if x <= 0))
    return gp / gl if gl else None


def metric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0, "positive_count": 0, "win_rate_pct": None,
            "mean_pct": None, "median_pct": None, "sum_pct_points": None,
            "profit_factor": None,
        }
    winners = [x for x in values if x > 0]
    return {
        "count": len(values),
        "positive_count": len(winners),
        "win_rate_pct": 100.0 * len(winners) / len(values),
        "mean_pct": mean(values),
        "median_pct": median(values),
        "sum_pct_points": sum(values),
        "profit_factor": profit_factor(values),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = {
        "trade_count": len(rows),
        "direction_counts": dict(Counter(r["direction"] for r in rows)),
    }
    for h in HORIZONS:
        vals = [
            float(r["net_returns_pct"][f"{h}m"])
            for r in rows
            if r.get("entry_available")
            and r.get("net_returns_pct", {}).get(f"{h}m") is not None
        ]
        out[f"net_{h}m"] = metric_summary(vals)
    return out


def next_5m_boundary_after(ts: datetime) -> datetime:
    base = ts.replace(second=0, microsecond=0)
    minutes = (base.minute // 5) * 5
    boundary = base.replace(minute=minutes)
    if boundary <= ts:
        boundary += timedelta(minutes=5)
    return boundary


def candle_minutes_for_checkpoint(checkpoint: datetime) -> list[str]:
    # A checkpoint at 09:25 represents the fully completed 09:20..09:24 candle.
    start = checkpoint - timedelta(minutes=5)
    return [(start + timedelta(minutes=i)).isoformat() for i in range(5)]


def build_underlying(
    items: list[tuple[str, Path]]
) -> tuple[
    dict[tuple[str, str, str], dict[str, Any]],
    dict[str, set[str]],
]:
    idx: dict[tuple[str, str, str], dict[str, Any]] = {}
    session_blocks: dict[str, set[str]] = defaultdict(set)
    for block, path in items:
        validate_block(block)
        for r in load_csv(path):
            ts_raw = pick(r, "timestamp", "datetime", "time", "provider_timestamp")
            if not ts_raw:
                continue
            ts = parse_ts(str(ts_raw))
            session = str(pick(r, "session_date", "date") or ts.date().isoformat())
            idx[(block, session, ts.isoformat())] = {
                "open": num(pick(r, "open")),
                "high": num(pick(r, "high")),
                "low": num(pick(r, "low")),
                "close": num(pick(r, "close")),
            }
            session_blocks[session].add(block)
    return idx, session_blocks


def completed_5m_close(
    underlying: dict[tuple[str, str, str], dict[str, Any]],
    block: str,
    session: str,
    checkpoint: datetime,
) -> tuple[float | None, str | None]:
    keys = candle_minutes_for_checkpoint(checkpoint)
    rows = [underlying.get((block, session, k)) for k in keys]
    if any(r is None for r in rows):
        return None, "MISSING_1M_ROWS_FOR_COMPLETED_5M_CANDLE"
    if any(r.get("close") is None for r in rows if r):
        return None, "MISSING_CLOSE_FOR_COMPLETED_5M_CANDLE"
    return float(rows[-1]["close"]), None


def load_positioning(
    items: list[tuple[str, Path]]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    out = {}
    for block, path in items:
        validate_block(block)
        for r in load_csv(path):
            off = num(pick(r, "strike_offset", "offset"))
            if off is not None and abs(off) > 1e-9:
                continue
            ts_raw = pick(r, "timestamp", "provider_timestamp", "datetime", "time")
            if not ts_raw:
                continue
            ts = parse_ts(str(ts_raw))
            if ts.minute % 5 or ts.second or ts.microsecond:
                continue
            session = str(pick(r, "session_date", "date") or ts.date().isoformat())
            out[(block, session, ts.isoformat())] = {
                "ce_state": str(pick(r, "ce_5m_state", "ce_state") or ""),
                "pe_state": str(pick(r, "pe_5m_state", "pe_state") or ""),
                "moving_atm": num(pick(r, "moving_atm", "atm", "atm_strike", "strike")),
                "ce_instrument_key": pick(r, "ce_instrument_key"),
                "pe_instrument_key": pick(r, "pe_instrument_key"),
            }
    return out


def load_futures(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for r in load_csv(path):
        ts_raw = pick(r, "timestamp", "provider_timestamp", "datetime", "time")
        if not ts_raw:
            continue
        ts = parse_ts(str(ts_raw))
        session = str(pick(r, "session_date", "date") or ts.date().isoformat())
        out[(session, ts.isoformat())] = {
            "futures_close": num(pick(r, "futures_close", "close")),
            "futures_vwap": num(pick(r, "futures_vwap", "session_vwap", "vwap")),
        }
    return out


def load_option_ohlc(
    items: list[tuple[str, Path]]
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    out = {}
    for block, path in items:
        validate_block(block)
        for r in load_csv(path):
            ts_raw = pick(r, "timestamp", "provider_timestamp", "datetime", "time")
            instrument = pick(r, "instrument_key")
            if not ts_raw or not instrument:
                continue
            ts = parse_ts(str(ts_raw))
            session = str(pick(r, "session_date", "date") or ts.date().isoformat())
            out[(block, session, str(instrument), ts.isoformat())] = {
                "open": num(pick(r, "open")),
                "high": num(pick(r, "high")),
                "low": num(pick(r, "low")),
                "close": num(pick(r, "close")),
            }
    return out


def aligned(direction: str, p: dict[str, Any], f: dict[str, Any]) -> bool:
    ce, pe = p.get("ce_state"), p.get("pe_state")
    fc, fv = f.get("futures_close"), f.get("futures_vwap")
    if fc is None or fv is None:
        return False
    if direction == "BEARISH":
        return ce == "SHORT_BUILDUP" and pe == "LONG_BUILDUP" and fc < fv
    if direction == "BULLISH":
        return ce == "LONG_BUILDUP" and pe == "SHORT_BUILDUP" and fc > fv
    return False


def apply_economics(
    base: dict[str, Any],
    option: dict[tuple[str, str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    block = base["block"]
    session = base["session_date"]
    instrument = base["instrument_key"]
    signal_ts = parse_ts(base["signal_timestamp"])
    entry_ts = signal_ts + timedelta(minutes=1)
    entry = option.get((block, session, instrument, entry_ts.isoformat()))
    if not entry or entry.get("open") is None:
        return {**base, "entry_available": False,
                "issue": "NEXT_MINUTE_EXACT_OPTION_OPEN_UNAVAILABLE"}

    ep = float(entry["open"])
    net = {}
    for h in HORIZONS:
        row = option.get((
            block, session, instrument,
            (entry_ts + timedelta(minutes=h)).isoformat()
        ))
        net[f"{h}m"] = (
            None if not row or row.get("close") is None
            else pct(ep, float(row["close"])) - COST
        )

    path = [
        option.get((block, session, instrument,
                    (entry_ts + timedelta(minutes=i)).isoformat()))
        for i in range(15)
    ]
    full = all(r is not None for r in path)
    highs = [float(r["high"]) for r in path if r and r.get("high") is not None]
    lows = [float(r["low"]) for r in path if r and r.get("low") is not None]

    return {
        **base,
        "entry_available": True,
        "issue": None,
        "entry_timestamp": entry_ts.isoformat(),
        "entry_price": ep,
        "complete_15m_path": full,
        "net_returns_pct": net,
        "mfe_pct_15m": pct(ep, max(highs)) if highs else None,
        "mae_pct_15m": pct(ep, min(lows)) if lows else None,
    }


def events_from_framework(
    framework: dict[str, Any],
    session_blocks: dict[str, set[str]],
) -> list[dict[str, Any]]:
    events = framework.get("events")
    if not isinstance(events, list):
        raise ValueError("framework missing top-level events list")

    out = []
    for e in events:
        if not isinstance(e, dict):
            continue
        setup = str(e.get("setup_type") or "")
        if setup not in {"RED_BREAK", "GREEN_BREAK"}:
            continue
        session = str(e.get("session_date") or "")
        boundary_ts = e.get("boundary_break_timestamp")
        midpoint = num(e.get("reference_midpoint"))
        if not session or not boundary_ts or midpoint is None:
            continue

        block = str(e.get("block") or "").upper()
        if block:
            if block in FORBIDDEN_BLOCKS:
                continue
            if block not in ALLOWED_BLOCKS:
                continue
        else:
            candidates = sorted(session_blocks.get(session, set()))
            if len(candidates) != 1:
                raise ValueError(
                    f"Cannot uniquely infer block for {session}; candidates={candidates}"
                )
            block = candidates[0]

        out.append({
            "block": block,
            "session_date": session,
            "setup_type": setup,
            "direction": "BEARISH" if setup == "RED_BREAK" else "BULLISH",
            "reference_colour": e.get("reference_colour"),
            "reference_high": num(e.get("reference_high")),
            "reference_low": num(e.get("reference_low")),
            "reference_midpoint": midpoint,
            "boundary_break_timestamp": str(boundary_ts),
        })
    return out


def build_arm_d(
    events: list[dict[str, Any]],
    underlying: dict[tuple[str, str, str], dict[str, Any]],
    positioning: dict[tuple[str, str, str], dict[str, Any]],
    futures: dict[tuple[str, str], dict[str, Any]],
    option: dict[tuple[str, str, str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter]:
    trades = []
    diagnostics = []
    issues = Counter()

    for e in events:
        block, session = e["block"], e["session_date"]
        break_ts = parse_ts(e["boundary_break_timestamp"])
        checkpoint = next_5m_boundary_after(break_ts)
        close5, close_issue = completed_5m_close(
            underlying, block, session, checkpoint
        )
        diag = {
            **e,
            "first_completed_5m_checkpoint": checkpoint.isoformat(),
            "completed_5m_close": close5,
            "t3_used": False,
        }
        if close_issue:
            diag["decision"] = "UNAVAILABLE"
            diag["issue"] = close_issue
            diagnostics.append(diag)
            issues[close_issue] += 1
            continue

        midpoint = float(e["reference_midpoint"])
        price_ok = (
            close5 < midpoint if e["direction"] == "BEARISH"
            else close5 > midpoint
        )
        diag["midpoint_acceptance_pass"] = price_ok
        if not price_ok:
            diag["decision"] = "REJECT_5M_MIDPOINT_ACCEPTANCE"
            diagnostics.append(diag)
            continue

        p = positioning.get((block, session, checkpoint.isoformat()))
        f = futures.get((session, checkpoint.isoformat()))
        if not p:
            diag["decision"] = "UNAVAILABLE"
            diag["issue"] = "MISSING_POSITIONING_AT_5M_CHECKPOINT"
            diagnostics.append(diag)
            issues[diag["issue"]] += 1
            continue
        if not f:
            diag["decision"] = "UNAVAILABLE"
            diag["issue"] = "MISSING_FUTURES_VWAP_AT_5M_CHECKPOINT"
            diagnostics.append(diag)
            issues[diag["issue"]] += 1
            continue

        oi_vwap_ok = aligned(e["direction"], p, f)
        diag.update({
            "ce_state": p.get("ce_state"),
            "pe_state": p.get("pe_state"),
            "moving_atm": p.get("moving_atm"),
            "futures_close": f.get("futures_close"),
            "futures_vwap": f.get("futures_vwap"),
            "oi_vwap_alignment_pass": oi_vwap_ok,
        })
        if not oi_vwap_ok:
            diag["decision"] = "REJECT_OI_VWAP_ALIGNMENT"
            diagnostics.append(diag)
            continue

        side = "PE" if e["direction"] == "BEARISH" else "CE"
        instrument = p.get(
            "pe_instrument_key" if side == "PE" else "ce_instrument_key"
        )
        if not instrument:
            diag["decision"] = "UNAVAILABLE"
            diag["issue"] = "MISSING_EXACT_ATM_OPTION_INSTRUMENT"
            diagnostics.append(diag)
            issues[diag["issue"]] += 1
            continue

        base = {
            "arm": ARM_D,
            "block": block,
            "session_date": session,
            "setup_type": e["setup_type"],
            "direction": e["direction"],
            "option_side": side,
            "reference_midpoint": midpoint,
            "boundary_break_timestamp": e["boundary_break_timestamp"],
            "signal_timestamp": checkpoint.isoformat(),
            "completed_5m_close": close5,
            "instrument_key": str(instrument),
            "strike": p.get("moving_atm"),
            "ce_state": p.get("ce_state"),
            "pe_state": p.get("pe_state"),
            "futures_close": f.get("futures_close"),
            "futures_vwap": f.get("futures_vwap"),
        }
        trade = apply_economics(base, option)
        trades.append(trade)
        diag["decision"] = "ARM_D_SIGNAL"
        diag["instrument_key"] = str(instrument)
        diagnostics.append(diag)

    return trades, diagnostics, issues


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--existing-comparison", required=True)
    ap.add_argument("--framework", required=True)
    ap.add_argument("--underlying", action="append", required=True, type=parse_block_arg)
    ap.add_argument("--positioning", action="append", required=True, type=parse_block_arg)
    ap.add_argument("--option-ohlc", action="append", required=True, type=parse_block_arg)
    ap.add_argument("--futures-vwap", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    existing = load_json(Path(args.existing_comparison))
    framework = load_json(Path(args.framework))
    underlying, session_blocks = build_underlying(args.underlying)
    positioning = load_positioning(args.positioning)
    futures = load_futures(Path(args.futures_vwap))
    option = load_option_ohlc(args.option_ohlc)
    events = events_from_framework(framework, session_blocks)

    trades, diagnostics, issues = build_arm_d(
        events, underlying, positioning, futures, option
    )

    by_block = {
        b: summarize([r for r in trades if r["block"] == b])
        for b in sorted(ALLOWED_BLOCKS)
    }
    by_direction = {
        d: summarize([r for r in trades if r["direction"] == d])
        for d in ("BULLISH", "BEARISH")
    }

    doc = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "research_status": "DEVELOPMENT_CONTROLLED_COMPARISON_ONLY",
        "source_existing_comparison_version": existing.get("research_version"),
        "candidate_event_count": len(events),
        "rules": {
            "arm_d": ARM_D,
            "t3_used": False,
            "structural_prerequisite": "existing original-direction 1m boundary break",
            "price_confirmation": (
                "first fully completed 5m candle AFTER boundary break; "
                "RED requires close < original midpoint; GREEN requires close > original midpoint"
            ),
            "same_checkpoint_oi_vwap": True,
            "bearish_alignment": "CE SHORT_BUILDUP + PE LONG_BUILDUP + FUT close < session VWAP",
            "bullish_alignment": "CE LONG_BUILDUP + PE SHORT_BUILDUP + FUT close > session VWAP",
            "exact_atm_at_signal": True,
            "entry": "next-minute exact-option OPEN",
            "nearest_time_fallback": False,
            "nearest_strike_fallback": False,
            "round_trip_cost_pct_points": COST,
            "no_threshold_sweep": True,
            "no_stop_change": True,
        },
        "existing_arm_a": existing.get("arm_a"),
        "existing_arm_c": existing.get("arm_c"),
        "arm_d": {
            "summary": summarize(trades),
            "by_block": by_block,
            "by_direction": by_direction,
            "trades": trades,
        },
        "comparison": {
            "arm_a_trade_count": (existing.get("comparison") or {}).get("arm_a_trade_count"),
            "arm_c_trade_count": (existing.get("comparison") or {}).get("arm_c_trade_count"),
            "arm_d_trade_count": len(trades),
        },
        "diagnostic_counts": dict(Counter(d["decision"] for d in diagnostics)),
        "issue_counts": dict(issues),
        "diagnostics": diagnostics,
        "integrity": {
            "t3_features_used_by_arm_d": False,
            "future_outcome_used_for_candidate_selection": False,
            "oos_e_f_g_h_used": False,
            "existing_arm_a_or_c_modified": False,
            "paper_or_live_order_emission_allowed": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, allow_nan=False), encoding="utf-8")

    print(json.dumps({
        "research_version": RESEARCH_VERSION,
        "candidate_event_count": len(events),
        "comparison": doc["comparison"],
        "arm_d": doc["arm_d"]["summary"],
        "arm_d_by_direction": by_direction,
        "diagnostic_counts": doc["diagnostic_counts"],
        "issue_counts": doc["issue_counts"],
        "output": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
