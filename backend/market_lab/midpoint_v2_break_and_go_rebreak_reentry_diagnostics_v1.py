from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

RESEARCH_VERSION = "MIDPOINT_V2_BREAK_AND_GO_REBREAK_REENTRY_DIAGNOSTICS_V1_FIX1"
EXPECTED_STATE_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"
EXPECTED_ECONOMICS_VERSION = "MIDPOINT_V3_2_EXACT_OPTION_ECONOMICS_V1"

START = date(2026, 6, 9)
END = date(2026, 9, 7)
TARGET_SETUP = "RED_BREAK"
TARGET_DIRECTION = "BEARISH"
TARGET_STATE = "CONFIRM_CONTINUATION"
FROZEN_POLICY = "SL5_BE5_TRAIL3_AFTER10_TIME15"


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


def parse_block_specs(specs, loader):
    out = {}
    for spec in specs:
        if "|" not in spec:
            raise ValueError("block files must be BLOCK|path.csv")
        block, raw = spec.split("|", 1)
        out[block.strip()] = loader(Path(raw.strip()))
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


def extract_economics_rows(doc):
    out, seen = [], set()
    for r in walk_dicts(doc):
        if r.get("t3_state") != TARGET_STATE:
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


def extract_exit_rows(doc):
    out, seen = [], set()
    for r in walk_dicts(doc):
        if r.get("policy_id") != FROZEN_POLICY:
            continue
        if not all(r.get(k) is not None for k in (
            "block", "session_date", "direction", "entry_timestamp",
            "exit_timestamp", "exit_reason", "net_return_pct"
        )):
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


def extract_framework_rows(doc):
    out = {}
    for r in walk_dicts(doc):
        if r.get("setup_type") != TARGET_SETUP:
            continue
        if not all(r.get(k) is not None for k in ("session_date", "reference_low")):
            continue
        key = (str(r.get("session_date")), TARGET_SETUP)
        if key not in out:
            out[key] = r
    return out


def replay_stop_regime(option_market, econ, frozen_exit):
    """
    Attribute the active stop regime at the already-frozen exit timestamp.

    We do NOT choose the exit. We only replay trigger activation through bars
    strictly before the frozen exit bar:
      +5% => BE active next bar
      +10% => trailing active next bar
    """
    if option_market is None:
        return {"available": False, "issue": "MISSING_OPTION_OHLC_BLOCK"}

    inst = str(econ["instrument_key"])
    entry_ts = parse_dt(econ["entry_timestamp"])
    exit_ts = parse_dt(frozen_exit["exit_timestamp"])
    entry_price = float(econ["entry_price"])

    if exit_ts < entry_ts:
        return {"available": False, "issue": "EXIT_BEFORE_ENTRY"}

    be_triggered_on = None
    trail_triggered_on = None
    bars_seen = 0

    ts = entry_ts
    while ts < exit_ts:
        bar = option_market.get((inst, ts.isoformat()))
        if bar is not None:
            bars_seen += 1
            high_ret = (float(bar["high"]) / entry_price - 1.0) * 100.0
            if be_triggered_on is None and high_ret >= 5.0:
                be_triggered_on = ts
            if trail_triggered_on is None and high_ret >= 10.0:
                trail_triggered_on = ts
        ts += timedelta(minutes=1)

    if option_market.get((inst, exit_ts.isoformat())) is None:
        return {"available": False, "issue": "MISSING_OPTION_EXIT_BAR"}

    # Any trigger from a prior bar is active on the exit bar.
    if trail_triggered_on is not None:
        regime = "TRAILING"
    elif be_triggered_on is not None:
        regime = "BREAKEVEN"
    else:
        regime = "INITIAL_SL5"

    return {
        "available": True,
        "issue": None,
        "stop_regime": regime,
        "method": "REPLAYED_FROM_EXACT_OPTION_OHLC_TO_FROZEN_EXIT",
        "entry_price": entry_price,
        "entry_timestamp": entry_ts.isoformat(),
        "exit_timestamp": exit_ts.isoformat(),
        "bars_before_exit_seen": bars_seen,
        "be_triggered_on": None if be_triggered_on is None else be_triggered_on.isoformat(),
        "trail_triggered_on": None if trail_triggered_on is None else trail_triggered_on.isoformat(),
        "frozen_exit_reason": frozen_exit.get("exit_reason"),
        "frozen_net_return_pct": frozen_exit.get("net_return_pct"),
    }


def find_rebreak(market, sd, exit_ts, boundary, max_watch=60):
    if market is None:
        return {"available": False, "issue": "MISSING_UNDERLYING_BLOCK"}

    start = parse_dt(exit_ts) + timedelta(minutes=1)
    first = None

    for offset in range(max_watch):
        ts = start + timedelta(minutes=offset)
        bar = market.get((sd, ts.isoformat()))
        if not bar:
            continue
        if float(bar["close"]) < boundary:
            first = (ts, bar, offset + 1)
            break

    if first is None:
        return {
            "available": True,
            "issue": None,
            "rebreak_found": False,
            "rebreak_class": "NO_REBREAK_60M",
        }

    ts, bar, minutes_after_exit = first
    rebreak_close = float(bar["close"])
    next_bar = market.get((sd, (ts + timedelta(minutes=1)).isoformat()))
    held = bool(next_bar and float(next_bar["close"]) < boundary)

    favorable = {}
    bars = []
    for m in range(31):
        b = market.get((sd, (ts + timedelta(minutes=m)).isoformat()))
        if b:
            bars.append((m, b))
    for m in (1, 3, 5, 15, 30):
        b = market.get((sd, (ts + timedelta(minutes=m)).isoformat()))
        favorable[f"{m}m"] = None if not b else rebreak_close - float(b["close"])

    mfe = rebreak_close - min(float(b["low"]) for _, b in bars) if bars else None
    mae = max(float(b["high"]) for _, b in bars) - rebreak_close if bars else None

    return {
        "available": True,
        "issue": None,
        "rebreak_found": True,
        "rebreak_class": "REBREAK_HELD_2_CLOSES" if held else "REBREAK_SINGLE_CLOSE_ONLY",
        "rebreak_timestamp": ts.isoformat(),
        "minutes_after_exit": minutes_after_exit,
        "boundary": boundary,
        "rebreak_close": rebreak_close,
        "next_close_held_below_boundary": held,
        "next_close": None if next_bar is None else float(next_bar["close"]),
        "favorable_close_points_after_rebreak": favorable,
        "post_rebreak_mfe_points_30m": mfe,
        "post_rebreak_mae_points_30m": mae,
    }


def summarize(rows):
    attributed = [r for r in rows if r["stop_attribution"].get("available")]
    initial = [r for r in rows if r["eligible_initial_sl5"]]
    rebreak = [r for r in initial if r["rebreak"].get("rebreak_found")]
    held = [r for r in rebreak if r["rebreak"].get("rebreak_class") == "REBREAK_HELD_2_CLOSES"]

    mins = [r["rebreak"]["minutes_after_exit"] for r in rebreak]
    mfe = [
        r["rebreak"]["post_rebreak_mfe_points_30m"]
        for r in rebreak
        if isinstance(r["rebreak"].get("post_rebreak_mfe_points_30m"), (int, float))
    ]

    return {
        "frozen_candidate_count": len(rows),
        "explicit_replayed_stop_attribution_count": len(attributed),
        "stop_regime_counts": dict(Counter(
            r["stop_attribution"].get("stop_regime") for r in attributed
        )),
        "initial_sl5_count": len(initial),
        "rebreak_found_count": len(rebreak),
        "rebreak_held_2_closes_count": len(held),
        "rebreak_class_counts": dict(Counter(
            r["rebreak"].get("rebreak_class") for r in initial
            if r["rebreak"].get("available")
        )),
        "mean_minutes_to_rebreak": mean(mins) if mins else None,
        "median_minutes_to_rebreak": median(mins) if mins else None,
        "mean_post_rebreak_mfe_points_30m": mean(mfe) if mfe else None,
        "median_post_rebreak_mfe_points_30m": median(mfe) if mfe else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--framework", required=True)
    ap.add_argument("--economics", required=True)
    ap.add_argument("--exit-research", required=True)
    ap.add_argument("--option-ohlc", action="append", required=True)
    ap.add_argument("--underlying", action="append", required=True)
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

    underlyings = parse_block_specs(args.underlying, load_underlying)
    options = parse_block_specs(args.option_ohlc, load_option_ohlc)

    framework_idx = extract_framework_rows(framework)
    econ_idx = {event_key(r): r for r in extract_economics_rows(economics)}

    exit_idx = {}
    for r in extract_exit_rows(exits):
        exit_idx[(
            str(r["block"]),
            str(r["session_date"]),
            str(r["direction"]),
            str(r["entry_timestamp"]),
        )] = r

    rows = []

    for e in candidate_events(state):
        block = str(e.get("block"))
        sd = str(e.get("session_date"))
        key = event_key(e)

        fw = framework_idx.get((sd, TARGET_SETUP))
        econ = econ_idx.get(key)
        ex = None
        if econ is not None:
            ex = exit_idx.get((
                block, sd, TARGET_DIRECTION, str(econ["entry_timestamp"])
            ))

        if econ is None:
            attr = {"available": False, "issue": "MISSING_EXACT_ECONOMICS"}
        elif ex is None:
            attr = {"available": False, "issue": "MISSING_FROZEN_EXIT"}
        else:
            attr = replay_stop_regime(options.get(block), econ, ex)

        eligible = bool(
            attr.get("available") and attr.get("stop_regime") == "INITIAL_SL5"
        )

        reference_low = None if fw is None else ffloat(fw.get("reference_low"))
        reference_high = None if fw is None else ffloat(fw.get("reference_high"))

        if not eligible:
            rebreak = {
                "available": False,
                "issue": "NOT_INITIAL_SL5" if attr.get("available") else attr.get("issue"),
            }
        elif reference_low is None:
            rebreak = {"available": False, "issue": "MISSING_REFERENCE_LOW"}
        else:
            rebreak = find_rebreak(
                underlyings.get(block),
                sd,
                ex["exit_timestamp"],
                reference_low,
                max_watch=60,
            )

        rows.append({
            "block": block,
            "session_date": sd,
            "reference_low": reference_low,
            "reference_high": reference_high,
            "framework_source_available": fw is not None,
            "t1_observation_state": (e.get("t1_observation") or {}).get("state"),
            "t1_oi_quality": (e.get("t1_observation") or {}).get("oi_quality"),
            "t3_oi_quality": (e.get("t3_score") or {}).get("oi_quality"),
            "exact_oi_transition_t1_to_t3": e.get("exact_oi_transition_t1_to_t3"),
            "price_pass_count": (e.get("t3_score") or {}).get("price_pass_count"),
            "primary_outcome": e.get("primary_outcome"),
            "stop_attribution": attr,
            "eligible_initial_sl5": eligible,
            "frozen_exit": None if ex is None else {
                "entry_timestamp": ex.get("entry_timestamp"),
                "exit_timestamp": ex.get("exit_timestamp"),
                "exit_reason": ex.get("exit_reason"),
                "net_return_pct": ex.get("net_return_pct"),
            },
            "rebreak": rebreak,
        })

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "candidate_scope": {
            "window": {"start": START.isoformat(), "end": END.isoformat()},
            "setup_type": TARGET_SETUP,
            "direction": TARGET_DIRECTION,
            "t3_state": TARGET_STATE,
            "required_stop_regime": "INITIAL_SL5",
            "frozen_exit_policy": FROZEN_POLICY,
        },
        "source_correction": {
            "v2_new_arm_stop_attribution_artifact_used": False,
            "reason": "V2 E15 stop-regime attribution contains the 17 new-arm candidates, not the frozen V1 immediate cohort",
            "v1_stop_regime_method": "replay exact option OHLC only up to the already-frozen exit timestamp",
            "reference_boundary_source": "opening-candle-midpoint-framework-v1-1 development artifact",
        },
        "rebreak_definition": {
            "bearish_rebreak": "first 1-minute CLOSE below original RED reference_low after frozen exit",
            "held_confirmation": "next 1-minute CLOSE also remains below original RED reference_low",
            "watch_window_minutes": 60,
            "point_threshold_search_performed": False,
            "option_pnl_replay_performed": False,
        },
        "summary": summarize(rows),
        "sep7_reference": next((r for r in rows if r["session_date"] == "2026-09-07"), None),
        "rows": rows,
        "integrity": {
            "v1_stop_regime_replayed_from_exact_option_ohlc": True,
            "exit_timestamp_is_frozen_not_reselected": True,
            "activation_uses_only_bars_strictly_before_exit_bar": True,
            "original_reference_low_loaded_from_framework": True,
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
