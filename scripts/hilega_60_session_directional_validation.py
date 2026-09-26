#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta, date
import argparse
import csv
import json
import math
import statistics
import subprocess
import sys

# ============================================================
# Frozen research design
# ============================================================

STEP = 50

# Main validation uses latest 60 real-OI sessions discovered from cache.
MAIN_SESSION_COUNT = 60

# Frozen candidate discovered on the earlier 30-session research sample.
FROZEN_INTENSITY_LOW = 3.0
FROZEN_INTENSITY_HIGH = 5.0
FROZEN_EXCLUDED_TIME_BUCKET = "13:00-13:59"

# Expiry-aware moving ATM panel already under research.
MODEL_C_WINGS = {
    0: 3,  # Monday
    1: 2,  # Tuesday
    2: 5,  # Wednesday
    3: 5,  # Thursday
    4: 4,  # Friday
}

DAY_NAMES = {
    0: "MON",
    1: "TUE",
    2: "WED",
    3: "THU",
    4: "FRI",
}

# Exact frozen 18 + 18 directional-session sets.
BULLISH_DIRECTIONAL_18 = [
    "2026-05-18",
    "2026-05-20",
    "2026-05-25",
    "2026-06-02",
    "2026-06-12",
    "2026-06-16",
    "2026-06-17",
    "2026-06-18",
    "2026-06-24",
    "2026-07-06",
    "2026-07-10",
    "2026-07-13",
    "2026-07-17",
    "2026-07-27",
    "2026-07-29",
    "2026-08-03",
    "2026-08-25",
    "2026-09-02",
]

BEARISH_DIRECTIONAL_18 = [
    "2026-05-12",
    "2026-05-19",
    "2026-05-29",
    "2026-06-01",
    "2026-06-23",
    "2026-06-29",
    "2026-07-07",
    "2026-07-08",
    "2026-07-14",
    "2026-07-16",
    "2026-07-22",
    "2026-08-18",
    "2026-08-24",
    "2026-08-26",
    "2026-08-27",
    "2026-09-03",
    "2026-09-07",
    "2026-09-08",
]

DIRECTIONAL_36 = sorted(
    set(BULLISH_DIRECTIONAL_18 + BEARISH_DIRECTIONAL_18)
)

OI_ROOTS = [
    Path("data/historical-positioning-cache-train"),
    Path("data/historical-positioning-cache-oos-a"),
    Path("data/historical-positioning-cache-oos-b"),
    Path("data/historical-positioning-cache-oos-c"),
    Path("data/historical-positioning-cache-oos-d"),
    Path("data/historical-positioning-cache-oos-e"),
    Path("data/historical-positioning-cache-oos-f"),
    Path("data/historical-positioning-cache-oos-g"),
    Path("data/historical-positioning-cache-oos-h"),
]

TRADES_ROOT = Path(
    "data/historical-evidence/"
    "hilega-directional-replay-v1"
)

OUT_DIR = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "60-session-directional-validation-v1"
)

OUT_DIR.mkdir(parents=True, exist_ok=True)

JOIN_CSV = OUT_DIR / "hilega-60-session-model-c-joined-v1.csv"
DIRECTIONAL_CSV = OUT_DIR / "hilega-directional-36-model-c-joined-v1.csv"
SUMMARY_TXT = OUT_DIR / "hilega-60-session-directional-validation-summary-v1.txt"
REPLAY_LOG = OUT_DIR / "historical-replay-build-v1.log"


def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Run 60-session Hilega+OI validation and the frozen "
            "18 bullish + 18 bearish directional-session validation."
        )
    )
    p.add_argument(
        "--run-replay",
        action="store_true",
        help="Generate/re-generate Hilega historical replay for all required dates.",
    )
    p.add_argument(
        "--skip-replay",
        action="store_true",
        help="Do not invoke historical replay; analyze only existing replay files.",
    )
    return p.parse_args()


def valid_oi_row(r):
    try:
        ce = r.get("ce_open_interest")
        pe = r.get("pe_open_interest")
        if ce is None or pe is None:
            return False
        ce = float(ce)
        pe = float(pe)
        return ce != 0 or pe != 0
    except Exception:
        return False


def discover_oi_sources():
    found = {}

    for root in OI_ROOTS:
        if not root.exists():
            continue

        for p in root.glob("*.json"):
            try:
                data = json.loads(
                    p.read_text(encoding="utf-8", errors="ignore")
                )
            except Exception:
                continue

            session_date = str(data.get("session_date", ""))
            rows = data.get("rows", [])

            if not session_date or not isinstance(rows, list):
                continue

            usable = sum(1 for r in rows if valid_oi_row(r))
            if usable == 0:
                continue

            old = found.get(session_date)

            if old is None or usable > old["usable"]:
                found[session_date] = {
                    "path": p,
                    "usable": usable,
                    "expiry": str(data.get("expiry", "")),
                }

    return found


def run_replay(dates):
    cmd = [
        sys.executable,
        "-m",
        "market_lab.hilega_directional_historical_replay_cli_v1",
        "--dates",
        *dates,
    ]

    print()
    print("=" * 120)
    print("GENERATING HILEGA HISTORICAL REPLAY")
    print("=" * 120)
    print("dates =", len(dates))
    print("full replay JSON will be written to:")
    print(REPLAY_LOG)

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    REPLAY_LOG.write_text(
        proc.stdout or "",
        encoding="utf-8",
    )

    if proc.returncode != 0:
        print("REPLAY FAILED. See:", REPLAY_LOG)
        raise SystemExit(proc.returncode)

    print("replay command = PASS")


def replay_file(session_date):
    return (
        TRADES_ROOT
        / session_date
        / "directional-trades.csv"
    )


def load_trades(session_date):
    p = replay_file(session_date)
    if not p.exists():
        return []

    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_ts(value):
    return datetime.fromisoformat(str(value))


def load_oi_session(info):
    data = json.loads(
        info["path"].read_text(
            encoding="utf-8",
            errors="ignore",
        )
    )

    snapshots = defaultdict(dict)
    atm_by_ts = {}

    for r in data.get("rows", []):
        try:
            ts = parse_ts(r["timestamp"])
            strike = float(r["strike"])
            ce = float(r["ce_open_interest"])
            pe = float(r["pe_open_interest"])
        except Exception:
            continue

        snapshots[ts][strike] = {
            "ce": ce,
            "pe": pe,
        }

        try:
            if int(r.get("strike_offset")) == 0:
                atm_by_ts[ts] = strike
        except Exception:
            pass

    return {
        "expiry": str(data.get("expiry", "")),
        "snapshots": dict(snapshots),
        "atm_by_ts": atm_by_ts,
        "source": str(info["path"]),
    }


def aggregate(snapshot, strikes):
    values = []

    for strike in strikes:
        item = snapshot.get(float(strike))
        if item is None:
            return None
        values.append(item)

    return {
        "ce": sum(x["ce"] for x in values),
        "pe": sum(x["pe"] for x in values),
    }


def pct(delta, previous):
    if previous in (None, 0):
        return None
    return delta / previous * 100.0


def pcr(pe, ce):
    if ce in (None, 0):
        return None
    return pe / ce


def classify(ce_delta, pe_delta):
    if ce_delta < 0 and pe_delta > 0:
        return "BULLISH"
    if ce_delta > 0 and pe_delta < 0:
        return "BEARISH"
    if ce_delta > 0 and pe_delta > 0:
        return "TWO_SIDE_BUILD"
    if ce_delta < 0 and pe_delta < 0:
        return "TWO_SIDE_UNWIND"
    return "NEUTRAL"


def relation(direction, state):
    if direction == state:
        return "MATCH"
    if state in {"BULLISH", "BEARISH"}:
        return "OPPOSITE"
    return "AMBIGUOUS"


def route_family(event):
    s = (event or "").upper()
    if "OPENING" in s:
        return "OPENING"
    if "ROUTE_A" in s:
        return "ROUTE_A"
    if "ROUTE_B" in s:
        return "ROUTE_B"
    return "OTHER"


def time_bucket(hhmm):
    try:
        hh, mm = map(int, hhmm.split(":"))
        m = hh * 60 + mm
    except Exception:
        return "UNKNOWN"

    if m < 10 * 60:
        return "09:15-09:59"
    if m < 11 * 60:
        return "10:00-10:59"
    if m < 12 * 60:
        return "11:00-11:59"
    if m < 13 * 60:
        return "12:00-12:59"
    if m < 14 * 60:
        return "13:00-13:59"
    return "14:00-14:55"


def dominant_leg(direction, ce_pct, pe_pct):
    if ce_pct is None or pe_pct is None:
        return "UNKNOWN"

    if direction == "BULLISH":
        return (
            "PE_BUILD"
            if pe_pct > abs(ce_pct)
            else "CE_UNWIND"
        )

    if direction == "BEARISH":
        return (
            "CE_BUILD"
            if ce_pct > abs(pe_pct)
            else "PE_UNWIND"
        )

    return "UNKNOWN"


def build_join(session_dates, oi_sources, set_name):
    rows_out = []

    for session_date in session_dates:
        info = oi_sources.get(session_date)
        trades = load_trades(session_date)

        if info is None:
            rows_out.append({
                "set_name": set_name,
                "session_date": session_date,
                "data_status": "OI_SOURCE_MISSING",
            })
            continue

        if not trades:
            rows_out.append({
                "set_name": set_name,
                "session_date": session_date,
                "data_status": "HILEGA_REPLAY_MISSING_OR_NO_TRADES",
            })
            continue

        oi = load_oi_session(info)

        if not oi["snapshots"]:
            rows_out.append({
                "set_name": set_name,
                "session_date": session_date,
                "data_status": "OI_SNAPSHOTS_MISSING",
            })
            continue

        example_ts = next(iter(oi["snapshots"]))
        tz = example_ts.tzinfo
        session_dt = datetime.fromisoformat(session_date)
        weekday = session_dt.weekday()
        wings = MODEL_C_WINGS[weekday]

        for trade in trades:
            hh, mm = map(int, trade["entry_time"].split(":"))

            signal_ts = datetime(
                session_dt.year,
                session_dt.month,
                session_dt.day,
                hh,
                mm,
                tzinfo=tz,
            )

            previous_ts = signal_ts - timedelta(minutes=5)

            current_snapshot = oi["snapshots"].get(signal_ts)
            previous_snapshot = oi["snapshots"].get(previous_ts)
            signal_atm = oi["atm_by_ts"].get(signal_ts)

            base = {
                "set_name": set_name,
                "session_date": session_date,
                "weekday": DAY_NAMES.get(weekday, str(weekday)),
                "expiry": oi["expiry"],
                "entry_time": trade["entry_time"],
                "entry_event": trade["entry_event"],
                "route_family": route_family(trade["entry_event"]),
                "time_bucket": time_bucket(trade["entry_time"]),
                "direction": trade["direction"],
                "exit_time": trade["exit_time"],
                "points": float(trade["points"]),
                "outcome": trade["outcome"],
                "wings": wings,
                "oi_source": oi["source"],
            }

            if current_snapshot is None:
                base["data_status"] = "CURRENT_SNAPSHOT_MISSING"
                rows_out.append(base)
                continue

            if previous_snapshot is None:
                base["data_status"] = "PREVIOUS_SNAPSHOT_MISSING"
                rows_out.append(base)
                continue

            if signal_atm is None:
                base["data_status"] = "SIGNAL_ATM_MISSING"
                rows_out.append(base)
                continue

            strikes = [
                signal_atm + i * STEP
                for i in range(-wings, wings + 1)
            ]

            current = aggregate(current_snapshot, strikes)
            previous = aggregate(previous_snapshot, strikes)

            if current is None or previous is None:
                base.update({
                    "data_status": "INCOMPLETE_SAME_PHYSICAL_PANEL",
                    "signal_atm": signal_atm,
                    "strike_low": min(strikes),
                    "strike_high": max(strikes),
                })
                rows_out.append(base)
                continue

            ce_delta = current["ce"] - previous["ce"]
            pe_delta = current["pe"] - previous["pe"]

            ce_pct = pct(ce_delta, previous["ce"])
            pe_pct = pct(pe_delta, previous["pe"])

            current_pcr = pcr(current["pe"], current["ce"])
            previous_pcr = pcr(previous["pe"], previous["ce"])

            state = classify(ce_delta, pe_delta)
            rel = relation(trade["direction"], state)

            intensity = (
                abs(ce_pct) + abs(pe_pct)
                if ce_pct is not None and pe_pct is not None
                else None
            )

            base.update({
                "data_status": "AVAILABLE",
                "signal_atm": signal_atm,
                "strike_low": min(strikes),
                "strike_high": max(strikes),
                "ce_delta": ce_delta,
                "pe_delta": pe_delta,
                "ce_delta_pct": ce_pct,
                "pe_delta_pct": pe_pct,
                "previous_pcr": previous_pcr,
                "current_pcr": current_pcr,
                "pcr_delta": (
                    current_pcr - previous_pcr
                    if current_pcr is not None and previous_pcr is not None
                    else None
                ),
                "intensity_sum_abs_pct": intensity,
                "oi_state": state,
                "relation": rel,
                "dominant_leg": dominant_leg(
                    trade["direction"],
                    ce_pct,
                    pe_pct,
                ),
                "frozen_candidate": (
                    rel == "MATCH"
                    and intensity is not None
                    and FROZEN_INTENSITY_LOW <= intensity < FROZEN_INTENSITY_HIGH
                    and base["time_bucket"] != FROZEN_EXCLUDED_TIME_BUCKET
                ),
            })

            rows_out.append(base)

    return rows_out


def write_csv(path, rows):
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def usable(rows):
    return [
        r for r in rows
        if r.get("data_status") == "AVAILABLE"
    ]


def summarize(rows):
    pts = []

    for r in rows:
        try:
            pts.append(float(r["points"]))
        except Exception:
            pass

    if not pts:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "wr": None,
            "avg": None,
            "median": None,
            "total": None,
            "cap20": None,
        }

    wins = sum(x > 0 for x in pts)
    losses = sum(x < 0 for x in pts)
    capped = [max(-20.0, min(20.0, x)) for x in pts]

    return {
        "n": len(pts),
        "wins": wins,
        "losses": losses,
        "wr": wins / len(pts) * 100,
        "avg": sum(pts) / len(pts),
        "median": statistics.median(pts),
        "total": sum(pts),
        "cap20": sum(capped),
    }


def fmt(label, s):
    if not s["n"]:
        return f"{label:42s} n=0"

    return (
        f"{label:42s} "
        f"n={s['n']:3d} "
        f"win={s['wins']:3d} "
        f"loss={s['losses']:3d} "
        f"wr={s['wr']:6.2f}% "
        f"avg={s['avg']:+8.2f} "
        f"median={s['median']:+7.2f} "
        f"total={s['total']:+9.2f} "
        f"cap20={s['cap20']:+9.2f}"
    )


def candidate(rows):
    return [
        r for r in rows
        if str(r.get("frozen_candidate")).lower() == "true"
        or r.get("frozen_candidate") is True
    ]


def match_rows(rows):
    return [r for r in rows if r.get("relation") == "MATCH"]


def intensity_match(rows):
    out = []
    for r in rows:
        if r.get("relation") != "MATCH":
            continue

        try:
            x = float(r.get("intensity_sum_abs_pct"))
        except Exception:
            continue

        if FROZEN_INTENSITY_LOW <= x < FROZEN_INTENSITY_HIGH:
            out.append(r)

    return out


def robustness_block(lines, title, rows):
    lines.append("")
    lines.append("=" * 128)
    lines.append(title)
    lines.append("=" * 128)
    lines.append(fmt("candidate", summarize(rows)))

    if not rows:
        return

    points = sorted(
        [(float(r["points"]), r) for r in rows],
        key=lambda x: x[0],
    )

    best = points[-1]
    without_best = list(rows)
    without_best.remove(best[1])

    lines.append(
        "best winner = "
        f"{best[0]:+.2f} "
        f"{best[1]['session_date']} "
        f"{best[1]['entry_time']}"
    )
    lines.append(
        fmt(
            "without single best winner",
            summarize(without_best),
        )
    )

    sessions = sorted(
        {
            r["session_date"]
            for r in rows
            if r.get("session_date")
        }
    )

    folds = []

    for d in sessions:
        fold = [
            r for r in rows
            if r.get("session_date") != d
        ]
        s = summarize(fold)

        if s["n"]:
            folds.append((d, s))

    if folds:
        pos = sum(s["total"] > 0 for _, s in folds)
        min_total = min(s["total"] for _, s in folds)
        max_total = max(s["total"] for _, s in folds)
        min_wr = min(s["wr"] for _, s in folds)
        max_wr = max(s["wr"] for _, s in folds)

        lines.append(
            "LOSO "
            f"folds={len(folds)} "
            f"positive_total={pos}/{len(folds)} "
            f"total_range={min_total:+.2f}..{max_total:+.2f} "
            f"wr_range={min_wr:.2f}%..{max_wr:.2f}%"
        )


def report_main(lines, rows, main_dates):
    u = usable(rows)
    m = match_rows(u)
    im = intensity_match(u)
    c = candidate(u)

    lines.append("")
    lines.append("=" * 128)
    lines.append("60-SESSION MAIN VALIDATION")
    lines.append("=" * 128)
    lines.append("latest 60 real-OI dates:")
    lines.append(" ".join(main_dates))
    lines.append("")
    lines.append(fmt("BASELINE ALL AVAILABLE", summarize(u)))
    lines.append(fmt("MATCH ONLY", summarize(m)))
    lines.append(fmt("MATCH + intensity 3-<5%", summarize(im)))
    lines.append(fmt("FROZEN CANDIDATE + no 13h", summarize(c)))

    lines.append("")
    lines.append("FROZEN CANDIDATE BY DIRECTION")
    for d in ["BULLISH", "BEARISH"]:
        lines.append(
            fmt(
                d,
                summarize([r for r in c if r.get("direction") == d]),
            )
        )

    lines.append("")
    lines.append("FROZEN CANDIDATE BY DOMINANT LEG")
    for leg in [
        "PE_BUILD",
        "CE_UNWIND",
        "CE_BUILD",
        "PE_UNWIND",
    ]:
        lines.append(
            fmt(
                leg,
                summarize([r for r in c if r.get("dominant_leg") == leg]),
            )
        )

    robustness_block(
        lines,
        "60-SESSION FROZEN CANDIDATE ROBUSTNESS",
        c,
    )


def report_directional_set(
    lines,
    title,
    rows,
    allowed_dates,
    expected_direction,
):
    u = [
        r for r in usable(rows)
        if r.get("session_date") in allowed_dates
    ]

    expected = [
        r for r in u
        if r.get("direction") == expected_direction
    ]

    m = match_rows(expected)
    im = intensity_match(expected)
    c = candidate(expected)

    lines.append("")
    lines.append("=" * 128)
    lines.append(title)
    lines.append("=" * 128)
    lines.append(
        f"expected Hilega direction = {expected_direction}"
    )
    lines.append(
        f"sessions requested = {len(allowed_dates)}"
    )
    lines.append(
        "sessions with usable trade rows = "
        f"{len(set(r['session_date'] for r in u))}"
    )
    lines.append("")
    lines.append(fmt("ALL EXPECTED-DIRECTION TRADES", summarize(expected)))
    lines.append(fmt("MATCH ONLY", summarize(m)))
    lines.append(fmt("MATCH + intensity 3-<5%", summarize(im)))
    lines.append(fmt("FROZEN CANDIDATE + no 13h", summarize(c)))

    lines.append("")
    lines.append("FROZEN CANDIDATE DOMINANT LEG")
    legs = (
        ["PE_BUILD", "CE_UNWIND"]
        if expected_direction == "BULLISH"
        else ["CE_BUILD", "PE_UNWIND"]
    )

    for leg in legs:
        lines.append(
            fmt(
                leg,
                summarize(
                    [r for r in c if r.get("dominant_leg") == leg]
                ),
            )
        )

    robustness_block(
        lines,
        f"{title} — FROZEN CANDIDATE ROBUSTNESS",
        c,
    )


def main():
    args = parse_args()

    oi_sources = discover_oi_sources()
    all_dates = sorted(oi_sources)

    if len(all_dates) < MAIN_SESSION_COUNT:
        raise SystemExit(
            f"Only {len(all_dates)} real-OI sessions found; "
            f"need at least {MAIN_SESSION_COUNT}."
        )

    main_dates = all_dates[-MAIN_SESSION_COUNT:]

    missing_directional_oi = [
        d for d in DIRECTIONAL_36
        if d not in oi_sources
    ]

    if missing_directional_oi:
        print(
            "WARNING: directional-session dates without OI source:",
            " ".join(missing_directional_oi),
        )

    target_dates = sorted(
        set(main_dates + DIRECTIONAL_36)
    )

    existing_replay = [
        d for d in target_dates
        if replay_file(d).exists()
    ]

    missing_replay = [
        d for d in target_dates
        if not replay_file(d).exists()
    ]

    print("=" * 120)
    print("60-SESSION + 18 BULLISH + 18 BEARISH VALIDATION")
    print("=" * 120)
    print("real OI sessions discovered =", len(all_dates))
    print("main latest sessions         =", len(main_dates))
    print("directional frozen sessions  =", len(DIRECTIONAL_36))
    print("union dates requiring replay =", len(target_dates))
    print("existing replay dates        =", len(existing_replay))
    print("missing replay dates         =", len(missing_replay))

    if args.run_replay:
        # Re-run all target dates in one deterministic historical replay.
        run_replay(target_dates)

    elif not args.skip_replay and missing_replay:
        print()
        print("Replay is missing for some required dates.")
        print("Run again with --run-replay")
        print()
        print("MISSING REPLAY DATES:")
        for d in missing_replay:
            print(d)
        raise SystemExit(2)

    # Re-check after optional build.
    still_missing = [
        d for d in target_dates
        if not replay_file(d).exists()
    ]

    if still_missing:
        print()
        print("WARNING: replay files still missing:")
        for d in still_missing:
            print(d)

    main_rows = build_join(
        main_dates,
        oi_sources,
        "MAIN_60",
    )

    directional_rows = build_join(
        DIRECTIONAL_36,
        oi_sources,
        "DIRECTIONAL_36",
    )

    write_csv(JOIN_CSV, main_rows)
    write_csv(DIRECTIONAL_CSV, directional_rows)

    lines = []
    lines.append("=" * 128)
    lines.append(
        "HILEGA 60-SESSION + 18 BULLISH + 18 BEARISH OI VALIDATION"
    )
    lines.append(
        "FROZEN RULE TEST — NO RETUNING OF THE 3-5% / 13H CANDIDATE"
    )
    lines.append("=" * 128)

    report_main(
        lines,
        main_rows,
        main_dates,
    )

    report_directional_set(
        lines,
        "FROZEN 18 BULLISH DIRECTIONAL SESSIONS",
        directional_rows,
        set(BULLISH_DIRECTIONAL_18),
        "BULLISH",
    )

    report_directional_set(
        lines,
        "FROZEN 18 BEARISH DIRECTIONAL SESSIONS",
        directional_rows,
        set(BEARISH_DIRECTIONAL_18),
        "BEARISH",
    )

    SUMMARY_TXT.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print()
    print("\n".join(lines))

    print()
    print("=" * 128)
    print("OUTPUT FILES")
    print("=" * 128)
    print("MAIN JOIN CSV      =", JOIN_CSV)
    print("DIRECTIONAL CSV    =", DIRECTIONAL_CSV)
    print("SUMMARY            =", SUMMARY_TXT)
    if args.run_replay:
        print("REPLAY BUILD LOG   =", REPLAY_LOG)


if __name__ == "__main__":
    main()
