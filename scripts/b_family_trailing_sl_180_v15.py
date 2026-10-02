#!/usr/bin/env python3
"""
B FAMILY — TRAILING-SL 180-SESSION CHARACTERIZATION V15

Research question:
Can a causal structural trailing stop preserve more of Family-B's large
underlying-point runners than the existing immediate breakeven-after-+20 model?

IMPORTANT
---------
- Uses the frozen canonical Family-B detector unchanged.
- Requires exact canonical parity: 45 total = 27 older + 18 latest60.
- Uses the already-audited 180-session inputs.
- Does NOT tune B entry, VWAP threshold, delay window, or lifecycle.
- This is historical characterization, NOT independent validation.
- Underlying NIFTY points only, NOT CE/PE option-premium P&L.

Models
------
STRUCTURAL
    Existing structural invalidation only.

HYBRID_MIN15_ATR1_BE20
    Existing V8.2 model imported unchanged.

TRAIL_T1_SWING1
    initial risk = min(15, causal ATR14)
    proof = +20 favorable points
    after proof, trail behind latest causally CONFIRMED 1m swing:
      radius 1 = one bar left + one bar right
    newly confirmed trail applies NEXT BAR only
    stop never widens
    structural lifecycle remains mandatory
    NO forced breakeven floor

TRAIL_T2_SWING2
    same, but radius 2 = two bars left + two bars right
    slower structural trail
    newly confirmed trail applies NEXT BAR only
    NO forced breakeven floor

Same-bar proof+initial-stop touch is marked AMBIGUOUS rather than guessed.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from statistics import mean, median

CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V8_2 = Path("scripts/b_family_risk_model_comparison_v8_2.py")

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-trailing-sl-180-v15"
)
EVENTS_CSV = OUTDIR / "model-events-v15.csv"
RUNNERS_CSV = OUTDIR / "runner-capture-v15.csv"
REPORT_JSON = OUTDIR / "report-v15.json"
SUMMARY_TXT = OUTDIR / "summary-v15.txt"

EXPECTED_TOTAL = 45
EXPECTED_OLDER = 27
EXPECTED_LATEST60 = 18

PROOF_POINTS = 20.0
FIXED_CAP = 15.0
RUNNER_LEVELS = (20, 30, 50, 75, 100)

MODELS = (
    "STRUCTURAL",
    "HYBRID_MIN15_ATR1_BE20",
    "TRAIL_T1_SWING1",
    "TRAIL_T2_SWING2",
)


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def stop_price(direction, entry, risk):
    return entry - risk if direction == "BULLISH" else entry + risk


def stop_touched(direction, bar, stop):
    if direction == "BULLISH":
        return bar["low"] <= stop
    return bar["high"] >= stop


def stop_gap(direction, bar, stop):
    if direction == "BULLISH":
        return bar["open"] <= stop
    return bar["open"] >= stop


def favorable_bar_move(direction, entry, bar):
    px = bar["high"] if direction == "BULLISH" else bar["low"]
    return directional(direction, entry, px)


def sorted_session_rows(u):
    return [(ts, u[ts]) for ts in sorted(u)]


def latest_confirmed_pivot(history, direction, radius):
    """
    history: [(timestamp, bar), ...] up through the just-completed current bar.

    A pivot at index i is causal only when radius bars to its right have already
    completed. Strict comparisons avoid inventing a pivot across equal extrema.
    Returns (timestamp, pivot_price) for the latest confirmed pivot.
    """
    n = len(history)
    if n < 2 * radius + 1:
        return None

    latest = None
    last_candidate = n - 1 - radius

    for i in range(radius, last_candidate + 1):
        window = history[i - radius : i + radius + 1]
        cand_ts, cand = history[i]

        if direction == "BULLISH":
            p = cand["low"]
            others = [b["low"] for j, (_, b) in enumerate(window) if j != radius]
            if all(p < x for x in others):
                latest = (cand_ts, p)
        else:
            p = cand["high"]
            others = [b["high"] for j, (_, b) in enumerate(window) if j != radius]
            if all(p > x for x in others):
                latest = (cand_ts, p)

    return latest


def tighten(direction, current_stop, candidate):
    if candidate is None:
        return current_stop
    if direction == "BULLISH":
        return max(current_stop, candidate)
    return min(current_stop, candidate)


def trail_result(ev, u, atr, radius, canon):
    if atr is None:
        return {
            "eligible": False,
            "exit_timestamp": None,
            "points": None,
            "reason": "INELIGIBLE_NO_ATR",
            "initial_risk": None,
            "proof_timestamp": None,
            "trail_activated": False,
            "trail_updates": 0,
            "final_stop": None,
        }

    direction = ev["direction"]
    entry_ts = ev["entry_timestamp"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])
    risk = min(FIXED_CAP, float(atr))
    active_stop = stop_price(direction, entry, risk)
    proof_ts = None
    trail_activated = False
    updates = 0

    invalid_ts = ev.get("structural_invalidation_timestamp")
    rows = sorted_session_rows(u)

    # History begins with entry candle because later pivot confirmation may
    # legitimately confirm the entry candle as a swing.
    history = [(ts, bar) for ts, bar in rows if ts == entry_ts]

    started = False
    last_trusted_bar = None

    for ts, bar in rows:
        if ts == entry_ts:
            started = True
            continue
        if not started or not canon.is_trusted(ts):
            continue

        last_trusted_bar = (ts, bar)

        fav = favorable_bar_move(direction, entry, bar)
        hits_stop = stop_touched(direction, bar, active_stop)
        reaches_proof = proof_ts is None and fav >= PROOF_POINTS

        # We cannot know whether the +20 proof or initial stop occurred first
        # inside the same 1m candle.
        if reaches_proof and hits_stop:
            return {
                "eligible": True,
                "exit_timestamp": ts,
                "points": None,
                "reason": "AMBIGUOUS_PROOF_AND_STOP_SAME_BAR",
                "initial_risk": risk,
                "proof_timestamp": ts,
                "trail_activated": False,
                "trail_updates": updates,
                "final_stop": active_stop,
            }

        # Existing stop applies throughout this bar.
        if hits_stop:
            if stop_gap(direction, bar, active_stop):
                px = float(bar["open"])
                reason = "STOP_GAP"
            else:
                px = float(active_stop)
                reason = "STOP_TOUCH"
            return {
                "eligible": True,
                "exit_timestamp": ts,
                "points": directional(direction, entry, px),
                "reason": reason,
                "initial_risk": risk,
                "proof_timestamp": proof_ts,
                "trail_activated": trail_activated,
                "trail_updates": updates,
                "final_stop": active_stop,
            }

        # Structural lifecycle remains the final hard exit. This is a close
        # event, so it is evaluated after intrabar stop-touch logic.
        if invalid_ts and ts == invalid_ts:
            px = float(bar["close"])
            return {
                "eligible": True,
                "exit_timestamp": ts,
                "points": directional(direction, entry, px),
                "reason": "STRUCTURAL_EXIT",
                "initial_risk": risk,
                "proof_timestamp": proof_ts,
                "trail_activated": trail_activated,
                "trail_updates": updates,
                "final_stop": active_stop,
            }

        # Observe the completed bar. New proof/trailing state applies NEXT BAR.
        history.append((ts, bar))

        if reaches_proof:
            proof_ts = ts
            trail_activated = True

        if trail_activated:
            pivot = latest_confirmed_pivot(history, direction, radius)
            if pivot is not None:
                _, p = pivot
                new_stop = tighten(direction, active_stop, float(p))
                if new_stop != active_stop:
                    active_stop = new_stop
                    updates += 1

    # No earlier stop/invalidation: session-close result at final trusted bar.
    if last_trusted_bar is None:
        return {
            "eligible": True,
            "exit_timestamp": None,
            "points": None,
            "reason": "INCOMPLETE_NO_POST_ENTRY_BAR",
            "initial_risk": risk,
            "proof_timestamp": proof_ts,
            "trail_activated": trail_activated,
            "trail_updates": updates,
            "final_stop": active_stop,
        }

    ts, bar = last_trusted_bar
    return {
        "eligible": True,
        "exit_timestamp": ts,
        "points": directional(direction, entry, float(bar["close"])),
        "reason": "SESSION_CUTOFF",
        "initial_risk": risk,
        "proof_timestamp": proof_ts,
        "trail_activated": trail_activated,
        "trail_updates": updates,
        "final_stop": active_stop,
    }


def opportunity_before_exit(ev, u, result):
    """
    Maximum favorable excursion observed before the exit candle.
    For SESSION_CUTOFF, include the cutoff candle.
    For stop/structural exits, exclude exit candle to avoid intrabar-order bias
    and to match canonical MFE stopping before structural invalidation.
    """
    if result["points"] is None:
        return None

    entry_ts = ev["entry_timestamp"]
    exit_ts = result["exit_timestamp"]
    direction = ev["direction"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])

    include_exit = result["reason"] == "SESSION_CUTOFF"
    best = 0.0

    for ts, bar in sorted_session_rows(u):
        if ts <= entry_ts:
            continue
        if exit_ts:
            if ts > exit_ts:
                break
            if ts == exit_ts and not include_exit:
                break
        best = max(best, favorable_bar_move(direction, entry, bar))

    return best


def max_consecutive_losses(points):
    best = cur = 0
    for p in points:
        if p < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def max_drawdown(points):
    eq = peak = 0.0
    worst = 0.0
    for p in points:
        eq += p
        peak = max(peak, eq)
        worst = min(worst, eq - peak)
    return worst


def summarize(rows):
    eligible = [r for r in rows if r["eligible"]]
    clean = [r for r in eligible if r["points"] is not None]
    amb = [r for r in eligible if r["points"] is None]
    ineligible = [r for r in rows if not r["eligible"]]

    pts = [float(r["points"]) for r in clean]
    wins = [x for x in pts if x > 0]
    losses = [x for x in pts if x < 0]
    flats = [x for x in pts if x == 0]

    return {
        "events": len(rows),
        "eligible": len(eligible),
        "clean": len(clean),
        "ambiguous": len(amb),
        "ineligible": len(ineligible),
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(flats),
        "win_rate_pct": 100 * len(wins) / len(clean) if clean else None,
        "expectancy": mean(pts) if pts else None,
        "total": sum(pts) if pts else None,
        "avg_win": mean(wins) if wins else None,
        "avg_loss": mean(losses) if losses else None,
        "median_win": median(wins) if wins else None,
        "median_loss": median(losses) if losses else None,
        "max_consecutive_losses": max_consecutive_losses(pts),
        "max_drawdown": max_drawdown(pts),
    }


def fmt(x):
    return "-" if x is None else f"{x:+.2f}"


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def runner_stats(rows, threshold):
    opp = [r for r in rows if r["canonical_mfe"] is not None and r["canonical_mfe"] >= threshold]
    clean = [r for r in opp if r["points"] is not None]
    preserved = [
        r for r in clean
        if r["opportunity_before_exit"] is not None
        and r["opportunity_before_exit"] >= threshold
    ]

    captures = []
    givebacks = []
    for r in clean:
        mfe = float(r["canonical_mfe"])
        p = float(r["points"])
        if mfe > 0:
            captures.append(100.0 * p / mfe)
            givebacks.append(mfe - p)

    return {
        "opportunities": len(opp),
        "clean": len(clean),
        "preserved": len(preserved),
        "preserved_pct": 100 * len(preserved) / len(clean) if clean else None,
        "mean_capture_pct": mean(captures) if captures else None,
        "median_capture_pct": median(captures) if captures else None,
        "mean_giveback_points": mean(givebacks) if givebacks else None,
        "median_giveback_points": median(givebacks) if givebacks else None,
    }


def main():
    print("B FAMILY — TRAILING-SL 180-SESSION CHARACTERIZATION V15")
    print("=" * 118)

    c = import_module(CANON, "canonical_b_v15")
    r8 = import_module(V8_2, "risk_v8_2_for_v15")

    framework_files, framework = c.load_framework()
    underlying_files, underlying, dup_conflicts = c.load_underlying()
    futures = c.load_futures()

    sessions = sorted({e["session_date"] for e in framework})
    latest60 = set(sessions[-60:])

    by_session = defaultdict(list)
    for e in framework:
        by_session[e["session_date"]].append(e)

    events = []
    for e in framework:
        d = e["session_date"]
        b = c.family_b_for_event(e, underlying.get(d, {}), futures.get(d, {}))
        if b:
            measured = c.measure_event(dict(b), underlying[d])
            measured["_block"] = "LATEST60" if d in latest60 else "OLDER"
            events.append(measured)

    older = [e for e in events if e["_block"] == "OLDER"]
    dev = [e for e in events if e["_block"] == "LATEST60"]

    parity = (
        len(events) == EXPECTED_TOTAL
        and len(older) == EXPECTED_OLDER
        and len(dev) == EXPECTED_LATEST60
        and dup_conflicts == 0
    )

    print("Framework sessions :", len(sessions))
    print("Canonical B events :", len(events))
    print("Older              :", len(older))
    print("Latest60           :", len(dev))
    print("Duplicate conflicts:", dup_conflicts)
    print("Canonical parity   :", "PASS" if parity else "FAIL")
    print()

    if not parity:
        raise SystemExit("STOP: canonical B parity failed; V15 results would be invalid.")

    model_rows = []

    for ev in events:
        d = ev["session_date"]
        u = underlying[d]
        atr = r8.causal_atr_1m(u, ev["entry_timestamp"])

        # Existing STRUCTURAL baseline.
        ex, pts, reason = r8.structural_result(ev, u)
        base = {
            "session_date": d,
            "block": ev["_block"],
            "direction": ev["direction"],
            "entry_timestamp": ev["entry_timestamp"],
            "origin_timestamp": ev["origin_timestamp"],
            "delay_minutes": ev["delay_minutes"],
            "entry_close": ev.get("entry_close"),
            "atr_1m": atr,
            "canonical_mfe": ev.get("mfe"),
            "canonical_mae": ev.get("mae"),
            "structural_invalidation_timestamp": ev.get("structural_invalidation_timestamp"),
        }

        result = {
            "eligible": True,
            "exit_timestamp": ex,
            "points": pts,
            "reason": reason,
            "initial_risk": None,
            "proof_timestamp": None,
            "trail_activated": False,
            "trail_updates": 0,
            "final_stop": None,
        }
        row = {**base, "model": "STRUCTURAL", **result}
        row["opportunity_before_exit"] = opportunity_before_exit(ev, u, result)
        model_rows.append(row)

        # Existing V8.2 hybrid baseline.
        if atr is None:
            result = {
                "eligible": False,
                "exit_timestamp": None,
                "points": None,
                "reason": "INELIGIBLE_NO_ATR",
                "initial_risk": None,
                "proof_timestamp": None,
                "trail_activated": False,
                "trail_updates": 0,
                "final_stop": None,
            }
        else:
            risk = min(FIXED_CAP, float(atr))
            ex, pts, reason = r8.hybrid_result(ev, u, risk)
            result = {
                "eligible": True,
                "exit_timestamp": ex,
                "points": pts,
                "reason": reason,
                "initial_risk": risk,
                "proof_timestamp": None,
                "trail_activated": False,
                "trail_updates": 0,
                "final_stop": None,
            }
        row = {**base, "model": "HYBRID_MIN15_ATR1_BE20", **result}
        row["opportunity_before_exit"] = opportunity_before_exit(ev, u, result)
        model_rows.append(row)

        # New causal structural trails.
        for name, radius in (
            ("TRAIL_T1_SWING1", 1),
            ("TRAIL_T2_SWING2", 2),
        ):
            result = trail_result(ev, u, atr, radius, c)
            row = {**base, "model": name, **result}
            row["opportunity_before_exit"] = opportunity_before_exit(ev, u, result)
            model_rows.append(row)

    # Common ATR-eligible event IDs for apples-to-apples comparison.
    eligible_ids = {
        (r["session_date"], r["entry_timestamp"])
        for r in model_rows
        if r["model"] == "TRAIL_T1_SWING1" and r["eligible"]
    }

    scopes = {
        "FULL": lambda r: True,
        "OLDER": lambda r: r["block"] == "OLDER",
        "LATEST60": lambda r: r["block"] == "LATEST60",
        "COMMON_ATR_ELIGIBLE": lambda r: (r["session_date"], r["entry_timestamp"]) in eligible_ids,
    }

    report = {
        "version": "B_FAMILY_TRAILING_SL_180_V15",
        "research_only": True,
        "historical_characterization_not_independent_validation": True,
        "canonical_parity": {
            "pass": parity,
            "sessions": len(sessions),
            "events": len(events),
            "older": len(older),
            "latest60": len(dev),
            "duplicate_conflicts": dup_conflicts,
        },
        "definitions": {
            "proof_points": PROOF_POINTS,
            "initial_risk": "min(15, causal 1m Wilder ATR14)",
            "T1": "confirmed 1m swing radius=1; next-bar stop update; never widen; no forced BE",
            "T2": "confirmed 1m swing radius=2; next-bar stop update; never widen; no forced BE",
            "structural_lifecycle": "mandatory",
        },
        "summaries": {},
        "runner_capture": {},
    }

    summary_lines = [
        "B FAMILY — TRAILING-SL 180-SESSION CHARACTERIZATION V15",
        "=" * 118,
        "Canonical detector parity: PASS",
        f"Sessions={len(sessions)}  B events={len(events)}  older={len(older)}  latest60={len(dev)}",
        f"ATR-eligible common events={len(eligible_ids)}",
        "",
        "IMPORTANT: historical characterization only; NOT independent validation.",
        "",
    ]

    runner_rows = []

    for scope_name, pred in scopes.items():
        summary_lines += [scope_name, "-" * 118]
        report["summaries"][scope_name] = {}
        report["runner_capture"][scope_name] = {}

        for model in MODELS:
            rows = [r for r in model_rows if r["model"] == model and pred(r)]
            s = summarize(rows)
            report["summaries"][scope_name][model] = s

            summary_lines.append(
                f"{model:<27} "
                f"events={s['events']} clean={s['clean']} amb={s['ambiguous']} "
                f"inelig={s['ineligible']} W/L/F={s['wins']}/{s['losses']}/{s['flats']} "
                f"exp={fmt(s['expectancy'])} total={fmt(s['total'])} "
                f"avgLoss={fmt(s['avg_loss'])} maxCL={s['max_consecutive_losses']} "
                f"maxDD={fmt(s['max_drawdown'])}"
            )

            report["runner_capture"][scope_name][model] = {}
            for level in RUNNER_LEVELS:
                rs = runner_stats(rows, level)
                report["runner_capture"][scope_name][model][str(level)] = rs
                runner_rows.append(
                    {
                        "scope": scope_name,
                        "model": model,
                        "runner_level": level,
                        **rs,
                    }
                )

        summary_lines.append("")

    summary_lines += [
        "RUNNER PRESERVATION — COMMON ATR-ELIGIBLE",
        "-" * 118,
        "preserved = canonical opportunity level was actually reached before model exit",
    ]

    common_rows = [r for r in model_rows if (r["session_date"], r["entry_timestamp"]) in eligible_ids]
    for level in RUNNER_LEVELS:
        summary_lines.append(f"+{level} opportunity:")
        for model in MODELS:
            rs = runner_stats([r for r in common_rows if r["model"] == model], level)
            summary_lines.append(
                f"  {model:<27} "
                f"preserved={rs['preserved']}/{rs['clean']} "
                f"({('-' if rs['preserved_pct'] is None else f'{rs['preserved_pct']:.1f}%')}) "
                f"medianCapture={('-' if rs['median_capture_pct'] is None else f'{rs['median_capture_pct']:+.1f}%')} "
                f"medianGiveback={fmt(rs['median_giveback_points'])}"
            )

    summary_lines += [
        "",
        "GUARDS",
        "-" * 118,
        "- Do NOT select a production exit from this run alone.",
        "- Same 180 sessions contributed to earlier B discovery/characterization.",
        "- T1/T2 are architecture characterization candidates, not independently validated rules.",
        "- No B entry/VWAP/delay/lifecycle parameter is changed.",
        "- No production/runtime/order code is changed.",
        "- NIFTY underlying points only; not CE/PE premium P&L.",
    ]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENTS_CSV, model_rows)
    write_csv(RUNNERS_CSV, runner_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(summary_lines))

    print("\n".join(summary_lines))
    print()
    print("MODEL EVENTS :", EVENTS_CSV)
    print("RUNNER CSV   :", RUNNERS_CSV)
    print("REPORT JSON  :", REPORT_JSON)
    print("SUMMARY      :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
