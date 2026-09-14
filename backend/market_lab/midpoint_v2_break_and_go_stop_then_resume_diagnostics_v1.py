from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

RESEARCH_VERSION = "MIDPOINT_V2_BREAK_AND_GO_STOP_THEN_RESUME_DIAGNOSTICS_V1"
EXPECTED_STATE_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"
FROZEN_POLICY = "SL5_BE5_TRAIL3_AFTER10_TIME15"

START = date(2026, 6, 9)
END = date(2026, 9, 7)
TARGET_SETUP = "RED_BREAK"
TARGET_DIRECTION = "BEARISH"
TARGET_STATE = "CONFIRM_CONTINUATION"


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


def ffloat(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_underlying(path: Path):
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


def parse_underlying_specs(specs):
    out = {}
    for spec in specs:
        if "|" not in spec:
            raise ValueError("--underlying must be BLOCK|path.csv")
        block, raw = spec.split("|", 1)
        out[block.strip()] = load_underlying(Path(raw.strip()))
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
        out.append(e)
    return out


def extract_exit_rows(doc):
    out, seen = [], set()
    for r in walk_dicts(doc):
        if r.get("policy_id") != FROZEN_POLICY:
            continue
        if not all(r.get(k) is not None for k in ("block", "session_date", "direction",
                                                  "entry_timestamp", "exit_timestamp",
                                                  "exit_reason", "net_return_pct")):
            continue
        sig = (
            str(r["block"]), str(r["session_date"]), str(r["direction"]),
            str(r["entry_timestamp"]), str(r["policy_id"])
        )
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
    return out


def classify_resume(f15, f30, f60):
    # Sign-only descriptive classification; no point threshold search.
    if f15 is not None and f15 > 0:
        return "RESUMED_BY_15M"
    if f30 is not None and f30 > 0:
        return "RESUMED_BY_30M"
    if f60 is not None and f60 > 0:
        return "RESUMED_BY_60M"
    return "NO_RESUME_BY_60M"


def post_exit_underlying(market, sd, exit_timestamp):
    ts = parse_dt(exit_timestamp)
    exit_bar = market.get((sd, ts.isoformat()))
    if not exit_bar:
        return {"available": False, "issue": "MISSING_EXIT_BAR"}

    anchor = float(exit_bar["close"])
    horizons = {}
    for m in (1, 3, 5, 15, 30, 60):
        bar = market.get((sd, (ts + timedelta(minutes=m)).isoformat()))
        horizons[f"{m}m"] = None if not bar else anchor - float(bar["close"])

    bars = []
    for m in range(0, 61):
        bar = market.get((sd, (ts + timedelta(minutes=m)).isoformat()))
        if bar:
            bars.append((m, bar))

    if not bars:
        return {"available": False, "issue": "NO_POST_EXIT_BARS"}

    mfe = anchor - min(float(b["low"]) for _, b in bars)
    mae = max(float(b["high"]) for _, b in bars) - anchor

    return {
        "available": True,
        "issue": None,
        "exit_underlying_close": anchor,
        "favorable_close_points_after_exit": horizons,
        "post_exit_mfe_points_60m": mfe,
        "post_exit_mae_points_60m": mae,
        "resume_class": classify_resume(horizons["15m"], horizons["30m"], horizons["60m"]),
    }


def summarize(rows):
    stop_rows = [r for r in rows if r.get("is_stop_exit")]
    avail = [r for r in stop_rows if r["post_exit_underlying"].get("available")]

    def vals(field):
        return [
            float(r["post_exit_underlying"][field])
            for r in avail
            if isinstance(r["post_exit_underlying"].get(field), (int, float))
        ]

    mfe = vals("post_exit_mfe_points_60m")
    mae = vals("post_exit_mae_points_60m")
    return {
        "candidate_count": len(rows),
        "stop_exit_count": len(stop_rows),
        "non_stop_exit_count": len(rows) - len(stop_rows),
        "post_exit_available_count": len(avail),
        "resume_class_counts": dict(Counter(
            r["post_exit_underlying"].get("resume_class")
            for r in avail
        )),
        "stop_exit_reason_counts": dict(Counter(r.get("exit_reason") for r in stop_rows)),
        "mean_post_exit_mfe_points_60m": mean(mfe) if mfe else None,
        "median_post_exit_mfe_points_60m": median(mfe) if mfe else None,
        "mean_post_exit_mae_points_60m": mean(mae) if mae else None,
        "median_post_exit_mae_points_60m": median(mae) if mae else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--exit-research", required=True)
    ap.add_argument("--underlying", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    state = load_json(Path(args.state))
    exits = load_json(Path(args.exit_research))

    if state.get("research_version") != EXPECTED_STATE_VERSION:
        raise SystemExit(f"unexpected state version={state.get('research_version')!r}")

    markets = parse_underlying_specs(args.underlying)
    exit_rows = extract_exit_rows(exits)

    exit_idx = {}
    for r in exit_rows:
        exit_idx[(str(r["block"]), str(r["session_date"]), str(r["direction"]))] = r

    rows = []
    for e in candidate_events(state):
        ex = exit_idx.get((str(e.get("block")), str(e["session_date"]), str(e["direction"])))
        if ex is None:
            rows.append({
                "block": e.get("block"),
                "session_date": e.get("session_date"),
                "issue": "MISSING_FROZEN_EXIT",
            })
            continue

        market = markets.get(str(e.get("block")))
        reason = str(ex.get("exit_reason"))
        is_stop = reason in {"STOP_TOUCH", "STOP_GAP"}

        post = (
            post_exit_underlying(market, e["session_date"], ex["exit_timestamp"])
            if is_stop and market is not None
            else {"available": False, "issue": "NOT_STOP_EXIT" if not is_stop else "MISSING_UNDERLYING_BLOCK"}
        )

        rows.append({
            "block": e.get("block"),
            "session_date": e.get("session_date"),
            "t1_observation_state": (e.get("t1_observation") or {}).get("state"),
            "t1_oi_quality": (e.get("t1_observation") or {}).get("oi_quality"),
            "t3_oi_quality": (e.get("t3_score") or {}).get("oi_quality"),
            "exact_oi_transition_t1_to_t3": e.get("exact_oi_transition_t1_to_t3"),
            "price_pass_count": (e.get("t3_score") or {}).get("price_pass_count"),
            "primary_outcome": e.get("primary_outcome"),
            "entry_timestamp": ex.get("entry_timestamp"),
            "exit_timestamp": ex.get("exit_timestamp"),
            "exit_reason": reason,
            "frozen_net_return_pct": ex.get("net_return_pct"),
            "is_stop_exit": is_stop,
            "post_exit_underlying": post,
        })

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "candidate_scope": {
            "window": {"start": START.isoformat(), "end": END.isoformat()},
            "setup_type": TARGET_SETUP,
            "direction": TARGET_DIRECTION,
            "t3_state": TARGET_STATE,
            "frozen_exit_policy": FROZEN_POLICY,
        },
        "resume_taxonomy": {
            "RESUMED_BY_15M": "underlying close is bearish-favorable vs exit-bar close by +15m",
            "RESUMED_BY_30M": "not resumed by +15m, but bearish-favorable by +30m",
            "RESUMED_BY_60M": "not resumed by +30m, but bearish-favorable by +60m",
            "NO_RESUME_BY_60M": "no bearish-favorable close at +15m/+30m/+60m",
            "point_threshold_search_performed": False,
            "classification_threshold_points": 0,
        },
        "summary": summarize(rows),
        "sep7_reference": next((r for r in rows if r.get("session_date") == "2026-09-07"), None),
        "rows": rows,
        "integrity": {
            "frozen_v1_entry_unchanged": True,
            "frozen_v1_exit_unchanged": True,
            "post_exit_analysis_only": True,
            "resume_class_uses_underlying_only": True,
            "option_pnl_not_used_to_define_resume": True,
            "no_reentry_rule_tested": True,
            "no_stop_threshold_sweep": True,
            "oos_h_used": False,
            "e_f_g_used": False,
        },
        "governance": {
            "diagnostic_only": True,
            "no_reentry_promoted": True,
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
