from __future__ import annotations

"""
MIDPOINT_GLOBAL_SESSION_EXEMPLAR_ANALYSIS_V1

Purpose
-------
Analyze the complete development universe across TRAIN + OOS_A/B/C/D:
- 99 historical sessions
- 184 leakage-safe structural events
- both BULLISH and BEARISH families
- compare strong winners, weak winners, losers, and rejected/missed setups
- use Sep-07 as a historical exemplar and allow Sep-15 current-day as an optional external reference

This study is descriptive only:
- no rule changes
- no threshold tuning
- no promotion
- no OOS E/F/G/H
- no order emission
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_GLOBAL_SESSION_EXEMPLAR_ANALYSIS_V1"
ALLOWED_BLOCKS = {"TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"}
FORBIDDEN_BLOCKS = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}
HORIZONS = (1, 3, 5, 10, 15)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


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


def pct_change(a: float | None, b: float | None) -> float | None:
    if a in (None, 0) or b is None:
        return None
    return ((b / a) - 1.0) * 100.0


def metric(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0, "positive_count": 0, "win_rate_pct": None,
            "mean_pct": None, "median_pct": None, "sum_pct_points": None,
            "profit_factor": None,
        }
    pos = [x for x in values if x > 0]
    neg = [x for x in values if x < 0]
    gp = sum(pos)
    gl = abs(sum(neg))
    return {
        "count": len(values),
        "positive_count": len(pos),
        "win_rate_pct": 100.0 * len(pos) / len(values),
        "mean_pct": mean(values),
        "median_pct": median(values),
        "sum_pct_points": sum(values),
        "profit_factor": (gp / gl if gl else None),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = {
        "count": len(rows),
        "direction_counts": dict(Counter(r.get("direction") for r in rows)),
        "decision_counts": dict(Counter(r.get("decision_family") for r in rows)),
    }
    for h in HORIZONS:
        vals = [
            float((r.get("option_economics") or {}).get(f"net_{h}m_pct"))
            for r in rows
            if (r.get("option_economics") or {}).get(f"net_{h}m_pct") is not None
        ]
        out[f"net_{h}m"] = metric(vals)
    return out


def load_structural_events(doc: dict[str, Any]) -> list[dict[str, Any]]:
    events = doc.get("events")
    if not isinstance(events, list):
        raise ValueError("structural reconstruction missing top-level events list")
    out = []
    for e in events:
        block = str(e.get("block") or "")
        if block in FORBIDDEN_BLOCKS:
            continue
        if block not in ALLOWED_BLOCKS:
            continue
        session = str(e.get("session_date") or "")
        if not session:
            continue
        direction = str(e.get("direction") or "")
        if direction not in {"BULLISH", "BEARISH"}:
            continue
        out.append(dict(e))
    return out


def stable_feature_index(doc: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    out = {}
    for e in doc.get("events", []):
        if not isinstance(e, dict):
            continue
        block = str(e.get("block") or "")
        session = str(e.get("session_date") or "")
        setup = str(e.get("setup_type") or "")
        if block in ALLOWED_BLOCKS and session and setup:
            out[(block, session, setup)] = e
    return out


def arm_c_trade_index(doc: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    rows = doc.get("arm_c_trades")
    if not isinstance(rows, list):
        raise ValueError("controlled comparison missing top-level arm_c_trades")
    out = {}
    for r in rows:
        block = str(r.get("block") or "")
        session = str(r.get("session_date") or "")
        direction = str(r.get("direction") or "")
        signal = str(r.get("signal_timestamp") or "")
        if block in ALLOWED_BLOCKS and session and direction and signal:
            out[(block, session, signal)] = r
    return out


def all_option_trade_index(doc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = doc.get("trades")
    return rows if isinstance(rows, list) else []


def load_positioning(items: list[tuple[str, Path]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    out = {}
    for block, path in items:
        if block not in ALLOWED_BLOCKS:
            raise ValueError(block)
        for r in load_csv(path):
            ts = parse_ts(pick(r, "timestamp", "datetime", "provider_timestamp", "time"))
            if not ts:
                continue
            session = str(pick(r, "session_date", "date") or ts.date().isoformat())
            if ts.minute % 5 != 0 or ts.second != 0:
                continue
            off = num(pick(r, "strike_offset", "offset"))
            if off is not None and abs(off) > 1e-9:
                continue
            out[(block, session, ts.isoformat())] = {
                "moving_atm": num(pick(r, "moving_atm", "atm", "atm_strike", "strike")),
                "ce_state": str(pick(r, "ce_5m_state", "ce_state") or ""),
                "pe_state": str(pick(r, "pe_5m_state", "pe_state") or ""),
                "ce_premium": num(pick(r, "ce_premium", "ce_price")),
                "ce_oi": num(pick(r, "ce_oi")),
                "pe_premium": num(pick(r, "pe_premium", "pe_price")),
                "pe_oi": num(pick(r, "pe_oi")),
            }
    return out


def load_futures(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for r in load_csv(path):
        ts = parse_ts(pick(r, "timestamp", "datetime", "provider_timestamp", "time"))
        if not ts:
            continue
        session = str(pick(r, "session_date", "date") or ts.date().isoformat())
        out[(session, ts.isoformat())] = {
            "futures_close": num(pick(r, "futures_close", "close")),
            "futures_vwap": num(pick(r, "futures_vwap", "session_vwap", "vwap")),
        }
    return out


def latest_completed_5m(ts: datetime) -> datetime:
    minute = (ts.minute // 5) * 5
    return ts.replace(minute=minute, second=0, microsecond=0)


def decision_family(e: dict[str, Any]) -> str:
    t3 = str(e.get("t3_state") or "")
    final = str(e.get("v2_final_state") or e.get("final_state") or "")
    if final == "CONFIRM_BASE_THEN_GO":
        return "BASE_THEN_GO"
    if final == "CONFIRM_FAILED_BREAK_RECLAIM":
        return "FAILED_BREAK_RECLAIM"
    if t3 == "CONFIRM_CONTINUATION" or final == "CONFIRM_CONTINUATION":
        return "IMMEDIATE_CONTINUATION"
    if "CANCEL" in t3 or "CANCEL" in final:
        return "CANCEL"
    if "RECLAIM" in t3 or "RECLAIM" in final:
        return "RECLAIM"
    if "WAIT" in t3 or "WAIT" in final:
        return "WAIT"
    return final or t3 or "OTHER"


def extract_features(
    e: dict[str, Any],
    stable: dict[str, Any] | None,
    positioning: dict[tuple[str, str, str], dict[str, Any]],
    futures: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    block = str(e.get("block"))
    session = str(e.get("session_date"))
    direction = str(e.get("direction"))
    signal_raw = (
        e.get("absolute_confirmation_timestamp")
        or e.get("confirmation_timestamp")
        or e.get("t3_timestamp")
        or (stable or {}).get("t3_timestamp")
    )
    ts = parse_ts(signal_raw)
    cp = latest_completed_5m(ts) if ts else None
    p = positioning.get((block, session, cp.isoformat())) if cp else None
    f = futures.get((session, cp.isoformat())) if cp else None

    price_features = {}
    t3_score = (stable or {}).get("t3_score") or {}
    pf = (stable or {}).get("price_features") or {}
    if isinstance(pf, dict):
        price_features.update(pf)

    for key in [
        "acceptance_pct",
        "momentum_5m_directional",
        "progress_points",
        "giveback_from_best_checkpoint_points",
        "consecutive_closes",
        "velocity",
    ]:
        if key not in price_features:
            v = e.get(key)
            if v is not None:
                price_features[key] = v

    fv_dist = None
    fv_pct = None
    aligned = None
    if f and f.get("futures_close") is not None and f.get("futures_vwap") is not None:
        fc = float(f["futures_close"])
        vw = float(f["futures_vwap"])
        fv_dist = fc - vw
        fv_pct = (fv_dist / vw) * 100.0 if vw else None
        aligned = (
            direction == "BULLISH" and fc > vw
        ) or (
            direction == "BEARISH" and fc < vw
        )

    return {
        "signal_timestamp": ts.isoformat() if ts else None,
        "oi_vwap_checkpoint_timestamp": cp.isoformat() if cp else None,
        "price_features": price_features,
        "price_pass_count": t3_score.get("price_pass_count"),
        "price_pass_ratio": t3_score.get("price_pass_ratio"),
        "oi_quality": str((stable or {}).get("oi_quality") or t3_score.get("oi_quality") or ""),
        "oi": p,
        "futures": {
            **(f or {}),
            "distance_points": fv_dist,
            "distance_pct": fv_pct,
            "aligned": aligned,
        } if f else None,
    }


def attach_option_economics(
    row: dict[str, Any],
    arm_c_idx: dict[tuple[str, str, str], dict[str, Any]],
    all_option_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    signal = row.get("signal_timestamp")
    block = row["block"]
    session = row["session_date"]
    direction = row["direction"]

    tr = None
    if signal:
        tr = arm_c_idx.get((block, session, signal))

    if tr is None:
        # descriptive fallback: exact same block/session/direction from canonical option economics
        candidates = [
            x for x in all_option_rows
            if str(x.get("block")) == block
            and str(x.get("session_date")) == session
            and str(x.get("direction")) == direction
        ]
        if len(candidates) == 1:
            tr = candidates[0]

    if tr is None:
        return {**row, "option_economics": None}

    nr = tr.get("net_returns_pct") or {}
    return {
        **row,
        "option_economics": {
            "option_side": tr.get("option_side"),
            "strike": tr.get("strike"),
            "instrument_key": tr.get("instrument_key"),
            "entry_timestamp": tr.get("entry_timestamp"),
            "entry_price": tr.get("entry_price"),
            **{f"net_{h}m_pct": nr.get(f"{h}m") for h in HORIZONS},
            "mfe_pct_15m": tr.get("mfe_pct_15m"),
            "mae_pct_15m": tr.get("mae_pct_15m"),
        },
    }


def quality_bucket(r: dict[str, Any]) -> str:
    econ = r.get("option_economics") or {}
    v = econ.get("net_5m_pct")
    if v is None:
        return "NO_EXACT_OPTION_ECONOMICS"
    v = float(v)
    if v >= 10:
        return "EXCELLENT_5M_GE_10"
    if v >= 3:
        return "GOOD_5M_3_TO_10"
    if v > 0:
        return "SMALL_WIN_5M_0_TO_3"
    if v > -5:
        return "LOSS_5M_0_TO_MINUS5"
    return "LARGE_LOSS_5M_LE_MINUS5"


def top_rank(rows: list[dict[str, Any]], direction: str, n: int = 10) -> list[dict[str, Any]]:
    use = [
        r for r in rows
        if r["direction"] == direction
        and (r.get("option_economics") or {}).get("net_5m_pct") is not None
    ]
    use.sort(key=lambda r: float(r["option_economics"]["net_5m_pct"]), reverse=True)
    return use[:n]


def bottom_rank(rows: list[dict[str, Any]], direction: str, n: int = 10) -> list[dict[str, Any]]:
    use = [
        r for r in rows
        if r["direction"] == direction
        and (r.get("option_economics") or {}).get("net_5m_pct") is not None
    ]
    use.sort(key=lambda r: float(r["option_economics"]["net_5m_pct"]))
    return use[:n]


def compact_rank(r: dict[str, Any]) -> dict[str, Any]:
    econ = r.get("option_economics") or {}
    oi = r.get("oi") or {}
    fut = r.get("futures") or {}
    pf = r.get("price_features") or {}
    return {
        "block": r.get("block"),
        "session_date": r.get("session_date"),
        "setup_type": r.get("setup_type"),
        "direction": r.get("direction"),
        "decision_family": r.get("decision_family"),
        "signal_timestamp": r.get("signal_timestamp"),
        "price_features": pf,
        "price_pass_count": r.get("price_pass_count"),
        "oi_quality": r.get("oi_quality"),
        "ce_state": oi.get("ce_state"),
        "pe_state": oi.get("pe_state"),
        "futures_vwap_distance_points": fut.get("distance_points"),
        "futures_vwap_aligned": fut.get("aligned"),
        "option_side": econ.get("option_side"),
        "strike": econ.get("strike"),
        "net_1m_pct": econ.get("net_1m_pct"),
        "net_3m_pct": econ.get("net_3m_pct"),
        "net_5m_pct": econ.get("net_5m_pct"),
        "net_10m_pct": econ.get("net_10m_pct"),
        "net_15m_pct": econ.get("net_15m_pct"),
        "mfe_pct_15m": econ.get("mfe_pct_15m"),
        "mae_pct_15m": econ.get("mae_pct_15m"),
    }


def parse_named(v: str) -> tuple[str, Path]:
    b, p = v.split("|", 1)
    if b not in ALLOWED_BLOCKS:
        raise argparse.ArgumentTypeError(f"invalid block {b}")
    return b, Path(p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--structural", required=True)
    ap.add_argument("--stable-state", required=True)
    ap.add_argument("--controlled-comparison", required=True)
    ap.add_argument("--canonical-option-economics", required=True)
    ap.add_argument("--positioning", action="append", required=True, type=parse_named)
    ap.add_argument("--futures-vwap", required=True)
    ap.add_argument("--sep15-intraday", required=False)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    structural = load_json(Path(args.structural))
    stable_doc = load_json(Path(args.stable_state))
    comparison = load_json(Path(args.controlled_comparison))
    economics = load_json(Path(args.canonical_option_economics))

    events = load_structural_events(structural)
    stable_idx = stable_feature_index(stable_doc)
    armc_idx = arm_c_trade_index(comparison)
    all_option_rows = all_option_trade_index(economics)
    positioning = load_positioning(args.positioning)
    futures = load_futures(Path(args.futures_vwap))

    rows = []
    for e in events:
        block = str(e.get("block"))
        session = str(e.get("session_date"))
        setup = str(e.get("setup_type") or "")
        stable = stable_idx.get((block, session, setup))
        base = {
            "block": block,
            "session_date": session,
            "setup_type": setup,
            "direction": str(e.get("direction")),
            "decision_family": decision_family(e),
            "reference_high": num(e.get("reference_high")),
            "reference_low": num(e.get("reference_low")),
            "reference_midpoint": num(e.get("reference_midpoint")),
            "midpoint_break_timestamp": e.get("midpoint_break_timestamp"),
            "boundary_break_timestamp": e.get("boundary_break_timestamp"),
        }
        base.update(extract_features(e, stable, positioning, futures))
        base = attach_option_economics(base, armc_idx, all_option_rows)
        base["quality_bucket"] = quality_bucket(base)
        rows.append(base)

    sessions = sorted({r["session_date"] for r in rows})

    by_direction = {
        d: summarize([r for r in rows if r["direction"] == d])
        for d in ("BULLISH", "BEARISH")
    }
    by_decision = {
        k: summarize([r for r in rows if r["decision_family"] == k])
        for k in sorted({r["decision_family"] for r in rows})
    }
    quality_counts = dict(Counter(r["quality_bucket"] for r in rows))

    sep7 = [compact_rank(r) for r in rows if r["session_date"] == "2026-09-07"]
    sep15 = None
    if args.sep15_intraday:
        p = Path(args.sep15_intraday)
        if p.exists():
            sep15 = load_json(p)

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "research_status": "DESCRIPTIVE_GLOBAL_SESSION_EXEMPLAR_ANALYSIS_ONLY",
        "scope": {
            "historical_session_count": len(sessions),
            "historical_event_count": len(rows),
            "blocks": sorted(ALLOWED_BLOCKS),
            "forbidden_blocks": sorted(FORBIDDEN_BLOCKS),
            "sep15_current_day_included_as_external_reference": sep15 is not None,
        },
        "overall": summarize(rows),
        "by_direction": by_direction,
        "by_decision_family": by_decision,
        "quality_bucket_counts": quality_counts,
        "top_bullish_by_5m": [compact_rank(r) for r in top_rank(rows, "BULLISH")],
        "top_bearish_by_5m": [compact_rank(r) for r in top_rank(rows, "BEARISH")],
        "bottom_bullish_by_5m": [compact_rank(r) for r in bottom_rank(rows, "BULLISH")],
        "bottom_bearish_by_5m": [compact_rank(r) for r in bottom_rank(rows, "BEARISH")],
        "sep7_historical_reference": sep7,
        "sep15_external_reference": sep15,
        "events": rows,
        "integrity": {
            "strategy_rules_modified": False,
            "threshold_tuning_performed": False,
            "outcome_used_for_live_selection": False,
            "oos_e_f_g_h_used": False,
            "paper_or_live_order_emission_allowed": False,
            "outcomes_used_only_for_retrospective_grouping_and_ranking": True,
        },
        "interpretation_guard": (
            "Ranking and quality buckets use realized outcomes only for retrospective research. "
            "They must not be converted directly into live filters without freezing a candidate "
            "rule and validating on fresh precommitted OOS data."
        ),
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8")

    print(json.dumps({
        "research_version": RESEARCH_VERSION,
        "scope": result["scope"],
        "quality_bucket_counts": quality_counts,
        "top_bullish_by_5m": result["top_bullish_by_5m"][:5],
        "top_bearish_by_5m": result["top_bearish_by_5m"][:5],
        "bottom_bullish_by_5m": result["bottom_bullish_by_5m"][:5],
        "bottom_bearish_by_5m": result["bottom_bearish_by_5m"][:5],
        "sep7_historical_reference": sep7,
        "output": str(out),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
