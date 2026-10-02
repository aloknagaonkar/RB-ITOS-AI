#!/usr/bin/env python3
"""
B FAMILY — INDEPENDENT HISTORICAL VALIDATION V6

Purpose
-------
Take the already-frozen B definition and the already-defined post-entry
WARNING / RECOVERY diagnostics out of the 60-session development sample.

This script does TWO stages:

1) PARITY GATE
   Reconstruct B from raw NIFTY 1m + futures VWAP on the known 60-session
   sample and compare reconstructed B (date/direction/timestamp) with the
   existing frozen 60-session B event CSV.
   If parity is not exact, ABORT. Do not trust the older-session result.

2) OLDER-SAMPLE VALIDATION
   Apply the exact same reconstructed B logic to sessions strictly before
   2026-06-16. No threshold tuning is performed.

Frozen B definition implemented
-------------------------------
Opening structure:
- Ignore 09:15-09:19.
- From completed 5m bars beginning 09:20:
  * first RED bar becomes RED reference
  * first GREEN bar becomes GREEN reference
- RED midpoint close-break downward, then RED low close-break downward.
- GREEN midpoint close-break upward, then GREEN high close-break upward.

Candidate A at structural boundary:
BULL: current FUT-VWAP > +5 AND T-5..T contains at least one <= +5.
BEAR: current FUT-VWAP < -5 AND T-5..T contains at least one >= -5.

B:
- Original structural boundary event exists.
- Candidate A is NOT valid on the original boundary minute.
- Parent structure remains alive (midpoint not reclaimed against direction).
- First later minute satisfying full Candidate-A condition becomes B.

Post-entry diagnostics carried forward unchanged
------------------------------------------------
WARNING:
- structural boundary reclaimed and/or futures crosses to wrong VWAP side,
  while midpoint remains intact.

RECOVERY:
- after warning, original boundary is re-broken in B direction AND futures
  returns to correct VWAP side before midpoint invalidation.

INVALIDATION:
- bullish: close < GREEN midpoint
- bearish: close > RED midpoint

3-minute candidate:
- descriptive only; no production rule is frozen.

Important scope note
--------------------
The older sample is independent of the B post-entry management tuning done on
the latest 60-session sample. It is NOT globally pristine with respect to all
earlier Candidate-A/opening-framework research.

Research only. No runtime/execution changes.
"""

from __future__ import annotations

import csv
import glob
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

ROOT = Path("data/historical-evidence")
KNOWN_EVENTS = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-setup-family-60-session-validation-v1-1"
    / "setup-family-events-v1-1.csv"
)
FUTURES = ROOT / "midpoint-v2-nifty-futures-vwap-v1-all180.csv"

OUT = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "b-family-independent-historical-validation-v6"
)
EVENT_CSV = OUT / "b-family-independent-events-v6.csv"
SUMMARY_TXT = OUT / "b-family-independent-summary-v6.txt"
PARITY_CSV = OUT / "b-family-parity-v6.csv"

DEV_START = "2026-06-16"
TRUSTED_END = "15:14"
A_THRESHOLD = 5.0


def num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except Exception:
        return None


def dmove(direction, entry, later):
    if entry is None or later is None:
        return None
    return later - entry if direction == "BULLISH" else entry - later


def minutes(a, b):
    if not a or not b:
        return None
    return int(
        (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() // 60
    )


def med(vals):
    vals = [x for x in vals if x is not None]
    return median(vals) if vals else None


def percentile(values, p):
    vals = sorted(x for x in values if x is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    frac = pos - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def load_underlying():
    """
    Returns:
      day -> timestamp -> OHLC
    """
    out = {}
    seen = set()
    patterns = (
        str(ROOT / "underlying-ohlc-*.csv"),
        str(ROOT / "**" / "underlying-ohlc-*.csv"),
    )

    for pattern in patterns:
        for p in sorted(glob.glob(pattern, recursive=True)):
            if p in seen:
                continue
            seen.add(p)
            try:
                with open(p, newline="") as f:
                    for r in csv.DictReader(f):
                        day = r.get("session_date")
                        ts = r.get("timestamp")
                        if not day or not ts:
                            continue
                        bar = {
                            "open": num(r.get("open")),
                            "high": num(r.get("high")),
                            "low": num(r.get("low")),
                            "close": num(r.get("close")),
                        }
                        if None not in bar.values():
                            out.setdefault(day, {})[ts] = bar
            except Exception:
                pass

    return out


def load_futures():
    out = {}
    with open(FUTURES, newline="") as f:
        for r in csv.DictReader(f):
            day = r.get("session_date")
            ts = r.get("timestamp")
            close = num(r.get("close"))
            vwap = num(r.get("session_vwap") or r.get("vwap"))
            if day and ts and close is not None and vwap is not None:
                out.setdefault(day, {})[ts] = {
                    "close": close,
                    "vwap": vwap,
                    "diff": close - vwap,
                }
    return out


def five_minute_bars(daybars):
    """
    Build exact 5m blocks 09:20-09:24, 09:25-09:29, ...
    from five complete 1m bars only.
    """
    result = []

    times = sorted(
        ts for ts in daybars
        if "09:20" <= ts[11:16] <= "15:14"
    )
    if not times:
        return result

    day = times[0][:10]
    tz = times[0][19:] if len(times[0]) > 19 else "+05:30"

    start = datetime.fromisoformat(f"{day}T09:20:00{tz}")
    end = datetime.fromisoformat(f"{day}T15:15:00{tz}")

    cur = start
    while cur < end:
        stamps = [(cur + timedelta(minutes=i)).isoformat() for i in range(5)]
        if all(s in daybars for s in stamps):
            bars = [daybars[s] for s in stamps]
            result.append({
                "start": stamps[0],
                "end": stamps[-1],
                "open": bars[0]["open"],
                "high": max(b["high"] for b in bars),
                "low": min(b["low"] for b in bars),
                "close": bars[-1]["close"],
            })
        cur += timedelta(minutes=5)

    return result


def first_reference(daybars, colour):
    for b in five_minute_bars(daybars):
        if colour == "GREEN" and b["close"] > b["open"]:
            return b
        if colour == "RED" and b["close"] < b["open"]:
            return b
    return None


def build_structure(daybars, colour):
    ref = first_reference(daybars, colour)
    if not ref:
        return None

    high, low = ref["high"], ref["low"]
    mid = (high + low) / 2.0
    direction = "BULLISH" if colour == "GREEN" else "BEARISH"

    after = sorted(
        ts for ts in daybars
        if ts > ref["end"] and ts[11:16] <= TRUSTED_END
    )

    mid_break = None
    boundary_break = None

    for ts in after:
        c = daybars[ts]["close"]

        if mid_break is None:
            if direction == "BULLISH" and c > mid:
                mid_break = ts
            elif direction == "BEARISH" and c < mid:
                mid_break = ts
            continue

        if direction == "BULLISH" and c > high:
            boundary_break = ts
            break
        if direction == "BEARISH" and c < low:
            boundary_break = ts
            break

    return {
        "colour": colour,
        "direction": direction,
        "reference_start": ref["start"],
        "reference_end": ref["end"],
        "high": high,
        "low": low,
        "mid": mid,
        "mid_break": mid_break,
        "boundary_break": boundary_break,
    }


def candidate_a(direction, stamp, futures_day):
    if stamp not in futures_day:
        return False

    cur = futures_day[stamp]["diff"]
    d = datetime.fromisoformat(stamp)
    window = []

    for back in range(5, -1, -1):
        t = (d - timedelta(minutes=back)).isoformat()
        if t in futures_day:
            window.append(futures_day[t]["diff"])

    if direction == "BULLISH":
        return cur > A_THRESHOLD and any(x <= A_THRESHOLD for x in window)

    return cur < -A_THRESHOLD and any(x >= -A_THRESHOLD for x in window)


def midpoint_alive(direction, close, mid):
    if direction == "BULLISH":
        return close >= mid
    return close <= mid


def detect_b_for_structure(day, s, daybars, futures_day):
    """
    One B max per opening structure.
    """
    bb = s["boundary_break"]
    if not bb or bb not in daybars or bb not in futures_day:
        return None

    # Original Candidate A means this is A, not delayed B.
    if candidate_a(s["direction"], bb, futures_day):
        return None

    for stamp in sorted(ts for ts in daybars if ts > bb and ts[11:16] <= TRUSTED_END):
        if stamp not in futures_day:
            continue

        close = daybars[stamp]["close"]

        if not midpoint_alive(s["direction"], close, s["mid"]):
            return None

        if candidate_a(s["direction"], stamp, futures_day):
            return {
                "session_date": day,
                "direction": s["direction"],
                "entry_timestamp": stamp,
                "entry_close": close,
                "entry_fut_vwap": futures_day[stamp]["diff"],
                "reference_colour": s["colour"],
                "reference_start": s["reference_start"],
                "reference_end": s["reference_end"],
                "reference_high": s["high"],
                "reference_low": s["low"],
                "reference_midpoint": s["mid"],
                "midpoint_break_timestamp": s["mid_break"],
                "boundary_break_timestamp": s["boundary_break"],
            }

    return None


def reconstruct_all(under, fut):
    events = []
    common_days = sorted(set(under).intersection(fut))

    for day in common_days:
        for colour in ("RED", "GREEN"):
            s = build_structure(under[day], colour)
            if not s:
                continue
            ev = detect_b_for_structure(day, s, under[day], fut[day])
            if ev:
                events.append(ev)

    return sorted(events, key=lambda r: (r["session_date"], r["entry_timestamp"], r["direction"]))


def known_60_b():
    rows = list(csv.DictReader(open(KNOWN_EVENTS, newline="")))
    return sorted(
        [
            {
                "session_date": r["session_date"],
                "direction": r["direction"],
                "entry_timestamp": r["entry_timestamp"],
            }
            for r in rows
            if r.get("family") == "B_DELAYED_FULL_CANDIDATE_A"
        ],
        key=lambda r: (r["session_date"], r["entry_timestamp"], r["direction"]),
    )


def parity_gate(reconstructed, known):
    known_set = {
        (r["session_date"], r["direction"], r["entry_timestamp"])
        for r in known
    }
    recon_dev = [
        r for r in reconstructed
        if r["session_date"] >= DEV_START
    ]
    recon_set = {
        (r["session_date"], r["direction"], r["entry_timestamp"])
        for r in recon_dev
    }

    missing = sorted(known_set - recon_set)
    extra = sorted(recon_set - known_set)

    OUT.mkdir(parents=True, exist_ok=True)
    with open(PARITY_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["status", "session_date", "direction", "entry_timestamp"])
        for x in missing:
            w.writerow(["MISSING_FROM_RECONSTRUCTION", *x])
        for x in extra:
            w.writerow(["EXTRA_IN_RECONSTRUCTION", *x])

    return len(missing) == 0 and len(extra) == 0, missing, extra, recon_dev


def post_entry_health(ev, daybars, futures_day):
    direction = ev["direction"]
    entry_ts = ev["entry_timestamp"]
    entry = ev["entry_close"]
    hi = ev["reference_high"]
    lo = ev["reference_low"]
    mid = ev["reference_midpoint"]

    warning = None
    warning_reason = None
    recovery = None
    invalid = None

    warning_points = None
    recovery_points = None
    invalid_points = None

    # Excursion diagnostics.
    best = None
    worst = None

    common = sorted(
        ts for ts in set(daybars).intersection(futures_day)
        if ts > entry_ts and ts[11:16] <= TRUSTED_END
    )

    for stamp in common:
        bar = daybars[stamp]
        close = bar["close"]
        diff = futures_day[stamp]["diff"]

        # MFE/MAE through live structure, excluding invalidation bar from excursion.
        if direction == "BULLISH":
            fav = bar["high"] - entry
            adv = bar["low"] - entry
        else:
            fav = entry - bar["low"]
            adv = entry - bar["high"]

        # Midpoint invalidation first; do not include invalidation bar in MFE/MAE.
        alive = midpoint_alive(direction, close, mid)
        if not alive:
            invalid = stamp
            invalid_points = dmove(direction, entry, close)
            break

        best = fav if best is None else max(best, fav)
        worst = adv if worst is None else min(worst, adv)

        boundary_held = close > hi if direction == "BULLISH" else close < lo
        vwap_side = diff > 0 if direction == "BULLISH" else diff < 0

        if warning is None and (not boundary_held or not vwap_side):
            warning = stamp
            reasons = []
            if not boundary_held:
                reasons.append("BOUNDARY_RECLAIM")
            if not vwap_side:
                reasons.append("VWAP_SIDE_LOST")
            warning_reason = "+".join(reasons)
            warning_points = dmove(direction, entry, close)
            continue

        if warning and recovery is None:
            recovered = (
                close > hi and diff > 0
                if direction == "BULLISH"
                else close < lo and diff < 0
            )
            if recovered:
                recovery = stamp
                recovery_points = dmove(direction, entry, close)

    # Session close if structure did not invalidate.
    session_exit_ts = None
    session_exit_points = None
    if not invalid:
        stamps = [
            ts for ts in daybars
            if ts > entry_ts and ts[11:16] <= TRUSTED_END
        ]
        if stamps:
            session_exit_ts = sorted(stamps)[-1]
            session_exit_points = dmove(
                direction, entry, daybars[session_exit_ts]["close"]
            )

    e2w = minutes(entry_ts, warning) if warning else None
    w2r = minutes(warning, recovery) if warning and recovery else None
    w2i = minutes(warning, invalid) if warning and invalid else None

    recover_3m = bool(w2r is not None and w2r <= 3)

    if warning is None:
        final_class = "HEALTHY_NO_WARNING"
    elif recovery and invalid:
        final_class = "WARNING_RECOVERED_THEN_INVALIDATED"
    elif recovery and not invalid:
        final_class = "WARNING_RECOVERED_NO_INVALIDATION"
    elif invalid:
        final_class = "WARNING_THEN_INVALIDATED"
    else:
        final_class = "WARNING_NO_RECOVERY_NO_INVALIDATION"

    return {
        **ev,
        "mfe": best,
        "mae": worst,
        "first_warning_timestamp": warning,
        "first_warning_reason": warning_reason,
        "entry_to_warning_min": e2w,
        "warning_points": warning_points,
        "first_recovery_timestamp": recovery,
        "warning_to_recovery_min": w2r,
        "recovery_points": recovery_points,
        "midpoint_invalidation_timestamp": invalid,
        "warning_to_invalidation_min": w2i,
        "invalidation_points": invalid_points,
        "session_exit_timestamp": session_exit_ts,
        "session_exit_points": session_exit_points,
        "recovered_within_3m": recover_3m,
        "final_class": final_class,
    }


def main():
    under = load_underlying()
    fut = load_futures()

    reconstructed = reconstruct_all(under, fut)
    known = known_60_b()

    parity_ok, missing, extra, recon_dev = parity_gate(reconstructed, known)

    print("B FAMILY — INDEPENDENT HISTORICAL VALIDATION V6")
    print("=" * 118)
    print(f"Known frozen 60-sample B events: {len(known)}")
    print(f"Reconstructed B events on/after {DEV_START}: {len(recon_dev)}")
    print(f"Parity exact: {parity_ok}")
    print(f"Missing: {len(missing)}")
    print(f"Extra: {len(extra)}")
    print("Parity CSV:", PARITY_CSV)

    if not parity_ok:
        print()
        print("ABORTED: reconstruction does not exactly match the frozen 60-session B events.")
        print("Do not use older-sample results until parity is fixed.")
        if missing:
            print("\nMISSING:")
            for x in missing[:20]:
                print(x)
        if extra:
            print("\nEXTRA:")
            for x in extra[:20]:
                print(x)
        raise SystemExit(2)

    older = [
        r for r in reconstructed
        if r["session_date"] < DEV_START
    ]

    validated = [
        post_entry_health(r, under[r["session_date"]], fut[r["session_date"]])
        for r in older
    ]

    OUT.mkdir(parents=True, exist_ok=True)

    fields = [
        "session_date","direction","entry_timestamp","entry_close","entry_fut_vwap",
        "reference_colour","reference_start","reference_end",
        "reference_high","reference_low","reference_midpoint",
        "midpoint_break_timestamp","boundary_break_timestamp",
        "mfe","mae",
        "first_warning_timestamp","first_warning_reason","entry_to_warning_min",
        "warning_points","first_recovery_timestamp","warning_to_recovery_min",
        "recovery_points","midpoint_invalidation_timestamp",
        "warning_to_invalidation_min","invalidation_points",
        "session_exit_timestamp","session_exit_points",
        "recovered_within_3m","final_class",
    ]

    with open(EVENT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(validated)

    counts = Counter(r["final_class"] for r in validated)
    warns = [r for r in validated if r["first_warning_timestamp"]]
    recovered = [r for r in warns if r["first_recovery_timestamp"]]
    no_recovery = [r for r in warns if not r["first_recovery_timestamp"]]

    lines = []
    lines.append("B FAMILY — INDEPENDENT HISTORICAL VALIDATION V6")
    lines.append("=" * 118)
    lines.append("PARITY GATE: PASS")
    lines.append(f"Known 60 B events: {len(known)}")
    lines.append(f"Reconstructed known-sample B events: {len(recon_dev)}")
    lines.append("")
    lines.append("OLDER VALIDATION SAMPLE")
    lines.append("-" * 118)
    lines.append(f"Cutoff: sessions strictly before {DEV_START}")
    lines.append(f"Available common underlying/futures sessions: {sum(1 for d in set(under)&set(fut) if d < DEV_START)}")
    lines.append(f"Detected B events: {len(validated)}")
    lines.append(f"BULLISH: {sum(r['direction']=='BULLISH' for r in validated)}")
    lines.append(f"BEARISH: {sum(r['direction']=='BEARISH' for r in validated)}")
    lines.append("")
    lines.append("FINAL CLASS COUNTS")
    for k, v in sorted(counts.items()):
        lines.append(f"{k}: {v}")

    lines.append("")
    lines.append("WARNING / RECOVERY")
    lines.append(f"Warnings: {len(warns)}")
    lines.append(f"Recovered eventually: {len(recovered)}")
    lines.append(f"No recovery: {len(no_recovery)}")
    lines.append(f"Recovered within 3m: {sum(r['recovered_within_3m'] for r in warns)}")
    lines.append(f"Median entry->warning min: {med([r['entry_to_warning_min'] for r in warns])}")
    lines.append(f"Median warning points: {med([r['warning_points'] for r in warns])}")
    lines.append(f"Median warning->recovery min: {med([r['warning_to_recovery_min'] for r in recovered])}")
    lines.append(f"Median warning->invalidation min: {med([r['warning_to_invalidation_min'] for r in warns])}")
    lines.append("")

    ages = [r["entry_to_warning_min"] for r in warns]
    if ages:
        lines.append(
            f"Warning age quartiles: Q1={percentile(ages,.25)} "
            f"median={percentile(ages,.50)} Q3={percentile(ages,.75)}"
        )

    nonprofit = [
        r for r in warns
        if r["warning_points"] is not None and r["warning_points"] <= 0
    ]
    profitable = [
        r for r in warns
        if r["warning_points"] is not None and r["warning_points"] > 0
    ]

    lines.append("")
    lines.append("NATURAL ZERO-POINT WARNING SPLIT")
    lines.append(
        f"NONPROFIT_AT_WARNING: n={len(nonprofit)} "
        f"medianAge={med([r['entry_to_warning_min'] for r in nonprofit])} "
        f"medianWarnPts={med([r['warning_points'] for r in nonprofit])} "
        f"recover<=3m={sum(r['recovered_within_3m'] for r in nonprofit)}"
    )
    lines.append(
        f"PROFITABLE_AT_WARNING: n={len(profitable)} "
        f"medianAge={med([r['entry_to_warning_min'] for r in profitable])} "
        f"medianWarnPts={med([r['warning_points'] for r in profitable])} "
        f"recover<=3m={sum(r['recovered_within_3m'] for r in profitable)}"
    )

    lines.append("")
    lines.append("EVENT DETAIL")
    lines.append("=" * 118)

    for r in validated:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"entry={r['entry_timestamp'][11:16]} "
            f"warn={(r['first_warning_timestamp'][11:16] if r['first_warning_timestamp'] else '-')} "
            f"age={r['entry_to_warning_min']} "
            f"warnPts={r['warning_points']} "
            f"recovery={(r['first_recovery_timestamp'][11:16] if r['first_recovery_timestamp'] else '-')} "
            f"w2r={r['warning_to_recovery_min']} "
            f"invalid={(r['midpoint_invalidation_timestamp'][11:16] if r['midpoint_invalidation_timestamp'] else '-')} "
            f"MFE={r['mfe']} MAE={r['mae']} "
            f"recover3m={r['recovered_within_3m']} "
            f"class={r['final_class']}"
        )

    lines.append("")
    lines.append("IMPORTANT")
    lines.append("- No new threshold was tuned on the older sample.")
    lines.append("- B entry definition is unchanged.")
    lines.append("- The 3-minute window is evaluated unchanged from prior research.")
    lines.append("- Older sample is independent of B management tuning, but not globally pristine from all earlier Candidate-A research.")
    lines.append("- Underlying NIFTY points are not option-premium P&L.")

    summary = "\n".join(lines)
    SUMMARY_TXT.write_text(summary)

    print()
    print(summary)
    print()
    print("EVENT CSV:", EVENT_CSV)
    print("SUMMARY:", SUMMARY_TXT)


if __name__ == "__main__":
    main()
