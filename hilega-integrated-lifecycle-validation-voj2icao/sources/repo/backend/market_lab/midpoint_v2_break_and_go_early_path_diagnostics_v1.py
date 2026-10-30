from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

RESEARCH_VERSION = "MIDPOINT_V2_BREAK_AND_GO_EARLY_PATH_DIAGNOSTICS_V1"
EXPECTED_STATE_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"
EXPECTED_ECONOMICS_VERSION = "MIDPOINT_V3_2_EXACT_OPTION_ECONOMICS_V1"

TARGET_SETUP = "RED_BREAK"
TARGET_DIRECTION = "BEARISH"
TARGET_STATE = "CONFIRM_CONTINUATION"
START = date(2026, 6, 9)
END = date(2026, 9, 7)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def parse_dt(v: str) -> datetime:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def walk_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def first_existing(headers: list[str], names: tuple[str, ...]) -> str:
    lower = {h.lower(): h for h in headers}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    raise ValueError(f"missing one of {names}; available={headers}")


def optional_existing(headers: list[str], names: tuple[str, ...]) -> str | None:
    lower = {h.lower(): h for h in headers}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def ffloat(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_underlying_file(path: Path):
    out = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        headers = list(rd.fieldnames or [])
        ts_col = first_existing(headers, ("timestamp", "datetime", "time", "ts"))
        date_col = optional_existing(headers, ("session_date", "date", "trading_date"))
        open_col = first_existing(headers, ("open", "o"))
        high_col = first_existing(headers, ("high", "h"))
        low_col = first_existing(headers, ("low", "l"))
        close_col = first_existing(headers, ("close", "c"))
        for r in rd:
            raw = r.get(ts_col)
            if not raw:
                continue
            try:
                ts = parse_dt(raw)
            except ValueError:
                continue
            sd = str(r.get(date_col)) if date_col and r.get(date_col) else ts.date().isoformat()
            vals = {
                "open": ffloat(r.get(open_col)),
                "high": ffloat(r.get(high_col)),
                "low": ffloat(r.get(low_col)),
                "close": ffloat(r.get(close_col)),
            }
            if any(v is None for v in vals.values()):
                continue
            out[(sd, ts.isoformat())] = vals
    return out


def parse_underlying_specs(specs: list[str]):
    markets = {}
    for spec in specs:
        if "|" not in spec:
            raise ValueError("--underlying must be BLOCK|path.csv")
        block, raw = spec.split("|", 1)
        markets[block.strip()] = load_underlying_file(Path(raw.strip()))
    return markets


def event_key(r: dict[str, Any]):
    return (
        str(r.get("block")),
        str(r.get("session_date")),
        str(r.get("setup_type")),
        str(r.get("direction")),
    )


def extract_economics_rows(doc):
    rows, seen = [], set()
    for r in walk_dicts(doc):
        if r.get("t3_state") != TARGET_STATE:
            continue
        if not all(r.get(k) is not None for k in ("block","session_date","setup_type","direction","entry_timestamp","entry_price")):
            continue
        sig = (r["block"], r["session_date"], r["setup_type"], r["direction"], r["entry_timestamp"])
        if sig in seen:
            continue
        seen.add(sig)
        rows.append(r)
    return rows


def extract_t3_checkpoint_rows(doc):
    rows, seen = [], set()
    for r in walk_dicts(doc):
        if r.get("checkpoint_label") != "T+3":
            continue
        if not all(r.get(k) is not None for k in ("block","session_date","setup_type","direction")):
            continue
        sig = event_key(r)
        if sig in seen:
            continue
        seen.add(sig)
        rows.append(r)
    return rows


def candidate_events(state):
    rows = []
    for e in state.get("events") or []:
        sd = e.get("session_date")
        if not sd:
            continue
        d = date.fromisoformat(sd)
        if not (START <= d <= END):
            continue
        if e.get("setup_type") != TARGET_SETUP:
            continue
        if e.get("direction") != TARGET_DIRECTION:
            continue
        if e.get("t3_state") != TARGET_STATE:
            continue
        rows.append(e)
    return rows


def classify_path(fav5, fav30, fav60):
    # Descriptive sign-only taxonomy: no optimized point threshold.
    if fav5 is not None and fav5 > 0:
        return "IMMEDIATE_FOLLOW_THROUGH"
    later = [x for x in (fav30, fav60) if x is not None]
    if later and max(later) > 0:
        return "DELAYED_FOLLOW_THROUGH"
    return "FAILED_CONTINUATION"


def path_metrics(market, sd, entry_ts):
    ts = parse_dt(entry_ts)
    entry = market.get((sd, ts.isoformat()))
    if not entry:
        return {"available": False, "issue": "MISSING_ENTRY_BAR"}

    entry_open = float(entry["open"])
    favorable_close_points = {}
    for m in (1, 2, 3, 5, 15, 30, 60):
        bar = market.get((sd, (ts + timedelta(minutes=m)).isoformat()))
        favorable_close_points[f"{m}m"] = None if not bar else entry_open - float(bar["close"])

    closes = []
    for m in range(0, 61):
        bar = market.get((sd, (ts + timedelta(minutes=m)).isoformat()))
        if bar:
            closes.append((m, float(bar["close"]), float(bar["low"]), float(bar["high"])))

    if not closes:
        return {"available": False, "issue": "NO_POST_ENTRY_BARS"}

    mfe = entry_open - min(x[2] for x in closes)
    mae = max(x[3] for x in closes) - entry_open
    fav5 = favorable_close_points["5m"]
    fav30 = favorable_close_points["30m"]
    fav60 = favorable_close_points["60m"]

    return {
        "available": True,
        "issue": None,
        "entry_underlying_open": entry_open,
        "favorable_close_points": favorable_close_points,
        "mfe_points_60m": mfe,
        "mae_points_60m": mae,
        "path_class": classify_path(fav5, fav30, fav60),
    }


def compact_feature_view(checkpoint):
    if not checkpoint:
        return None
    pf = checkpoint.get("price_features") or {}
    return {
        "acceptance_pct": pf.get("acceptance_pct"),
        "momentum_5m_directional": pf.get("momentum_5m_directional"),
        "progress_points": pf.get("progress_points"),
        "giveback_from_best_checkpoint_points": pf.get("giveback_from_best_checkpoint_points"),
        "consecutive_closes": pf.get("consecutive_closes"),
        "velocity": pf.get("velocity"),
        "oi": checkpoint.get("oi"),
    }


def summarize_group(rows):
    if not rows:
        return {"count": 0}
    def vals(path):
        out = []
        for r in rows:
            v = r
            for key in path:
                if not isinstance(v, dict):
                    v = None
                    break
                v = v.get(key)
            if isinstance(v, (int, float)):
                out.append(float(v))
        return out
    def avg(path):
        x = vals(path)
        return mean(x) if x else None

    return {
        "count": len(rows),
        "t1_oi_quality_counts": dict(Counter(r.get("t1_oi_quality") for r in rows)),
        "t3_oi_quality_counts": dict(Counter(r.get("t3_oi_quality") for r in rows)),
        "oi_transition_counts": dict(Counter(r.get("exact_oi_transition_t1_to_t3") for r in rows)),
        "price_pass_count_counts": dict(Counter(r.get("price_pass_count") for r in rows)),
        "mean_acceptance_pct": avg(("t3_raw_features","acceptance_pct")),
        "mean_momentum_5m_directional": avg(("t3_raw_features","momentum_5m_directional")),
        "mean_progress_points": avg(("t3_raw_features","progress_points")),
        "mean_giveback_points": avg(("t3_raw_features","giveback_from_best_checkpoint_points")),
        "mean_consecutive_closes": avg(("t3_raw_features","consecutive_closes")),
        "mean_velocity": avg(("t3_raw_features","velocity")),
        "mean_underlying_mfe_60m": avg(("underlying","mfe_points_60m")),
        "mean_underlying_mae_60m": avg(("underlying","mae_points_60m")),
        "mean_option_mfe_15m_pct": avg(("option_economics","mfe_pct_15m")),
        "mean_option_mae_15m_pct": avg(("option_economics","mae_pct_15m")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--checkpoint-diagnostics", required=True)
    ap.add_argument("--economics", required=True)
    ap.add_argument("--underlying", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    state = load_json(Path(args.state))
    checkpoints = load_json(Path(args.checkpoint_diagnostics))
    economics = load_json(Path(args.economics))

    if state.get("research_version") != EXPECTED_STATE_VERSION:
        raise SystemExit(f"unexpected state version={state.get('research_version')!r}")
    if economics.get("research_version") != EXPECTED_ECONOMICS_VERSION:
        raise SystemExit(f"unexpected economics version={economics.get('research_version')!r}")

    markets = parse_underlying_specs(args.underlying)
    econ_idx = {event_key(r): r for r in extract_economics_rows(economics)}
    cp_idx = {event_key(r): r for r in extract_t3_checkpoint_rows(checkpoints)}

    rows = []
    for e in candidate_events(state):
        key = event_key(e)
        econ = econ_idx.get(key)
        cp = cp_idx.get(key)
        market = markets.get(str(e.get("block")))

        if econ and market:
            underlying = path_metrics(market, e["session_date"], econ["entry_timestamp"])
        elif not econ:
            underlying = {"available": False, "issue": "MISSING_ECONOMICS"}
        else:
            underlying = {"available": False, "issue": "MISSING_UNDERLYING_BLOCK"}

        score = e.get("t3_score") or {}
        row = {
            "block": e.get("block"),
            "session_date": e.get("session_date"),
            "setup_type": e.get("setup_type"),
            "direction": e.get("direction"),
            "t1_observation_state": (e.get("t1_observation") or {}).get("state"),
            "t1_oi_quality": (e.get("t1_observation") or {}).get("oi_quality"),
            "t3_oi_quality": score.get("oi_quality"),
            "exact_oi_transition_t1_to_t3": e.get("exact_oi_transition_t1_to_t3"),
            "price_pass_count": score.get("price_pass_count"),
            "price_pass_ratio": score.get("price_pass_ratio"),
            "primary_outcome": e.get("primary_outcome"),
            "t3_raw_features": compact_feature_view(cp),
            "underlying": underlying,
            "option_economics": None if not econ else {
                "entry_timestamp": econ.get("entry_timestamp"),
                "entry_price": econ.get("entry_price"),
                "strike": econ.get("strike"),
                "mfe_pct_15m": econ.get("mfe_pct_15m"),
                "mae_pct_15m": econ.get("mae_pct_15m"),
                "net_returns_pct": econ.get("net_returns_pct"),
            },
        }
        rows.append(row)

    groups = defaultdict(list)
    for r in rows:
        pc = r["underlying"].get("path_class") if r["underlying"].get("available") else "UNAVAILABLE"
        groups[pc].append(r)

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "candidate_scope": {
            "window": {"start": START.isoformat(), "end": END.isoformat()},
            "setup_type": TARGET_SETUP,
            "direction": TARGET_DIRECTION,
            "t3_state": TARGET_STATE,
        },
        "path_taxonomy": {
            "IMMEDIATE_FOLLOW_THROUGH": "5-minute favorable close movement > 0 points",
            "DELAYED_FOLLOW_THROUGH": "5-minute favorable close movement <= 0, but 30m or 60m favorable close movement > 0",
            "FAILED_CONTINUATION": "5-minute favorable close movement <= 0 and neither 30m nor 60m favorable close movement > 0",
            "threshold_search_performed": False,
            "point_threshold_used": 0,
        },
        "overall": {
            "candidate_count": len(rows),
            "available_count": sum(r["underlying"].get("available") for r in rows),
            "path_class_counts": dict(Counter(
                r["underlying"].get("path_class") if r["underlying"].get("available") else "UNAVAILABLE"
                for r in rows
            )),
        },
        "group_summaries": {k: summarize_group(v) for k, v in sorted(groups.items())},
        "sep7_reference": next((r for r in rows if r["session_date"] == "2026-09-07"), None),
        "rows": rows,
        "integrity": {
            "candidate_selection_uses_frozen_v1_state_only": True,
            "path_classification_uses_underlying_only": True,
            "option_pnl_not_used_to_define_path_class": True,
            "no_stop_threshold_sweep": True,
            "no_oi_filter_promoted": True,
            "oos_h_used": False,
            "e_f_g_used": False,
        },
        "governance": {
            "diagnostic_only": True,
            "no_delayed_entry_promoted": True,
            "no_exit_change_promoted": True,
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
