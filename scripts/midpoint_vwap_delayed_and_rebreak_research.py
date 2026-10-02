#!/usr/bin/env python3
"""
MIDPOINT + VWAP DELAYED CONFIRMATION / REBREAK RESEARCH V1.1

Research-only diagnostics.

Changes from V1:
1. Study A re-evaluates the COMPLETE frozen Candidate A condition at each future
   minute, including the causal 5-minute VWAP interaction requirement.
2. Study B records lifecycle durations so long multi-hour chains are visible.
3. Coverage explicitly reports:
      all framework events
      events with boundary break
      events without boundary break
      study-eligible events
4. Candidate A, Hilega, runtime, execution, quantity, and orders remain unchanged.
"""

from __future__ import annotations

import csv
import glob
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

ROOT = Path("data/historical-evidence")

FRAMEWORK_GLOB = str(ROOT / "opening-candle-midpoint-framework-v1-1-*.json")
FUTURES_CSV = ROOT / "midpoint-v2-nifty-futures-vwap-v1-all180.csv"
UNDERLYING_GLOB = str(ROOT / "underlying-ohlc-*.csv")

OUTDIR = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-delayed-and-rebreak-research-v1-1"
)

STUDY_A_CSV = OUTDIR / "delayed-vwap-confirmation-events-v1-1.csv"
STUDY_B_CSV = OUTDIR / "midpoint-retest-rebreak-events-v1-1.csv"
SUMMARY_TXT = OUTDIR / "summary-v1-1.txt"

VWAP_THRESHOLD = 5.0
DELAY_WINDOWS = (1, 2, 3, 5, 10)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def ts_key(dt: datetime) -> str:
    return dt.isoformat()


def minutes_between(a: str | None, b: str | None):
    if not a or not b:
        return None
    return (parse_ts(b) - parse_ts(a)).total_seconds() / 60.0


def get_float(row, *keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return float(v)
    return None


def get_ts(row):
    for k in ("timestamp", "datetime", "time"):
        v = row.get(k)
        if v:
            return v
    return None


def walk_all_framework_events(obj):
    """
    Return all RED_BREAK / GREEN_BREAK framework records, including those
    without boundary_break_timestamp, so coverage is explicit.
    """
    if isinstance(obj, dict):
        if (
            obj.get("session_date")
            and obj.get("setup_type") in {"RED_BREAK", "GREEN_BREAK"}
        ):
            yield obj

        for v in obj.values():
            yield from walk_all_framework_events(v)

    elif isinstance(obj, list):
        for v in obj:
            yield from walk_all_framework_events(v)


def framework_event_key(e):
    return (
        e.get("session_date"),
        e.get("setup_type"),
        e.get("reference_start"),
        e.get("reference_end"),
        e.get("reference_high"),
        e.get("reference_low"),
        e.get("reference_midpoint"),
        e.get("midpoint_break_timestamp"),
        e.get("boundary_break_timestamp"),
    )


def load_framework_events():
    files = sorted(glob.glob(FRAMEWORK_GLOB))
    if not files:
        raise FileNotFoundError(f"No framework files matched: {FRAMEWORK_GLOB}")

    events = []
    seen = set()

    for p in files:
        with open(p) as f:
            obj = json.load(f)

        for e in walk_all_framework_events(obj):
            key = framework_event_key(e)
            if key in seen:
                continue
            seen.add(key)
            events.append(e)

    events.sort(
        key=lambda x: (
            x.get("session_date") or "",
            x.get("boundary_break_timestamp")
            or x.get("midpoint_break_timestamp")
            or "",
            x.get("setup_type") or "",
        )
    )
    return files, events


def load_futures():
    if not FUTURES_CSV.exists():
        raise FileNotFoundError(FUTURES_CSV)

    out = {}

    with FUTURES_CSV.open(newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            ts = row.get("timestamp")
            if not ts:
                continue

            close = get_float(row, "close")
            vwap = get_float(row, "session_vwap", "vwap")

            if close is None or vwap is None:
                continue

            out[ts] = {
                "close": close,
                "vwap": vwap,
                "diff": close - vwap,
            }

    return out


def load_underlying():
    files = sorted(glob.glob(UNDERLYING_GLOB))
    if not files:
        raise FileNotFoundError(f"No underlying files matched: {UNDERLYING_GLOB}")

    by_ts = {}
    duplicates = 0

    for p in files:
        with open(p, newline="") as f:
            r = csv.DictReader(f)

            for row in r:
                ts = get_ts(row)
                if not ts:
                    continue

                o = get_float(row, "open")
                h = get_float(row, "high")
                l = get_float(row, "low")
                c = get_float(row, "close")

                if None in (o, h, l, c):
                    continue

                rec = {
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                }

                if ts in by_ts and by_ts[ts] != rec:
                    duplicates += 1
                    continue

                by_ts[ts] = rec

    return files, by_ts, duplicates


def direction_for(e):
    d = e.get("direction")
    if d in {"BEARISH", "BULLISH"}:
        return d

    return "BEARISH" if e["setup_type"] == "RED_BREAK" else "BULLISH"


def full_candidate_a_at(direction, at_ts: datetime, futures):
    """
    Frozen Candidate A logic at an arbitrary timestamp.

    BEAR:
      current Close-VWAP < -5
      AND at least one exact completed 1m observation in T-5..T >= -5

    BULL:
      current Close-VWAP > +5
      AND at least one exact completed 1m observation in T-5..T <= +5

    No interpolation.
    """
    current = futures.get(ts_key(at_ts))
    if not current:
        return None, None, [], "MISSING_CURRENT_FUTURES"

    prior_diffs = []

    for i in range(5, -1, -1):
        row = futures.get(ts_key(at_ts - timedelta(minutes=i)))
        if row is not None:
            prior_diffs.append(row["diff"])

    if not prior_diffs:
        return None, current["diff"], [], "MISSING_CAUSAL_WINDOW"

    if direction == "BEARISH":
        ok = (
            current["diff"] < -VWAP_THRESHOLD
            and any(x >= -VWAP_THRESHOLD for x in prior_diffs)
        )
    else:
        ok = (
            current["diff"] > VWAP_THRESHOLD
            and any(x <= VWAP_THRESHOLD for x in prior_diffs)
        )

    return ok, current["diff"], prior_diffs, "AVAILABLE"


def structurally_valid_for_delayed(direction, close, midpoint):
    """
    Conservative Study-A guard:
    once price closes through midpoint against the original direction,
    stop waiting for delayed confirmation.
    """
    if direction == "BEARISH":
        return close <= midpoint

    return close >= midpoint


def beyond_original_boundary(direction, close, boundary):
    if direction == "BEARISH":
        return close < boundary

    return close > boundary


def study_a(events, futures, underlying):
    rows = []

    eligible_events = [e for e in events if e.get("boundary_break_timestamp")]

    for e in eligible_events:
        direction = direction_for(e)
        midpoint = float(e["reference_midpoint"])
        boundary = float(
            e["reference_low"] if direction == "BEARISH"
            else e["reference_high"]
        )

        t0 = parse_ts(e["boundary_break_timestamp"])

        is_a, t0_diff, t0_window, a_status = full_candidate_a_at(
            direction,
            t0,
            futures,
        )

        row = {
            "session_date": e["session_date"],
            "direction": direction,
            "setup_type": e["setup_type"],
            "reference_high": e.get("reference_high"),
            "reference_low": e.get("reference_low"),
            "reference_midpoint": midpoint,
            "boundary_break_timestamp": e["boundary_break_timestamp"],
            "primary_outcome": e.get("primary_outcome"),
            "candidate_a_status": a_status,
            "candidate_a_at_t0": is_a,
            "t0_vwap_distance": t0_diff,
            "t0_causal_window_min": min(t0_window) if t0_window else None,
            "t0_causal_window_max": max(t0_window) if t0_window else None,
            "delayed_eligible": (is_a is False),
            "first_delayed_confirmation_timestamp": None,
            "delay_minutes": None,
            "confirmation_vwap_distance": None,
            "confirmation_window_min": None,
            "confirmation_window_max": None,
            "confirmation_underlying_close": None,
            "stop_reason": None,
        }

        if is_a is not False:
            row["stop_reason"] = (
                "ALREADY_CANDIDATE_A"
                if is_a is True
                else a_status
            )
            rows.append(row)
            continue

        for minute in range(1, max(DELAY_WINDOWS) + 1):
            ts = t0 + timedelta(minutes=minute)
            key = ts_key(ts)

            u = underlying.get(key)
            if not u:
                row["stop_reason"] = f"MISSING_UNDERLYING_TPLUS_{minute}"
                break

            if not structurally_valid_for_delayed(
                direction,
                u["close"],
                midpoint,
            ):
                row["stop_reason"] = (
                    f"MIDPOINT_INVALIDATION_TPLUS_{minute}"
                )
                break

            # Delayed confirmation should only count while price is still
            # beyond the original structural boundary.
            if not beyond_original_boundary(
                direction,
                u["close"],
                boundary,
            ):
                continue

            ok, diff, window, status = full_candidate_a_at(
                direction,
                ts,
                futures,
            )

            if ok is True:
                row["first_delayed_confirmation_timestamp"] = key
                row["delay_minutes"] = minute
                row["confirmation_vwap_distance"] = diff
                row["confirmation_window_min"] = (
                    min(window) if window else None
                )
                row["confirmation_window_max"] = (
                    max(window) if window else None
                )
                row["confirmation_underlying_close"] = u["close"]
                row["stop_reason"] = "CONFIRMED_FULL_CANDIDATE_A"
                break

        if row["stop_reason"] is None:
            row["stop_reason"] = "NO_FULL_CONFIRMATION_WITHIN_10M"

        rows.append(row)

    return rows


def midpoint_touched(candle, midpoint):
    return candle["low"] <= midpoint <= candle["high"]


def crossed_midpoint_against(direction, close, midpoint):
    if direction == "BEARISH":
        return close > midpoint
    return close < midpoint


def back_original_side(direction, close, midpoint):
    if direction == "BEARISH":
        return close < midpoint
    return close > midpoint


def inside_original_boundary(direction, close, boundary):
    """
    To make a later break a genuinely fresh rebreak, price must first return
    inside the original boundary.
    """
    if direction == "BEARISH":
        return close >= boundary
    return close <= boundary


def fresh_boundary_break(direction, close, boundary):
    if direction == "BEARISH":
        return close < boundary
    return close > boundary


def study_b(events, futures, underlying):
    """
    Descriptive first post-T0 midpoint-retest cycle.

    No arbitrary time cutoff other than same trading session.
    Durations are recorded so very long chains can be separated later.

    Pattern types:
      TEMPORARY_RECLAIM_FAILED
      TOUCH_REJECTION

    A rebreak is counted only after:
      - a midpoint retest,
      - return to original side of midpoint,
      - price has returned inside original reference boundary,
      - later fresh close through original boundary.
    """
    rows = []

    eligible_events = [e for e in events if e.get("boundary_break_timestamp")]

    for e in eligible_events:
        direction = direction_for(e)
        midpoint = float(e["reference_midpoint"])
        boundary = float(
            e["reference_low"] if direction == "BEARISH"
            else e["reference_high"]
        )

        t0 = parse_ts(e["boundary_break_timestamp"])

        rec = {
            "session_date": e["session_date"],
            "direction": direction,
            "setup_type": e["setup_type"],
            "reference_high": e.get("reference_high"),
            "reference_low": e.get("reference_low"),
            "reference_midpoint": midpoint,
            "boundary_break_timestamp": e["boundary_break_timestamp"],
            "primary_outcome": e.get("primary_outcome"),

            "midpoint_retest_timestamp": None,
            "temporary_reclaim_timestamp": None,
            "failed_reclaim_timestamp": None,
            "boundary_reset_timestamp": None,
            "rebreak_timestamp": None,

            "pattern_type": None,

            "vwap_at_retest": None,
            "vwap_at_temporary_reclaim": None,
            "vwap_at_failed_reclaim": None,
            "vwap_at_rebreak": None,

            "t0_to_retest_minutes": None,
            "retest_to_temp_reclaim_minutes": None,
            "temp_reclaim_to_failed_minutes": None,
            "retest_to_failed_minutes": None,
            "failed_to_rebreak_minutes": None,
            "retest_to_rebreak_minutes": None,
            "t0_to_rebreak_minutes": None,
        }

        retest_ts = None
        temp_reclaim_ts = None
        failed_reclaim_ts = None
        boundary_reset_ts = None

        # Same-session scan to 15:30.
        for minute in range(1, 6 * 60 + 1):
            ts = t0 + timedelta(minutes=minute)

            if ts.date() != t0.date():
                break

            if ts.hour > 15 or (ts.hour == 15 and ts.minute > 30):
                break

            key = ts_key(ts)
            u = underlying.get(key)

            if not u:
                continue

            # 1) first midpoint retest after original boundary break
            if retest_ts is None:
                if midpoint_touched(u, midpoint):
                    retest_ts = ts
                    rec["midpoint_retest_timestamp"] = key

                    if key in futures:
                        rec["vwap_at_retest"] = futures[key]["diff"]

                    # same candle may close across midpoint
                    if crossed_midpoint_against(
                        direction,
                        u["close"],
                        midpoint,
                    ):
                        temp_reclaim_ts = ts
                        rec["temporary_reclaim_timestamp"] = key

                        if key in futures:
                            rec["vwap_at_temporary_reclaim"] = (
                                futures[key]["diff"]
                            )

                continue

            # 2) after retest, first close across midpoint against direction
            if (
                temp_reclaim_ts is None
                and crossed_midpoint_against(
                    direction,
                    u["close"],
                    midpoint,
                )
            ):
                temp_reclaim_ts = ts
                rec["temporary_reclaim_timestamp"] = key

                if key in futures:
                    rec["vwap_at_temporary_reclaim"] = futures[key]["diff"]

            # 3) return to original side after retest
            if (
                failed_reclaim_ts is None
                and back_original_side(
                    direction,
                    u["close"],
                    midpoint,
                )
            ):
                failed_reclaim_ts = ts
                rec["failed_reclaim_timestamp"] = key

                if key in futures:
                    rec["vwap_at_failed_reclaim"] = futures[key]["diff"]

            # 4) price must re-enter original reference boundary before a
            #    new boundary crossing can be called a fresh rebreak
            if (
                boundary_reset_ts is None
                and inside_original_boundary(
                    direction,
                    u["close"],
                    boundary,
                )
            ):
                boundary_reset_ts = ts
                rec["boundary_reset_timestamp"] = key

            # 5) fresh boundary rebreak
            if (
                failed_reclaim_ts is not None
                and boundary_reset_ts is not None
                and ts > max(failed_reclaim_ts, boundary_reset_ts)
                and fresh_boundary_break(
                    direction,
                    u["close"],
                    boundary,
                )
            ):
                rec["rebreak_timestamp"] = key
                rec["pattern_type"] = (
                    "TEMPORARY_RECLAIM_FAILED"
                    if temp_reclaim_ts is not None
                    else "TOUCH_REJECTION"
                )

                if key in futures:
                    rec["vwap_at_rebreak"] = futures[key]["diff"]

                break

        # durations
        rec["t0_to_retest_minutes"] = minutes_between(
            rec["boundary_break_timestamp"],
            rec["midpoint_retest_timestamp"],
        )

        rec["retest_to_temp_reclaim_minutes"] = minutes_between(
            rec["midpoint_retest_timestamp"],
            rec["temporary_reclaim_timestamp"],
        )

        rec["temp_reclaim_to_failed_minutes"] = minutes_between(
            rec["temporary_reclaim_timestamp"],
            rec["failed_reclaim_timestamp"],
        )

        rec["retest_to_failed_minutes"] = minutes_between(
            rec["midpoint_retest_timestamp"],
            rec["failed_reclaim_timestamp"],
        )

        rec["failed_to_rebreak_minutes"] = minutes_between(
            rec["failed_reclaim_timestamp"],
            rec["rebreak_timestamp"],
        )

        rec["retest_to_rebreak_minutes"] = minutes_between(
            rec["midpoint_retest_timestamp"],
            rec["rebreak_timestamp"],
        )

        rec["t0_to_rebreak_minutes"] = minutes_between(
            rec["boundary_break_timestamp"],
            rec["rebreak_timestamp"],
        )

        rows.append(rec)

    return rows


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)

    fields = []

    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)

    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def pct(a, b):
    return 0.0 if not b else (100.0 * a / b)


def fmt_n_pct(n, total):
    return f"{n:4d} ({pct(n, total):6.2f}%)"


def describe(values):
    vals = [float(x) for x in values if x is not None]

    if not vals:
        return "n=0"

    vals = sorted(vals)

    def q(p):
        idx = round((len(vals) - 1) * p)
        return vals[idx]

    return (
        f"n={len(vals)} "
        f"median={median(vals):.2f} "
        f"p25={q(0.25):.2f} "
        f"p75={q(0.75):.2f} "
        f"min={vals[0]:.2f} "
        f"max={vals[-1]:.2f}"
    )


def summarize_a(rows):
    eligible = [r for r in rows if r["delayed_eligible"]]

    lines = []
    lines.append("STUDY A — FULL CANDIDATE-A DELAYED CONFIRMATION")
    lines.append("=" * 100)

    for direction in ("BEARISH", "BULLISH", "COMBINED"):
        subset = (
            eligible
            if direction == "COMBINED"
            else [r for r in eligible if r["direction"] == direction]
        )

        confirmed = [
            r for r in subset
            if r["delay_minutes"] is not None
        ]

        lines.append("")
        lines.append(direction)
        lines.append(
            f"  NOT-A eligible events         : {len(subset)}"
        )
        lines.append(
            f"  full Candidate A <=10m        : "
            f"{fmt_n_pct(len(confirmed), len(subset))}"
        )

        for w in DELAY_WINDOWS:
            n = sum(
                1 for r in confirmed
                if int(r["delay_minutes"]) <= w
            )
            lines.append(
                f"  cumulative confirmed <= {w:2d}m : "
                f"{fmt_n_pct(n, len(subset))}"
            )

        delays = [
            int(r["delay_minutes"])
            for r in confirmed
        ]

        if delays:
            lines.append(
                f"  confirmation-delay distribution: "
                f"{describe(delays)}"
            )

        stop = Counter(r["stop_reason"] for r in subset)
        lines.append(
            f"  stop reasons                 : {dict(stop)}"
        )

    return lines


def summarize_b(rows):
    lines = []
    lines.append("")
    lines.append("")
    lines.append(
        "STUDY B — MIDPOINT RETEST / FAILED RECLAIM / REBREAK"
    )
    lines.append("=" * 100)

    for direction in ("BEARISH", "BULLISH", "COMBINED"):
        subset = (
            rows
            if direction == "COMBINED"
            else [r for r in rows if r["direction"] == direction]
        )

        retest = [
            r for r in subset
            if r["midpoint_retest_timestamp"]
        ]
        temp = [
            r for r in subset
            if r["temporary_reclaim_timestamp"]
        ]
        failed = [
            r for r in subset
            if r["failed_reclaim_timestamp"]
        ]
        rebreak = [
            r for r in subset
            if r["rebreak_timestamp"]
        ]

        lines.append("")
        lines.append(direction)

        lines.append(
            f"  boundary-break events         : {len(subset)}"
        )
        lines.append(
            f"  midpoint retest               : "
            f"{fmt_n_pct(len(retest), len(subset))}"
        )
        lines.append(
            f"  temporary reclaim close       : "
            f"{fmt_n_pct(len(temp), len(subset))}"
        )
        lines.append(
            f"  return to original side       : "
            f"{fmt_n_pct(len(failed), len(subset))}"
        )
        lines.append(
            f"  fresh boundary rebreak        : "
            f"{fmt_n_pct(len(rebreak), len(subset))}"
        )

        lines.append(
            "  rebreak pattern types         : "
            + str(dict(Counter(
                r["pattern_type"]
                for r in rebreak
            )))
        )

        lines.append(
            "  T0->retest duration           : "
            + describe(
                r["t0_to_retest_minutes"]
                for r in retest
            )
        )

        lines.append(
            "  retest->failed duration       : "
            + describe(
                r["retest_to_failed_minutes"]
                for r in failed
            )
        )

        lines.append(
            "  failed->rebreak duration      : "
            + describe(
                r["failed_to_rebreak_minutes"]
                for r in rebreak
            )
        )

        lines.append(
            "  retest->rebreak duration      : "
            + describe(
                r["retest_to_rebreak_minutes"]
                for r in rebreak
            )
        )

        lines.append(
            "  T0->rebreak duration          : "
            + describe(
                r["t0_to_rebreak_minutes"]
                for r in rebreak
            )
        )

    return lines


def print_25_aug(a_rows, b_rows):
    print("")
    print("=" * 100)
    print("2026-08-25 MANUAL CHECK")
    print("=" * 100)

    for r in a_rows:
        if r["session_date"] == "2026-08-25":
            print(
                "A",
                r["direction"],
                "T0=", r["boundary_break_timestamp"],
                "candA=", r["candidate_a_at_t0"],
                "t0_vwap=", r["t0_vwap_distance"],
                "delayed=",
                r["first_delayed_confirmation_timestamp"],
                "delay=", r["delay_minutes"],
                "confirm_vwap=",
                r["confirmation_vwap_distance"],
                "window_min=",
                r["confirmation_window_min"],
                "window_max=",
                r["confirmation_window_max"],
                "stop=", r["stop_reason"],
            )

    for r in b_rows:
        if r["session_date"] == "2026-08-25":
            print(
                "B",
                r["direction"],
                "T0=", r["boundary_break_timestamp"],
                "retest=", r["midpoint_retest_timestamp"],
                "temp_reclaim=",
                r["temporary_reclaim_timestamp"],
                "failed_reclaim=",
                r["failed_reclaim_timestamp"],
                "boundary_reset=",
                r["boundary_reset_timestamp"],
                "rebreak=", r["rebreak_timestamp"],
                "pattern=", r["pattern_type"],
                "t0_to_retest=",
                r["t0_to_retest_minutes"],
                "retest_to_failed=",
                r["retest_to_failed_minutes"],
                "failed_to_rebreak=",
                r["failed_to_rebreak_minutes"],
                "t0_to_rebreak=",
                r["t0_to_rebreak_minutes"],
            )


def main():
    framework_files, all_events = load_framework_events()
    futures = load_futures()
    underlying_files, underlying, duplicate_count = load_underlying()

    boundary_events = [
        e for e in all_events
        if e.get("boundary_break_timestamp")
    ]

    no_boundary_events = [
        e for e in all_events
        if not e.get("boundary_break_timestamp")
    ]

    a_rows = study_a(
        all_events,
        futures,
        underlying,
    )

    b_rows = study_b(
        all_events,
        futures,
        underlying,
    )

    write_csv(STUDY_A_CSV, a_rows)
    write_csv(STUDY_B_CSV, b_rows)

    summary = []

    summary.append(
        "MIDPOINT + VWAP DELAYED / REBREAK RESEARCH V1.1"
    )
    summary.append("=" * 100)

    summary.append(
        "RESEARCH ONLY — Candidate A unchanged; "
        "no runtime/execution changes."
    )

    summary.append("")

    summary.append(
        f"framework files               = {len(framework_files)}"
    )

    for p in framework_files:
        summary.append(f"  {p}")

    summary.append(
        f"all framework events          = {len(all_events)}"
    )

    summary.append(
        f"events with boundary break    = {len(boundary_events)}"
    )

    summary.append(
        f"events without boundary break = {len(no_boundary_events)}"
    )

    summary.append(
        f"study-eligible events         = {len(boundary_events)}"
    )

    summary.append(
        f"underlying files              = {len(underlying_files)}"
    )

    summary.append(
        f"underlying duplicate conflict = {duplicate_count}"
    )

    summary.append(
        f"futures minute rows           = {len(futures)}"
    )

    summary.append(
        f"underlying minute rows        = {len(underlying)}"
    )

    summary.append("")

    summary.extend(summarize_a(a_rows))
    summary.extend(summarize_b(b_rows))

    summary.append("")
    summary.append("INTERPRETATION GUARD")

    summary.append(
        "Study A re-evaluates the complete frozen Candidate A condition "
        "at every future minute. Study B is descriptive only. "
        "Do not promote any delayed window or rebreak-duration cutoff "
        "into production rules without separate validation / "
        "forward observation."
    )

    summary.append("")

    summary.append(f"STUDY A CSV = {STUDY_A_CSV}")
    summary.append(f"STUDY B CSV = {STUDY_B_CSV}")
    summary.append(f"SUMMARY     = {SUMMARY_TXT}")

    OUTDIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    SUMMARY_TXT.write_text(
        "\n".join(summary) + "\n"
    )

    print("\n".join(summary))

    print_25_aug(
        a_rows,
        b_rows,
    )


if __name__ == "__main__":
    main()
