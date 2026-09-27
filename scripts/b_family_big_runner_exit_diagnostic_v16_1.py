#!/usr/bin/env python3
"""
B FAMILY — BIG-RUNNER EXIT DIAGNOSTIC V16.1

Purpose
-------
Diagnose WHY the V15 T1/T2 structural trailing stops cut some large Family-B
runners early.

Scope
-----
- Canonical 180-session Family-B universe.
- Exact frozen Family-B detector unchanged.
- Select only canonical B events whose structural-lifecycle MFE >= +75 points.
- NO parameter tuning.
- NO new exit selection.
- Underlying NIFTY points only, not option-premium P&L.

For each >=75-point canonical runner, report:
- entry/origin/delay/direction
- causal ATR and initial risk=min(15, ATR1)
- first +20 / +30 / +50 / +75 / +100 timestamps
- structural invalidation timestamp
- existing V8.2 hybrid result
- T1 and T2:
    proof timestamp
    every causal confirmed swing
    every stop update
    exit timestamp/reason/points
- post-exit maximum favorable move and missed runner extension

T1 = radius-1 confirmed 1m swing
T2 = radius-2 confirmed 1m swing
Newly confirmed stop applies NEXT BAR only.
Stop never widens.
No forced breakeven in T1/T2.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V8_2 = Path("scripts/b_family_risk_model_comparison_v8_2.py")

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-big-runner-exit-diagnostic-v16"
)
RUNNERS_CSV = OUTDIR / "runner-events-v16.csv"
TIMELINE_CSV = OUTDIR / "runner-timeline-v16.csv"
REPORT_JSON = OUTDIR / "report-v16.json"
SUMMARY_TXT = OUTDIR / "summary-v16.txt"

EXPECTED_B_TOTAL = 45
EXPECTED_RUNNERS_75 = 12
PROOF = 20.0
INITIAL_CAP = 15.0
MILESTONES = (20, 30, 50, 75, 100)


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable_move(direction, entry, bar):
    px = bar["high"] if direction == "BULLISH" else bar["low"]
    return directional(direction, entry, px)


def adverse_move(direction, entry, bar):
    px = bar["low"] if direction == "BULLISH" else bar["high"]
    return directional(direction, entry, px)


def initial_stop(direction, entry, risk):
    return entry - risk if direction == "BULLISH" else entry + risk


def stop_hit(direction, bar, stop):
    return bar["low"] <= stop if direction == "BULLISH" else bar["high"] >= stop


def stop_gap(direction, bar, stop):
    return bar["open"] <= stop if direction == "BULLISH" else bar["open"] >= stop


def tighten(direction, current, candidate):
    if direction == "BULLISH":
        return max(current, candidate)
    return min(current, candidate)


def confirmed_pivot(history, direction, radius):
    """
    Return latest causally confirmed pivot using strict extrema.
    history contains completed bars up through current bar.
    """
    n = len(history)
    if n < 2 * radius + 1:
        return None

    latest = None
    last_candidate = n - 1 - radius

    for i in range(radius, last_candidate + 1):
        ts, cand = history[i]
        window = history[i - radius : i + radius + 1]

        if direction == "BULLISH":
            p = float(cand["low"])
            others = [
                float(b["low"])
                for j, (_, b) in enumerate(window)
                if j != radius
            ]
            if all(p < x for x in others):
                latest = (ts, p)
        else:
            p = float(cand["high"])
            others = [
                float(b["high"])
                for j, (_, b) in enumerate(window)
                if j != radius
            ]
            if all(p > x for x in others):
                latest = (ts, p)

    return latest


def first_milestones(ev, u):
    entry_ts = ev["entry_timestamp"]
    direction = ev["direction"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])
    out = {x: None for x in MILESTONES}

    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if not ts[:10] == ev["session_date"]:
            continue
        if ts[11:16] > "15:14":
            continue
        m = favorable_move(direction, entry, u[ts])
        for level in MILESTONES:
            if out[level] is None and m >= level:
                out[level] = ts

    return out


def max_favorable_after(ev, u, after_ts):
    entry_ts = ev["entry_timestamp"]
    direction = ev["direction"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])

    best = None
    best_ts = None
    for ts in sorted(u):
        if ts <= after_ts or ts <= entry_ts:
            continue
        if ts[11:16] > "15:14":
            continue
        m = favorable_move(direction, entry, u[ts])
        if best is None or m > best:
            best = m
            best_ts = ts
    return best, best_ts


def replay_trail(ev, u, atr, radius, canon):
    direction = ev["direction"]
    entry_ts = ev["entry_timestamp"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])

    if atr is None:
        return {
            "eligible": False,
            "exit_timestamp": None,
            "exit_reason": "INELIGIBLE_NO_ATR",
            "points": None,
            "proof_timestamp": None,
            "initial_risk": None,
            "initial_stop": None,
            "final_stop": None,
            "trail_updates": 0,
            "timeline": [],
        }

    risk = min(INITIAL_CAP, float(atr))
    active_stop = initial_stop(direction, entry, risk)
    proof_ts = None
    trail_active = False
    trail_updates = 0
    invalid_ts = ev.get("structural_invalidation_timestamp")

    rows = [(ts, u[ts]) for ts in sorted(u) if canon.is_trusted(ts)]
    history = []
    started = False
    timeline = []
    last_trusted = None
    last_pivot_key = None

    for ts, bar in rows:
        if ts < entry_ts:
            continue

        if ts == entry_ts:
            history.append((ts, bar))
            started = True
            timeline.append({
                "timestamp": ts,
                "event_type": "ENTRY",
                "radius": radius,
                "price": entry,
                "stop_before": active_stop,
                "stop_after": active_stop,
                "favorable_move": 0.0,
                "adverse_move": 0.0,
                "note": f"initial_risk={risk:.4f}",
            })
            continue

        if not started:
            continue

        last_trusted = (ts, bar)
        fav = favorable_move(direction, entry, bar)
        adv = adverse_move(direction, entry, bar)
        hit = stop_hit(direction, bar, active_stop)
        reaches_proof = proof_ts is None and fav >= PROOF

        timeline.append({
            "timestamp": ts,
            "event_type": "BAR",
            "radius": radius,
            "price": float(bar["close"]),
            "stop_before": active_stop,
            "stop_after": active_stop,
            "favorable_move": fav,
            "adverse_move": adv,
            "note": "",
        })

        if reaches_proof and hit:
            timeline.append({
                "timestamp": ts,
                "event_type": "AMBIGUOUS_PROOF_AND_STOP",
                "radius": radius,
                "price": None,
                "stop_before": active_stop,
                "stop_after": active_stop,
                "favorable_move": fav,
                "adverse_move": adv,
                "note": "same 1m bar",
            })
            return {
                "eligible": True,
                "exit_timestamp": ts,
                "exit_reason": "AMBIGUOUS_PROOF_AND_STOP_SAME_BAR",
                "points": None,
                "proof_timestamp": ts,
                "initial_risk": risk,
                "initial_stop": initial_stop(direction, entry, risk),
                "final_stop": active_stop,
                "trail_updates": trail_updates,
                "timeline": timeline,
            }

        # Existing stop is active for entire current bar.
        if hit:
            if stop_gap(direction, bar, active_stop):
                px = float(bar["open"])
                reason = "STOP_GAP"
            else:
                px = float(active_stop)
                reason = "STOP_TOUCH"

            pts = directional(direction, entry, px)
            timeline.append({
                "timestamp": ts,
                "event_type": "EXIT",
                "radius": radius,
                "price": px,
                "stop_before": active_stop,
                "stop_after": active_stop,
                "favorable_move": fav,
                "adverse_move": adv,
                "note": reason,
            })
            return {
                "eligible": True,
                "exit_timestamp": ts,
                "exit_reason": reason,
                "points": pts,
                "proof_timestamp": proof_ts,
                "initial_risk": risk,
                "initial_stop": initial_stop(direction, entry, risk),
                "final_stop": active_stop,
                "trail_updates": trail_updates,
                "timeline": timeline,
            }

        if invalid_ts and ts == invalid_ts:
            px = float(bar["close"])
            pts = directional(direction, entry, px)
            timeline.append({
                "timestamp": ts,
                "event_type": "EXIT",
                "radius": radius,
                "price": px,
                "stop_before": active_stop,
                "stop_after": active_stop,
                "favorable_move": fav,
                "adverse_move": adv,
                "note": "STRUCTURAL_EXIT",
            })
            return {
                "eligible": True,
                "exit_timestamp": ts,
                "exit_reason": "STRUCTURAL_EXIT",
                "points": pts,
                "proof_timestamp": proof_ts,
                "initial_risk": risk,
                "initial_stop": initial_stop(direction, entry, risk),
                "final_stop": active_stop,
                "trail_updates": trail_updates,
                "timeline": timeline,
            }

        # Current bar completes. New proof/trail applies NEXT BAR.
        history.append((ts, bar))

        if reaches_proof:
            proof_ts = ts
            trail_active = True
            timeline.append({
                "timestamp": ts,
                "event_type": "PROOF_20",
                "radius": radius,
                "price": None,
                "stop_before": active_stop,
                "stop_after": active_stop,
                "favorable_move": fav,
                "adverse_move": adv,
                "note": "trail activation begins next bar",
            })

        if trail_active:
            pivot = confirmed_pivot(history, direction, radius)
            if pivot is not None:
                pivot_ts, pivot_price = pivot
                pivot_key = (pivot_ts, pivot_price)
                if pivot_key != last_pivot_key:
                    last_pivot_key = pivot_key
                    timeline.append({
                        "timestamp": ts,
                        "event_type": "PIVOT_CONFIRMED",
                        "radius": radius,
                        "price": pivot_price,
                        "stop_before": active_stop,
                        "stop_after": active_stop,
                        "favorable_move": fav,
                        "adverse_move": adv,
                        "note": f"pivot_timestamp={pivot_ts}",
                    })

                new_stop = tighten(direction, active_stop, float(pivot_price))
                if new_stop != active_stop:
                    old = active_stop
                    active_stop = new_stop
                    trail_updates += 1
                    timeline.append({
                        "timestamp": ts,
                        "event_type": "STOP_UPDATE",
                        "radius": radius,
                        "price": pivot_price,
                        "stop_before": old,
                        "stop_after": active_stop,
                        "favorable_move": fav,
                        "adverse_move": adv,
                        "note": f"confirmed_pivot={pivot_ts}; applies next bar",
                    })

    if last_trusted is None:
        return {
            "eligible": True,
            "exit_timestamp": None,
            "exit_reason": "INCOMPLETE_NO_POST_ENTRY_BAR",
            "points": None,
            "proof_timestamp": proof_ts,
            "initial_risk": risk,
            "initial_stop": initial_stop(direction, entry, risk),
            "final_stop": active_stop,
            "trail_updates": trail_updates,
            "timeline": timeline,
        }

    ts, bar = last_trusted
    px = float(bar["close"])
    pts = directional(direction, entry, px)
    timeline.append({
        "timestamp": ts,
        "event_type": "EXIT",
        "radius": radius,
        "price": px,
        "stop_before": active_stop,
        "stop_after": active_stop,
        "favorable_move": favorable_move(direction, entry, bar),
        "adverse_move": adverse_move(direction, entry, bar),
        "note": "SESSION_CUTOFF",
    })
    return {
        "eligible": True,
        "exit_timestamp": ts,
        "exit_reason": "SESSION_CUTOFF",
        "points": pts,
        "proof_timestamp": proof_ts,
        "initial_risk": risk,
        "initial_stop": initial_stop(direction, entry, risk),
        "final_stop": active_stop,
        "trail_updates": trail_updates,
        "timeline": timeline,
    }


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


def fmt(x):
    return "-" if x is None else f"{x:+.2f}"


def main():
    print("B FAMILY — BIG-RUNNER EXIT DIAGNOSTIC V16.1")
    print("=" * 118)

    c = import_module(CANON, "canonical_b_v16")
    r8 = import_module(V8_2, "risk_v8_2_v16")

    framework_files, framework = c.load_framework()
    underlying_files, underlying, dup_conflicts = c.load_underlying()
    futures = c.load_futures()

    sessions = sorted({e["session_date"] for e in framework})
    latest60 = set(sessions[-60:])

    events = []
    for e in framework:
        d = e["session_date"]
        b = c.family_b_for_event(e, underlying.get(d, {}), futures.get(d, {}))
        if b:
            measured = c.measure_event(dict(b), underlying[d])
            measured["_block"] = "LATEST60" if d in latest60 else "OLDER"
            events.append(measured)

    if len(events) != EXPECTED_B_TOTAL or dup_conflicts != 0:
        raise SystemExit(
            f"STOP: canonical parity failed: events={len(events)}, "
            f"dup_conflicts={dup_conflicts}"
        )

    runners = [
        e for e in events
        if e.get("mfe") is not None and float(e["mfe"]) >= 75.0
    ]

    print("Canonical B events :", len(events))
    print(">=75 runners       :", len(runners))
    print("Expected runners   :", EXPECTED_RUNNERS_75)
    print("Duplicate conflicts:", dup_conflicts)
    print()

    if len(runners) != EXPECTED_RUNNERS_75:
        raise SystemExit(
            "STOP: >=75 runner parity differs from V15 expectation."
        )

    runner_rows = []
    timeline_rows = []
    report_runners = []

    for idx, ev in enumerate(runners, start=1):
        d = ev["session_date"]
        u = underlying[d]
        atr = r8.causal_atr_1m(u, ev["entry_timestamp"])
        milestones = first_milestones(ev, u)

        # Existing V8.2 hybrid.
        if atr is None:
            hybrid = {
                "eligible": False,
                "exit_timestamp": None,
                "points": None,
                "reason": "INELIGIBLE_NO_ATR",
                "risk": None,
            }
        else:
            risk = min(INITIAL_CAP, float(atr))
            hx, hp, hr = r8.hybrid_result(ev, u, risk)
            hybrid = {
                "eligible": True,
                "exit_timestamp": hx,
                "points": hp,
                "reason": hr,
                "risk": risk,
            }

        t1 = replay_trail(ev, u, atr, 1, c)
        t2 = replay_trail(ev, u, atr, 2, c)

        t1_post, t1_post_ts = (
            max_favorable_after(ev, u, t1["exit_timestamp"])
            if t1["exit_timestamp"] else (None, None)
        )
        t2_post, t2_post_ts = (
            max_favorable_after(ev, u, t2["exit_timestamp"])
            if t2["exit_timestamp"] else (None, None)
        )

        row = {
            "runner_id": idx,
            "session_date": d,
            "block": ev["_block"],
            "direction": ev["direction"],
            "origin_timestamp": ev["origin_timestamp"],
            "entry_timestamp": ev["entry_timestamp"],
            "delay_minutes": ev["delay_minutes"],
            "entry_close": ev.get("entry_close"),
            "entry_fut_vwap": ev.get("entry_fut_vwap"),
            "atr_1m": atr,
            "canonical_mfe": ev.get("mfe"),
            "canonical_mae": ev.get("mae"),
            "structural_invalidation_timestamp": ev.get(
                "structural_invalidation_timestamp"
            ),
            "plus20_timestamp": milestones[20],
            "plus30_timestamp": milestones[30],
            "plus50_timestamp": milestones[50],
            "plus75_timestamp": milestones[75],
            "plus100_timestamp": milestones[100],
            "hybrid_exit_timestamp": hybrid["exit_timestamp"],
            "hybrid_exit_reason": hybrid["reason"],
            "hybrid_points": hybrid["points"],
            "t1_proof_timestamp": t1["proof_timestamp"],
            "t1_exit_timestamp": t1["exit_timestamp"],
            "t1_exit_reason": t1["exit_reason"],
            "t1_points": t1["points"],
            "t1_updates": t1["trail_updates"],
            "t1_final_stop": t1["final_stop"],
            "t1_post_exit_best_move": t1_post,
            "t1_post_exit_best_timestamp": t1_post_ts,
            "t1_missed_extension": (
                float(ev["mfe"]) - float(t1["points"])
                if t1["points"] is not None else None
            ),
            "t2_proof_timestamp": t2["proof_timestamp"],
            "t2_exit_timestamp": t2["exit_timestamp"],
            "t2_exit_reason": t2["exit_reason"],
            "t2_points": t2["points"],
            "t2_updates": t2["trail_updates"],
            "t2_final_stop": t2["final_stop"],
            "t2_post_exit_best_move": t2_post,
            "t2_post_exit_best_timestamp": t2_post_ts,
            "t2_missed_extension": (
                float(ev["mfe"]) - float(t2["points"])
                if t2["points"] is not None else None
            ),
        }
        runner_rows.append(row)

        for model_name, result in (("T1", t1), ("T2", t2)):
            for rec in result["timeline"]:
                timeline_rows.append({
                    "runner_id": idx,
                    "session_date": d,
                    "direction": ev["direction"],
                    "model": model_name,
                    **rec,
                })

        report_runners.append({
            "runner": row,
            "t1_timeline": t1["timeline"],
            "t2_timeline": t2["timeline"],
        })

        print("=" * 118)
        print(
            f"RUNNER {idx}: {d} {ev['direction']} "
            f"entry={ev['entry_timestamp'][11:16]} "
            f"MFE={fmt(ev.get('mfe'))} MAE={fmt(ev.get('mae'))}"
        )
        print(
            "Milestones:",
            " ".join(
                f"+{m}={milestones[m][11:16] if milestones[m] else '-'}"
                for m in MILESTONES
            ),
        )
        print(
            f"Hybrid: exit={str(hybrid['exit_timestamp'])[11:16] if hybrid['exit_timestamp'] else '-'} "
            f"reason={hybrid['reason']} points={fmt(hybrid['points'])}"
        )
        print(
            f"T1: proof={str(t1['proof_timestamp'])[11:16] if t1['proof_timestamp'] else '-'} "
            f"updates={t1['trail_updates']} "
            f"exit={str(t1['exit_timestamp'])[11:16] if t1['exit_timestamp'] else '-'} "
            f"reason={t1['exit_reason']} points={fmt(t1['points'])} "
            f"postExitBest={fmt(t1_post)}"
        )
        print(
            f"T2: proof={str(t2['proof_timestamp'])[11:16] if t2['proof_timestamp'] else '-'} "
            f"updates={t2['trail_updates']} "
            f"exit={str(t2['exit_timestamp'])[11:16] if t2['exit_timestamp'] else '-'} "
            f"reason={t2['exit_reason']} points={fmt(t2['points'])} "
            f"postExitBest={fmt(t2_post)}"
        )

    # Aggregate mechanism diagnostics.
    def clean_points(key):
        return [float(r[key]) for r in runner_rows if r[key] is not None]

    def count_before(level_key, exit_key):
        n = 0
        for r in runner_rows:
            milestone = r[level_key]
            ex = r[exit_key]
            if milestone and ex and ex < milestone:
                n += 1
        return n

    summary = [
        "B FAMILY — BIG-RUNNER EXIT DIAGNOSTIC V16.1",
        "=" * 118,
        f"Canonical B events = {len(events)}",
        f"Canonical >=75 runners = {len(runners)}",
        "",
        "NO OPTIMIZATION WAS PERFORMED.",
        "",
        "AGGREGATE BIG-RUNNER DIAGNOSTIC",
        "-" * 118,
        f"T1 exited before +75 on {count_before('plus75_timestamp','t1_exit_timestamp')}/{len(runner_rows)} runners",
        f"T2 exited before +75 on {count_before('plus75_timestamp','t2_exit_timestamp')}/{len(runner_rows)} runners",
        f"T1 exited before +100 on {count_before('plus100_timestamp','t1_exit_timestamp')}/{sum(1 for r in runner_rows if r['plus100_timestamp'])} +100-capable runners",
        f"T2 exited before +100 on {count_before('plus100_timestamp','t2_exit_timestamp')}/{sum(1 for r in runner_rows if r['plus100_timestamp'])} +100-capable runners",
        "",
        f"T1 median realized points on runners = {fmt(median(clean_points('t1_points')) if clean_points('t1_points') else None)}",
        f"T2 median realized points on runners = {fmt(median(clean_points('t2_points')) if clean_points('t2_points') else None)}",
        f"T1 median missed extension = {fmt(median(clean_points('t1_missed_extension')) if clean_points('t1_missed_extension') else None)}",
        f"T2 median missed extension = {fmt(median(clean_points('t2_missed_extension')) if clean_points('t2_missed_extension') else None)}",
        "",
        "PER-RUNNER",
        "-" * 118,
    ]

    for r in runner_rows:
        summary.append(
            f"{r['session_date']} {r['direction']:<7} "
            f"MFE={fmt(r['canonical_mfe'])} "
            f"+20={r['plus20_timestamp'][11:16] if r['plus20_timestamp'] else '-'} "
            f"+50={r['plus50_timestamp'][11:16] if r['plus50_timestamp'] else '-'} "
            f"+75={r['plus75_timestamp'][11:16] if r['plus75_timestamp'] else '-'} "
            f"+100={r['plus100_timestamp'][11:16] if r['plus100_timestamp'] else '-'} | "
            f"T1={fmt(r['t1_points'])}@{r['t1_exit_timestamp'][11:16] if r['t1_exit_timestamp'] else '-'} "
            f"({r['t1_updates']} updates) | "
            f"T2={fmt(r['t2_points'])}@{r['t2_exit_timestamp'][11:16] if r['t2_exit_timestamp'] else '-'} "
            f"({r['t2_updates']} updates)"
        )

    summary += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- This run diagnoses the already-defined T1/T2 behavior only.",
        "- Do not create T3/T4 thresholds from this output and call them validated.",
        "- Same historical 180-session universe; not independent validation.",
        "- Any new runner-preservation architecture derived from V16 must be frozen first, then tested forward.",
        "- Underlying NIFTY points only, not CE/PE premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_BIG_RUNNER_EXIT_DIAGNOSTIC_V16_1",
        "canonical_b_events": len(events),
        "runner_threshold": 75,
        "runner_count": len(runners),
        "no_optimization": True,
        "runners": report_runners,
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(RUNNERS_CSV, runner_rows)
    write_csv(TIMELINE_CSV, timeline_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(summary))

    print()
    print("\n".join(summary))
    print()
    print("RUNNERS CSV :", RUNNERS_CSV)
    print("TIMELINE CSV:", TIMELINE_CSV)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
