#!/usr/bin/env python3
"""
B FAMILY — V50 RECENT UNSEEN-BY-REENTRY VALIDATION

Purpose
-------
Validate the frozen current Family B shadow candidate on the recent post-2026-09-08
historical sessions already present in the repo.

Range:
    2026-09-09 through 2026-09-24

Frozen candidate:
    PRIMARY_OFF
    + CAP20 rescue
    + ONE post-rescue re-entry when, within 20 minutes:
        1m CLOSE retakes degraded-start target
        AND directional futures-VWAP > rescue-time directional futures-VWAP

No tuning.

Why this helps
--------------
The V47 re-entry rule was derived from older rescue events. This recent block was
not used to derive that 20-minute re-entry condition, so it is useful as a small,
more recent robustness check before enabling shadow-live observation.

Important:
- This is still historical validation, not live forward evidence.
- Sample may be small.
- No orders, no quantity, no rupee P&L.
"""

from __future__ import annotations

import csv, json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

START_DATE = "2026-09-09"
END_DATE = "2026-09-24"
REENTRY_WINDOW_MIN = 20

OUTDIR = RESEARCH / "b-family-recent-frozen-reentry-validation-v50"
EVENTS_CSV = OUTDIR / "events-v50.csv"
SCORECARD_CSV = OUTDIR / "scorecard-v50.csv"
REPORT_JSON = OUTDIR / "report-v50.json"
SUMMARY_TXT = OUTDIR / "summary-v50.txt"

ALIASES = {
    "session_date": ("session_date", "date", "trade_date"),
    "direction": ("direction", "side", "signal_direction"),
    "entry_timestamp": ("entry_timestamp", "entry_time", "entry_ts"),
    "entry_close": ("entry_close", "entry_price", "entry_underlying_close"),
    "structural_invalidation_timestamp": (
        "structural_invalidation_timestamp",
        "invalidation_timestamp",
        "structural_exit_timestamp",
        "exit_timestamp",
    ),
    "plus20_timestamp": ("plus20_timestamp", "plus_20_timestamp", "p20_timestamp"),
}

def load_csv(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))

def f(v):
    return None if v in ("", None) else float(v)

def parse_dt(s):
    return datetime.fromisoformat(s)

def plus_minutes(ts, n):
    return (parse_dt(ts) + timedelta(minutes=n)).isoformat()

def mins(a, b):
    return (parse_dt(b) - parse_dt(a)).total_seconds() / 60.0

def in_range(d):
    return START_DATE <= d <= END_DATE

def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price

def favorable(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]

def directional_vwap(direction, row):
    if row is None:
        return None
    raw = row["close"] - row["vwap"]
    return raw if direction == "BULLISH" else -raw

def stats(vals):
    xs = [float(x) for x in vals if x is not None]
    if not xs:
        return dict(n=0, total=None, mean=None, median=None, min=None, max=None)
    return dict(
        n=len(xs), total=sum(xs), mean=mean(xs), median=median(xs),
        min=min(xs), max=max(xs)
    )

def maxdd(vals):
    eq = peak = 0.0
    dd = 0.0
    for x in vals:
        eq += float(x)
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return dd

def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"

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

def first_present(row, names):
    for n in names:
        if n in row and row.get(n) not in ("", None):
            return row.get(n)
    return None

def normalize_event_row(raw):
    r = dict(raw)
    for canon, aliases in ALIASES.items():
        v = first_present(raw, aliases)
        if v not in ("", None):
            r[canon] = v
    d = r.get("session_date")
    direction = str(r.get("direction", "")).upper()
    ets = r.get("entry_timestamp")
    if not d or not ets or direction not in ("BULLISH", "BEARISH"):
        return None
    r["direction"] = direction
    return r

def discover_underlying():
    by = defaultdict(dict)
    for p in ROOT.rglob("*.csv"):
        if "underlying" not in p.name.lower():
            continue
        try:
            rows = load_csv(p)
        except Exception:
            continue
        if not rows or not {"session_date","timestamp","open","high","low","close"}.issubset(rows[0]):
            continue
        for r in rows:
            d = r["session_date"]
            if in_range(d):
                by[d][r["timestamp"]] = {
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                }
    return dict(by)

def discover_futures():
    by = defaultdict(dict)
    for p in ROOT.rglob("*.csv"):
        n = p.name.lower()
        if "futures" not in n or "vwap" not in n:
            continue
        try:
            rows = load_csv(p)
        except Exception:
            continue
        if not rows or not {"session_date","timestamp","close","session_vwap"}.issubset(rows[0]):
            continue
        for r in rows:
            d = r["session_date"]
            if in_range(d) and r.get("session_vwap") not in ("", None):
                by[d][r["timestamp"]] = {
                    "close": float(r["close"]),
                    "vwap": float(r["session_vwap"]),
                }
    return dict(by)

def discover_events():
    found = {}
    for p in RESEARCH.rglob("*.csv"):
        if "v50" in str(p).lower():
            continue
        try:
            rows = load_csv(p)
        except Exception:
            continue
        if not rows:
            continue
        headers = set(rows[0])
        if not any(x in headers for x in ALIASES["session_date"]): continue
        if not any(x in headers for x in ALIASES["direction"]): continue
        if not any(x in headers for x in ALIASES["entry_timestamp"]): continue

        for raw in rows:
            r = normalize_event_row(raw)
            if not r or not in_range(r["session_date"]):
                continue

            event_like = any(
                r.get(x) not in ("", None)
                for x in (
                    "entry_close","structural_invalidation_timestamp",
                    "plus20_timestamp","mfe","mae","candidate","event_type","setup_family"
                )
            )
            name_like = any(
                t in p.name.lower()
                for t in ("event","candidate","setup","family","canonical")
            )
            if not event_like and not name_like:
                continue

            k = (r["session_date"], r["direction"], r["entry_timestamp"])
            richness = sum(
                r.get(x) not in ("", None)
                for x in (
                    "entry_close","structural_invalidation_timestamp",
                    "plus20_timestamp","mfe","mae",
                    "observation_end_timestamp","classification"
                )
            )
            if k not in found or richness > found[k][0]:
                found[k] = (richness, r, str(p))

    return {k:(v[1],v[2]) for k,v in found.items()}

def terminal_for_event(event, u):
    ets = event["entry_timestamp"]
    entry = f(event.get("entry_close"))
    if entry is None:
        if ets not in u:
            return None
        entry = u[ets]["close"]

    invalid = event.get("structural_invalidation_timestamp") or None
    trusted = sorted(u)
    if invalid and invalid in u:
        terminal = invalid
        terminal_type = "STRUCTURAL_INVALIDATION"
    else:
        terminal = trusted[-1]
        terminal_type = "SESSION_CUTOFF"

    baseline = directional(event["direction"], entry, u[terminal]["close"])
    return {
        "entry_close": entry,
        "terminal_timestamp": terminal,
        "terminal_type": terminal_type,
        "baseline_points": baseline,
    }

def find_plus20(event, u, terminal, entry):
    src = event.get("plus20_timestamp")
    if src and src in u and src < terminal:
        return src
    for ts in sorted(u):
        if ts <= event["entry_timestamp"]:
            continue
        if ts >= terminal:
            break
        if directional(event["direction"], entry, favorable(event["direction"], u[ts])) >= 20:
            return ts
    return None

def classify_runner(event, p20, u, fut, entry, terminal):
    cts = plus_minutes(p20, 10)
    if cts >= terminal or p20 not in u or cts not in u:
        return None
    if p20 not in fut or cts not in fut:
        return None

    d = event["direction"]
    net = directional(d, entry, u[cts]["close"]) - directional(d, entry, u[p20]["close"])
    dv = directional_vwap(d, fut[cts]) - directional_vwap(d, fut[p20])

    return {
        "classification_timestamp": cts,
        "net_progress_10m": net,
        "directional_vwap_change_10m": dv,
        "runner_strengthening": net > 0 and dv > 0,
    }

def first_degraded(event, cts, u, fut, entry, terminal):
    d = event["direction"]
    running = None
    prevdv = None
    prior_joint = False

    for ts in sorted(u):
        if ts <= event["entry_timestamp"]:
            continue
        if ts > cts or ts >= terminal:
            break
        move = directional(d, entry, u[ts]["close"])
        running = move if running is None else max(running, move)
        dv = directional_vwap(d, fut.get(ts))
        if dv is not None:
            prevdv = dv

    for ts in sorted(u):
        if ts <= cts:
            continue
        if ts >= terminal:
            break

        move = directional(d, entry, u[ts]["close"])
        running = move if running is None else max(running, move)
        dd = running - move

        dv = directional_vwap(d, fut.get(ts))
        dvc = None if dv is None or prevdv is None else dv - prevdv
        joint = dd > 0 and dvc is not None and dvc < 0

        if joint and not prior_joint:
            return {"degraded_timestamp": ts, "target_move": move}

        prior_joint = joint
        if dv is not None:
            prevdv = dv

    return None

def first_recovery(degraded, event, u, entry, terminal):
    target = degraded["target_move"]
    dts = degraded["degraded_timestamp"]
    for ts in sorted(u):
        if ts <= dts:
            continue
        if ts >= terminal:
            break
        if directional(event["direction"], entry, u[ts]["close"]) > target:
            return ts
    return None

def cap20_rescue(degraded, recovery_ts, event, u, entry, terminal):
    target = degraded["target_move"]
    for ts in sorted(u):
        if ts <= recovery_ts:
            continue
        if ts >= terminal:
            break
        if mins(recovery_ts, ts) < 10:
            continue

        move = directional(event["direction"], entry, u[ts]["close"])
        if move < target:
            return ts if move <= 20 else None
    return None

def frozen_reentry(degraded, rescue_ts, event, u, fut, entry, terminal):
    rescue_dv = directional_vwap(event["direction"], fut.get(rescue_ts))
    if rescue_dv is None:
        return None

    target = degraded["target_move"]

    for ts in sorted(u):
        if ts <= rescue_ts:
            continue
        if ts >= terminal:
            break

        age = mins(rescue_ts, ts)
        if age > REENTRY_WINDOW_MIN:
            break

        move = directional(event["direction"], entry, u[ts]["close"])
        dv = directional_vwap(event["direction"], fut.get(ts))

        if move > target and dv is not None and dv > rescue_dv:
            return ts

    return None

def main():
    print("B FAMILY — V50 RECENT FROZEN RE-ENTRY VALIDATION")
    print("="*118)
    print(f"validation_range={START_DATE}..{END_DATE}")

    uall = discover_underlying()
    fall = discover_futures()
    sessions = sorted(set(uall).intersection(fall))
    events = discover_events()

    print(f"dual_raw_sessions={len(sessions)}")
    print(f"discovered_event_keys={len(events)}")

    if not sessions:
        raise SystemExit("STOP: no dual-valid recent sessions")
    if not events:
        raise SystemExit("STOP: no event rows discovered in V50 range")

    validated = []
    b_count = p20_count = class_count = rs_count = 0

    for _, (event, source) in sorted(
        events.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1])
    ):
        d = event["session_date"]
        if d not in uall or d not in fall:
            continue

        u = uall[d]
        fut = fall[d]
        base = terminal_for_event(event, u)
        if base is None:
            continue

        b_count += 1
        entry = base["entry_close"]
        terminal = base["terminal_timestamp"]

        p20 = find_plus20(event, u, terminal, entry)
        if not p20:
            continue
        p20_count += 1

        cls = classify_runner(event, p20, u, fut, entry, terminal)
        if cls is None:
            continue
        class_count += 1

        if not cls["runner_strengthening"]:
            continue
        rs_count += 1

        degraded = first_degraded(
            event, cls["classification_timestamp"], u, fut, entry, terminal
        )

        cap20_points = base["baseline_points"]
        rescue_ts = None
        reentry_ts = None
        second_leg_points = 0.0

        if degraded:
            recovery = first_recovery(degraded, event, u, entry, terminal)
            if recovery:
                rescue_ts = cap20_rescue(
                    degraded, recovery, event, u, entry, terminal
                )

            if rescue_ts:
                cap20_points = directional(
                    event["direction"], entry, u[rescue_ts]["close"]
                )

                reentry_ts = frozen_reentry(
                    degraded, rescue_ts, event, u, fut, entry, terminal
                )

                if reentry_ts:
                    reentry_price = u[reentry_ts]["close"]
                    second_leg_points = directional(
                        event["direction"],
                        reentry_price,
                        u[terminal]["close"],
                    )

        combined = cap20_points + second_leg_points

        validated.append({
            "session_date": d,
            "direction": event["direction"],
            "entry_timestamp": event["entry_timestamp"],
            "event_source": source,
            "baseline_points": base["baseline_points"],
            "cap20_points": cap20_points,
            "rescue_timestamp": rescue_ts,
            "reentry_timestamp": reentry_ts,
            "reentry_minutes_after_rescue": (
                mins(rescue_ts, reentry_ts)
                if rescue_ts and reentry_ts else None
            ),
            "second_leg_points": (
                second_leg_points if reentry_ts else None
            ),
            "combined_points": combined,
            "delta_cap20_vs_baseline": cap20_points - base["baseline_points"],
            "delta_reentry_vs_cap20": second_leg_points,
            "delta_combined_vs_baseline": combined - base["baseline_points"],
        })

    if not validated:
        raise SystemExit("STOP: no RUNNER_STRENGTHENING events validated")

    baseline = [r["baseline_points"] for r in validated]
    cap20 = [r["cap20_points"] for r in validated]
    combined = [r["combined_points"] for r in validated]

    sb = stats(baseline)
    sc = stats(cap20)
    sr = stats(combined)

    dcap = stats([c-b for c,b in zip(cap20,baseline)])
    dre = stats([r-c for r,c in zip(combined,cap20)])
    dcomb = stats([r-b for r,b in zip(combined,baseline)])

    rescues = [r for r in validated if r["rescue_timestamp"]]
    reentries = [r for r in validated if r["reentry_timestamp"]]

    lines = [
        "B FAMILY — V50 RECENT FROZEN RE-ENTRY VALIDATION",
        "="*118,
        f"validation_range={START_DATE}..{END_DATE}",
        f"dual_raw_sessions={len(sessions)}",
        f"B/event-like rows accepted={b_count}",
        f"events_reaching_plus20={p20_count}",
        f"events_with_complete_V20_classifier={class_count}",
        f"RUNNER_STRENGTHENING_events={rs_count}",
        f"validated_policy_events={len(validated)}",
        "",
        "SCORECARD",
        "-"*118,
        f"BASELINE total={fmt(sb['total'])} mean={fmt(sb['mean'])} "
        f"median={fmt(sb['median'])} worst={fmt(sb['min'])} maxDD={fmt(maxdd(baseline))}",
        f"PRIMARY_OFF+CAP20 total={fmt(sc['total'])} "
        f"Δbase={fmt(dcap['total'])} mean={fmt(sc['mean'])} "
        f"median={fmt(sc['median'])} worst={fmt(sc['min'])} maxDD={fmt(maxdd(cap20))}",
        f"+ FROZEN REENTRY total={fmt(sr['total'])} "
        f"Δbase={fmt(dcomb['total'])} ΔvsCAP20={fmt(dre['total'])} "
        f"mean={fmt(sr['mean'])} median={fmt(sr['median'])} "
        f"worst={fmt(sr['min'])} maxDD={fmt(maxdd(combined))}",
        "",
        "MIX",
        "-"*118,
        f"CAP20_rescues={len(rescues)}",
        f"frozen_reentries={len(reentries)}",
        "",
        "PER RE-ENTRY",
        "-"*118,
    ]

    for r in reentries:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"reentryAfter={fmt(r['reentry_minutes_after_rescue'])}m "
            f"secondLeg={fmt(r['second_leg_points'])} "
            f"ΔvsCAP20={fmt(r['delta_reentry_vs_cap20'])}"
        )

    lines += [
        "",
        "INTERPRETATION GUARDS",
        "-"*118,
        "- V50 performs no tuning.",
        "- The candidate is frozen before this run.",
        "- This is recent historical validation, not live forward evidence.",
        "- Sample size may be small.",
        "- If V50 is neutral/positive, shadow-live observation becomes the next sensible step.",
        "- Underlying NIFTY directional points only.",
    ]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENTS_CSV, validated)
    write_csv(SCORECARD_CSV, [
        {
            "policy":"BASELINE",
            "n":len(validated),
            "total_points":sb["total"],
            "mean_points":sb["mean"],
            "median_points":sb["median"],
            "worst_points":sb["min"],
            "max_drawdown_points":maxdd(baseline),
        },
        {
            "policy":"PRIMARY_OFF_CAP20",
            "n":len(validated),
            "total_points":sc["total"],
            "delta_vs_baseline_total":dcap["total"],
            "max_drawdown_points":maxdd(cap20),
        },
        {
            "policy":"PRIMARY_OFF_CAP20_PLUS_REENTRY",
            "n":len(validated),
            "total_points":sr["total"],
            "delta_vs_baseline_total":dcomb["total"],
            "delta_vs_cap20_total":dre["total"],
            "max_drawdown_points":maxdd(combined),
        },
    ])

    REPORT_JSON.write_text(json.dumps({
        "version":"V50",
        "range":{"start":START_DATE,"end":END_DATE},
        "dual_raw_sessions":len(sessions),
        "validated_events":len(validated),
        "rescue_count":len(rescues),
        "reentry_count":len(reentries),
        "scorecard":{
            "baseline":sb,
            "cap20":sc,
            "combined":sr,
            "delta_cap20_vs_baseline":dcap,
            "delta_reentry_vs_cap20":dre,
            "delta_combined_vs_baseline":dcomb,
        },
        "methodology":{
            "tuning_grid":False,
            "candidate_frozen_before_run":True,
            "live_forward_evidence":False,
        },
    }, indent=2))

    SUMMARY_TXT.write_text("\n".join(lines)+"\n")

    print()
    print("\n".join(lines))
    print()
    print("EVENTS CSV  :", EVENTS_CSV)
    print("SCORECARD   :", SCORECARD_CSV)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)

if __name__ == "__main__":
    main()
