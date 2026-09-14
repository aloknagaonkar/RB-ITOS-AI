from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

RESEARCH_VERSION = "MIDPOINT_V2_BREAK_AND_GO_REBREAK_REENTRY_DIAGNOSTICS_V1"
EXPECTED_STATE_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"
FROZEN_POLICY = "SL5_BE5_TRAIL3_AFTER10_TIME15"

START = date(2026, 6, 9)
END = date(2026, 9, 7)
TARGET_SETUP = "RED_BREAK"
TARGET_DIRECTION = "BEARISH"
TARGET_STATE = "CONFIRM_CONTINUATION"
TARGET_STOP_REGIME = "INITIAL_SL5"


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
        if not all(r.get(k) is not None for k in ("block","session_date","direction",
                                                  "entry_timestamp","exit_timestamp",
                                                  "exit_reason","net_return_pct")):
            continue
        sig = (
            str(r.get("block")), str(r.get("session_date")), str(r.get("direction")),
            str(r.get("entry_timestamp")), str(r.get("policy_id"))
        )
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
    return out


def normalize_stop_regime(r):
    for key in (
        "stop_regime",
        "active_stop_regime",
        "exit_stop_regime",
        "stop_type",
        "exit_stop_type",
        "regime",
    ):
        v = r.get(key)
        if isinstance(v, str) and v:
            u = v.strip().upper()
            if u in {"INITIAL_SL5", "INITIAL_SL", "SL5", "INITIAL_5_PERCENT"}:
                return "INITIAL_SL5"
            if "BREAK" in u or u == "BE":
                return "BREAKEVEN"
            if "TRAIL" in u:
                return "TRAILING"
            if "TIME" in u:
                return "TIME_EXIT"
            return u
    return None


def extract_stop_attribution_rows(doc):
    """
    Robustly find rows from the E15 stop-regime attribution artifact.
    Requires explicit stop-regime attribution; does not infer INITIAL_SL5 from P&L.
    """
    out, seen = [], set()
    for r in walk_dicts(doc):
        if not all(r.get(k) is not None for k in ("session_date", "direction")):
            continue
        regime = normalize_stop_regime(r)
        if regime is None:
            continue
        block = str(r.get("block"))
        setup = str(r.get("setup_type") or TARGET_SETUP)
        direction = str(r.get("direction"))
        if direction != TARGET_DIRECTION:
            continue
        sig = (block, str(r.get("session_date")), setup, direction, regime)
        if sig in seen:
            continue
        seen.add(sig)
        x = dict(r)
        x["_normalized_stop_regime"] = regime
        x["_normalized_setup_type"] = setup
        out.append(x)
    return out


def find_rebreak(market, sd, exit_ts, boundary, max_watch=60):
    if market is None:
        return {"available": False, "issue": "MISSING_UNDERLYING_BLOCK"}

    start = parse_dt(exit_ts) + timedelta(minutes=1)
    first = None
    for m in range(max_watch):
        ts = start + timedelta(minutes=m)
        bar = market.get((sd, ts.isoformat()))
        if not bar:
            continue
        close = float(bar["close"])
        if close < boundary:
            first = (ts, bar, m + 1)
            break

    if first is None:
        return {
            "available": True,
            "issue": None,
            "rebreak_found": False,
            "rebreak_class": "NO_REBREAK_60M",
        }

    ts, bar, minutes_after_exit = first
    close = float(bar["close"])
    next_ts = ts + timedelta(minutes=1)
    next_bar = market.get((sd, next_ts.isoformat()))
    held_next_close = bool(next_bar and float(next_bar["close"]) < boundary)

    bars = []
    for m in range(0, 31):
        b = market.get((sd, (ts + timedelta(minutes=m)).isoformat()))
        if b:
            bars.append((m, b))

    favorable = {}
    for m in (1, 3, 5, 15, 30):
        b = market.get((sd, (ts + timedelta(minutes=m)).isoformat()))
        favorable[f"{m}m"] = None if not b else close - float(b["close"])

    mfe = None
    mae = None
    if bars:
        mfe = close - min(float(b["low"]) for _, b in bars)
        mae = max(float(b["high"]) for _, b in bars) - close

    return {
        "available": True,
        "issue": None,
        "rebreak_found": True,
        "rebreak_class": "REBREAK_HELD_2_CLOSES" if held_next_close else "REBREAK_SINGLE_CLOSE_ONLY",
        "rebreak_timestamp": ts.isoformat(),
        "minutes_after_exit": minutes_after_exit,
        "boundary": boundary,
        "rebreak_close": close,
        "next_close_held_below_boundary": held_next_close,
        "next_close": None if not next_bar else float(next_bar["close"]),
        "favorable_close_points_after_rebreak": favorable,
        "post_rebreak_mfe_points_30m": mfe,
        "post_rebreak_mae_points_30m": mae,
    }


def summarize(rows):
    eligible = [r for r in rows if r.get("eligible_initial_sl5")]
    explicit = [r for r in rows if r.get("stop_attribution_available")]
    rebreak = [r for r in eligible if r["rebreak"].get("rebreak_found")]
    held = [r for r in eligible if r["rebreak"].get("rebreak_class") == "REBREAK_HELD_2_CLOSES"]

    mins = [r["rebreak"]["minutes_after_exit"] for r in rebreak]
    mfe = [
        r["rebreak"]["post_rebreak_mfe_points_30m"]
        for r in rebreak
        if isinstance(r["rebreak"].get("post_rebreak_mfe_points_30m"), (int, float))
    ]

    return {
        "frozen_candidate_count": len(rows),
        "explicit_stop_attribution_count": len(explicit),
        "initial_sl5_count": len(eligible),
        "rebreak_found_count": len(rebreak),
        "rebreak_held_2_closes_count": len(held),
        "rebreak_class_counts": dict(Counter(
            r["rebreak"].get("rebreak_class")
            for r in eligible
            if r.get("rebreak")
        )),
        "mean_minutes_to_rebreak": mean(mins) if mins else None,
        "median_minutes_to_rebreak": median(mins) if mins else None,
        "mean_post_rebreak_mfe_points_30m": mean(mfe) if mfe else None,
        "median_post_rebreak_mfe_points_30m": median(mfe) if mfe else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--exit-research", required=True)
    ap.add_argument("--stop-attribution", required=True)
    ap.add_argument("--underlying", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    state = load_json(Path(args.state))
    exits = load_json(Path(args.exit_research))
    stops = load_json(Path(args.stop_attribution))

    if state.get("research_version") != EXPECTED_STATE_VERSION:
        raise SystemExit(f"unexpected state version={state.get('research_version')!r}")

    markets = parse_underlying_specs(args.underlying)

    exit_idx = {}
    for r in extract_exit_rows(exits):
        exit_idx[(str(r.get("block")), str(r.get("session_date")), str(r.get("direction")))] = r

    stop_rows = extract_stop_attribution_rows(stops)
    stop_idx = {}
    for r in stop_rows:
        stop_idx[(
            str(r.get("block")),
            str(r.get("session_date")),
            str(r.get("_normalized_setup_type")),
            str(r.get("direction")),
        )] = r

    rows = []
    for e in candidate_events(state):
        block = str(e.get("block"))
        sd = str(e.get("session_date"))
        ex = exit_idx.get((block, sd, TARGET_DIRECTION))
        st = stop_idx.get((block, sd, TARGET_SETUP, TARGET_DIRECTION))

        base = {
            "block": block,
            "session_date": sd,
            "reference_low": e.get("reference_low"),
            "reference_high": e.get("reference_high"),
            "t1_observation_state": (e.get("t1_observation") or {}).get("state"),
            "t1_oi_quality": (e.get("t1_observation") or {}).get("oi_quality"),
            "t3_oi_quality": (e.get("t3_score") or {}).get("oi_quality"),
            "exact_oi_transition_t1_to_t3": e.get("exact_oi_transition_t1_to_t3"),
            "price_pass_count": (e.get("t3_score") or {}).get("price_pass_count"),
            "primary_outcome": e.get("primary_outcome"),
            "stop_attribution_available": st is not None,
            "stop_regime": None if st is None else st.get("_normalized_stop_regime"),
            "eligible_initial_sl5": bool(st and st.get("_normalized_stop_regime") == TARGET_STOP_REGIME),
            "frozen_exit": None if ex is None else {
                "entry_timestamp": ex.get("entry_timestamp"),
                "exit_timestamp": ex.get("exit_timestamp"),
                "exit_reason": ex.get("exit_reason"),
                "net_return_pct": ex.get("net_return_pct"),
            },
        }

        if ex is None:
            base["rebreak"] = {"available": False, "issue": "MISSING_FROZEN_EXIT"}
        elif st is None:
            base["rebreak"] = {"available": False, "issue": "MISSING_STOP_ATTRIBUTION"}
        elif st.get("_normalized_stop_regime") != TARGET_STOP_REGIME:
            base["rebreak"] = {"available": False, "issue": "NOT_INITIAL_SL5"}
        elif e.get("reference_low") is None:
            base["rebreak"] = {"available": False, "issue": "MISSING_REFERENCE_LOW"}
        else:
            base["rebreak"] = find_rebreak(
                markets.get(block),
                sd,
                ex["exit_timestamp"],
                float(e["reference_low"]),
                max_watch=60,
            )

        rows.append(base)

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "candidate_scope": {
            "window": {"start": START.isoformat(), "end": END.isoformat()},
            "setup_type": TARGET_SETUP,
            "direction": TARGET_DIRECTION,
            "t3_state": TARGET_STATE,
            "required_stop_regime": TARGET_STOP_REGIME,
            "frozen_exit_policy": FROZEN_POLICY,
        },
        "rebreak_definition": {
            "bearish_rebreak": "first 1-minute CLOSE below original RED reference_low after frozen exit",
            "held_confirmation": "next 1-minute CLOSE also remains below original RED reference_low",
            "watch_window_minutes": 60,
            "point_threshold_search_performed": False,
            "option_pnl_replay_performed": False,
        },
        "summary": summarize(rows),
        "sep7_reference": next((r for r in rows if r.get("session_date") == "2026-09-07"), None),
        "rows": rows,
        "integrity": {
            "initial_sl5_must_be_explicitly_attributed": True,
            "initial_sl5_not_inferred_from_net_return": True,
            "original_reference_low_used": True,
            "underlying_close_only_for_rebreak": True,
            "no_wick_only_rebreak": True,
            "no_option_reentry_simulated": True,
            "no_new_stop_tested": True,
            "no_oi_filter_promoted": True,
            "oos_h_used": False,
            "e_f_g_used": False,
        },
        "governance": {
            "diagnostic_only": True,
            "no_reentry_rule_promoted": True,
            "no_v1_rule_changed": True,
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
