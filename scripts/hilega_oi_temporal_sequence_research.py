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
# HILEGA + OI/PCR TEMPORAL SEQUENCE RESEARCH V1
# ============================================================
#
# Research only.
# - Hilega directional logic unchanged.
# - Observation/research only.
# - No execution, paper orders, or signal blocking.
# - Uses moving ATM at signal time T.
# - Uses exact same physical strikes at T and T-horizon.
# - No interpolation, nearest-strike substitution, or synthetic OI.
#
# Goal:
# Study whether OI/PCR temporal sequences at 15m -> 10m -> 5m
# contain more information than a single 5m MATCH snapshot.
# ============================================================

STEP = 50
SESSION_COUNT = 180

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
    "temporal-sequence-v1"
)

OUT_DIR.mkdir(parents=True, exist_ok=True)

FEATURES_CSV = OUT_DIR / "hilega-180-temporal-sequence-features-v1.csv"
SEQUENCE_CSV = OUT_DIR / "hilega-180-temporal-sequence-summary-v1.csv"
SUMMARY_TXT = OUT_DIR / "hilega-180-temporal-sequence-report-v1.txt"
REPLAY_LOG = OUT_DIR / "historical-replay-build-v1.log"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--run-replay",
        action="store_true",
        help="Build/rebuild Hilega replay for all 180 dates.",
    )
    p.add_argument(
        "--skip-replay",
        action="store_true",
        help="Analyze only existing Hilega replay files.",
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
                    p.read_text(
                        encoding="utf-8",
                        errors="ignore",
                    )
                )
            except Exception:
                continue

            d = str(data.get("session_date", ""))
            rows = data.get("rows", [])

            if not d or not isinstance(rows, list):
                continue

            usable = sum(1 for r in rows if valid_oi_row(r))
            if usable == 0:
                continue

            old = found.get(d)
            if old is None or usable > old["usable"]:
                found[d] = {
                    "path": p,
                    "usable": usable,
                    "expiry": str(data.get("expiry", "")),
                }

    return found


def replay_file(d):
    return TRADES_ROOT / d / "directional-trades.csv"


def run_replay(dates):
    cmd = [
        sys.executable,
        "-m",
        "market_lab.hilega_directional_historical_replay_cli_v1",
        "--dates",
        *dates,
    ]

    print("=" * 120)
    print("GENERATING HILEGA REPLAY FOR TEMPORAL-SEQUENCE RESEARCH")
    print("=" * 120)
    print("dates =", len(dates))
    print("large replay output ->", REPLAY_LOG)

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

    print("replay = PASS")


def load_trades(d):
    p = replay_file(d)
    if not p.exists():
        return []

    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_ts(v):
    return datetime.fromisoformat(str(v))


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
    vals = []

    for s in strikes:
        item = snapshot.get(float(s))
        if item is None:
            return None
        vals.append(item)

    return {
        "ce": sum(v["ce"] for v in vals),
        "pe": sum(v["pe"] for v in vals),
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
        return "BUILD"
    if ce_delta < 0 and pe_delta < 0:
        return "UNWIND"
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


def days_to_expiry(session_date, expiry):
    try:
        return (
            date.fromisoformat(expiry)
            - date.fromisoformat(session_date)
        ).days
    except Exception:
        return None


def horizon_features(
    oi,
    signal_ts,
    current_snapshot,
    strikes,
    direction,
    minutes,
):
    previous_ts = signal_ts - timedelta(minutes=minutes)
    previous_snapshot = oi["snapshots"].get(previous_ts)

    prefix = f"h{minutes}"

    if previous_snapshot is None:
        return {
            f"{prefix}_status": "PREVIOUS_SNAPSHOT_MISSING",
        }

    current = aggregate(current_snapshot, strikes)
    previous = aggregate(previous_snapshot, strikes)

    if current is None or previous is None:
        return {
            f"{prefix}_status": "INCOMPLETE_SAME_PHYSICAL_PANEL",
        }

    ce_delta = current["ce"] - previous["ce"]
    pe_delta = current["pe"] - previous["pe"]

    ce_pct = pct(ce_delta, previous["ce"])
    pe_pct = pct(pe_delta, previous["pe"])

    pcr_now = pcr(current["pe"], current["ce"])
    pcr_prev = pcr(previous["pe"], previous["ce"])

    state = classify(ce_delta, pe_delta)
    rel = relation(direction, state)

    intensity = (
        abs(ce_pct) + abs(pe_pct)
        if ce_pct is not None and pe_pct is not None
        else None
    )

    return {
        f"{prefix}_status": "AVAILABLE",
        f"{prefix}_ce_pct": ce_pct,
        f"{prefix}_pe_pct": pe_pct,
        f"{prefix}_intensity": intensity,
        f"{prefix}_pcr_previous": pcr_prev,
        f"{prefix}_pcr_current": pcr_now,
        f"{prefix}_pcr_delta": (
            pcr_now - pcr_prev
            if pcr_now is not None and pcr_prev is not None
            else None
        ),
        f"{prefix}_state": state,
        f"{prefix}_relation": rel,
    }


def sequence_label(r):
    if not all(
        r.get(f"h{x}_status") == "AVAILABLE"
        for x in (15, 10, 5)
    ):
        return "INCOMPLETE"

    return " -> ".join([
        r["h15_state"],
        r["h10_state"],
        r["h5_state"],
    ])


def relation_sequence_label(r):
    if not all(
        r.get(f"h{x}_status") == "AVAILABLE"
        for x in (15, 10, 5)
    ):
        return "INCOMPLETE"

    return " -> ".join([
        r["h15_relation"],
        r["h10_relation"],
        r["h5_relation"],
    ])


def pcr_trend_label(r):
    vals = [
        r.get("h15_pcr_current"),
        r.get("h10_pcr_current"),
        r.get("h5_pcr_current"),
    ]

    if any(v is None for v in vals):
        return "INCOMPLETE"

    a, b, c = vals

    if a < b < c:
        return "RISING"
    if a > b > c:
        return "FALLING"
    return "MIXED"


def build_features(session_dates, oi_sources):
    out = []

    for d in session_dates:
        info = oi_sources.get(d)
        trades = load_trades(d)

        if info is None:
            out.append({
                "session_date": d,
                "data_status": "OI_SOURCE_MISSING",
            })
            continue

        if not trades:
            out.append({
                "session_date": d,
                "data_status": "HILEGA_REPLAY_MISSING_OR_NO_TRADES",
            })
            continue

        oi = load_oi_session(info)

        if not oi["snapshots"]:
            out.append({
                "session_date": d,
                "data_status": "OI_SNAPSHOTS_MISSING",
            })
            continue

        example_ts = next(iter(oi["snapshots"]))
        tz = example_ts.tzinfo
        session_dt = datetime.fromisoformat(d)
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

            current_snapshot = oi["snapshots"].get(signal_ts)
            signal_atm = oi["atm_by_ts"].get(signal_ts)

            base = {
                "session_date": d,
                "weekday": DAY_NAMES.get(weekday, str(weekday)),
                "expiry": oi["expiry"],
                "days_to_expiry": days_to_expiry(d, oi["expiry"]),
                "entry_time": trade["entry_time"],
                "time_bucket": time_bucket(trade["entry_time"]),
                "entry_event": trade["entry_event"],
                "route_family": route_family(trade["entry_event"]),
                "direction": trade["direction"],
                "exit_time": trade["exit_time"],
                "points": float(trade["points"]),
                "outcome": trade["outcome"],
                "wings": wings,
                "oi_source": oi["source"],
            }

            if current_snapshot is None:
                base["data_status"] = "CURRENT_SNAPSHOT_MISSING"
                out.append(base)
                continue

            if signal_atm is None:
                base["data_status"] = "SIGNAL_ATM_MISSING"
                out.append(base)
                continue

            strikes = [
                signal_atm + i * STEP
                for i in range(-wings, wings + 1)
            ]

            base.update({
                "signal_atm": signal_atm,
                "strike_low": min(strikes),
                "strike_high": max(strikes),
            })

            for minutes in [5, 10, 15]:
                base.update(
                    horizon_features(
                        oi,
                        signal_ts,
                        current_snapshot,
                        strikes,
                        trade["direction"],
                        minutes,
                    )
                )

            if base.get("h5_status") != "AVAILABLE":
                base["data_status"] = "H5_UNAVAILABLE"
                out.append(base)
                continue

            base["data_status"] = "AVAILABLE"
            base["state_sequence_15_10_5"] = sequence_label(base)
            base["relation_sequence_15_10_5"] = relation_sequence_label(base)
            base["pcr_trend_15_10_5"] = pcr_trend_label(base)

            out.append(base)

    return out


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


def to_float(v):
    try:
        if v in (None, ""):
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def summarize(rows):
    pts = [to_float(r.get("points")) for r in rows]
    pts = [x for x in pts if x is not None]

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
        return f"{label:62s} n=0"

    return (
        f"{label:62s} "
        f"n={s['n']:4d} "
        f"win={s['wins']:4d} "
        f"loss={s['losses']:4d} "
        f"wr={s['wr']:6.2f}% "
        f"avg={s['avg']:+8.2f} "
        f"median={s['median']:+7.2f} "
        f"total={s['total']:+10.2f} "
        f"cap20={s['cap20']:+10.2f}"
    )


def group_rows(rows, field):
    groups = defaultdict(list)
    for r in rows:
        groups[str(r.get(field, "UNKNOWN"))].append(r)
    return groups


def export_sequence_summary(rows):
    records = []

    complete = [
        r for r in rows
        if r.get("state_sequence_15_10_5") not in (None, "INCOMPLETE")
    ]

    for sequence, subset in group_rows(
        complete,
        "state_sequence_15_10_5",
    ).items():
        s = summarize(subset)

        for direction in ["ALL", "BULLISH", "BEARISH"]:
            ss = (
                subset
                if direction == "ALL"
                else [
                    r for r in subset
                    if r.get("direction") == direction
                ]
            )

            x = summarize(ss)

            records.append({
                "sequence": sequence,
                "direction": direction,
                "n": x["n"],
                "wins": x["wins"],
                "losses": x["losses"],
                "win_rate": x["wr"],
                "avg_points": x["avg"],
                "median_points": x["median"],
                "total_points": x["total"],
                "cap20_points": x["cap20"],
            })

    records.sort(
        key=lambda x: (
            x["direction"],
            -(x["n"] or 0),
            x["sequence"],
        )
    )

    write_csv(SEQUENCE_CSV, records)


def report_top_sequences(lines, rows, direction=None):
    complete = [
        r for r in rows
        if r.get("state_sequence_15_10_5") not in (None, "INCOMPLETE")
    ]

    if direction:
        complete = [
            r for r in complete
            if r.get("direction") == direction
        ]

    groups = group_rows(
        complete,
        "state_sequence_15_10_5",
    )

    ranked = []

    for seq, subset in groups.items():
        s = summarize(subset)
        if s["n"] >= 10:
            ranked.append((seq, s))

    ranked.sort(
        key=lambda x: (
            x[1]["cap20"],
            x[1]["median"],
            x[1]["n"],
        ),
        reverse=True,
    )

    label = direction or "ALL"

    lines.append("")
    lines.append("=" * 128)
    lines.append(
        f"TOP TEMPORAL STATE SEQUENCES — {label} — minimum n=10"
    )
    lines.append("=" * 128)

    if not ranked:
        lines.append("NONE")
        return

    for seq, s in ranked[:15]:
        lines.append(fmt(seq, s))


def main():
    args = parse_args()

    sources = discover_oi_sources()
    dates = sorted(sources)

    if len(dates) < SESSION_COUNT:
        raise SystemExit(
            f"Need {SESSION_COUNT} real-OI sessions; found {len(dates)}."
        )

    dates = dates[-SESSION_COUNT:]

    missing_replay = [
        d for d in dates
        if not replay_file(d).exists()
    ]

    print("=" * 120)
    print("180-SESSION OI/PCR TEMPORAL-SEQUENCE RESEARCH")
    print("=" * 120)
    print("real OI sessions =", len(dates))
    print("date range        =", dates[0], "to", dates[-1])
    print("existing replay   =", len(dates) - len(missing_replay))
    print("missing replay    =", len(missing_replay))

    if args.run_replay:
        run_replay(dates)

    elif not args.skip_replay and missing_replay:
        print()
        print("Replay missing. Run with --run-replay")
        raise SystemExit(2)

    rows = build_features(dates, sources)
    write_csv(FEATURES_CSV, rows)
    export_sequence_summary(rows)

    available = [
        r for r in rows
        if r.get("data_status") == "AVAILABLE"
    ]

    complete = [
        r for r in available
        if r.get("state_sequence_15_10_5") not in (None, "INCOMPLETE")
    ]

    lines = []
    lines.append("=" * 128)
    lines.append("HILEGA + OI/PCR TEMPORAL SEQUENCE RESEARCH V1")
    lines.append("=" * 128)
    lines.append("")
    lines.append(
        "Moving ATM at signal time T. Same physical strikes used for T vs T-5/T-10/T-15."
    )
    lines.append(
        "No nearest-strike substitution, interpolation, or synthetic OI."
    )
    lines.append("")
    lines.append(
        f"dates = {dates[0]} -> {dates[-1]} ({len(dates)} sessions)"
    )
    lines.append(fmt("ALL AVAILABLE HILEGA TRADES", summarize(available)))
    lines.append(fmt("COMPLETE 15/10/5 SEQUENCE TRADES", summarize(complete)))

    lines.append("")
    lines.append("=" * 128)
    lines.append("SINGLE-HORIZON RELATION BASELINES")
    lines.append("=" * 128)

    for h in [5, 10, 15]:
        for rel in ["MATCH", "OPPOSITE", "AMBIGUOUS"]:
            subset = [
                r for r in available
                if r.get(f"h{h}_relation") == rel
            ]
            lines.append(
                fmt(
                    f"{h}M {rel}",
                    summarize(subset),
                )
            )

    lines.append("")
    lines.append("=" * 128)
    lines.append("RELATION SEQUENCES 15M -> 10M -> 5M — minimum n=10")
    lines.append("=" * 128)

    rel_groups = group_rows(
        complete,
        "relation_sequence_15_10_5",
    )

    rel_ranked = []

    for seq, subset in rel_groups.items():
        s = summarize(subset)
        if s["n"] >= 10:
            rel_ranked.append((seq, s))

    rel_ranked.sort(
        key=lambda x: (
            x[1]["cap20"],
            x[1]["median"],
            x[1]["n"],
        ),
        reverse=True,
    )

    for seq, s in rel_ranked[:20]:
        lines.append(fmt(seq, s))

    report_top_sequences(lines, complete, None)
    report_top_sequences(lines, complete, "BULLISH")
    report_top_sequences(lines, complete, "BEARISH")

    lines.append("")
    lines.append("=" * 128)
    lines.append("PCR TREND 15M -> 10M -> 5M")
    lines.append("=" * 128)

    for k, subset in group_rows(
        complete,
        "pcr_trend_15_10_5",
    ).items():
        lines.append(fmt(k, summarize(subset)))

    lines.append("")
    lines.append("=" * 128)
    lines.append("TEMPORAL SEQUENCE BY HILEGA ROUTE")
    lines.append("=" * 128)

    for route in ["OPENING", "ROUTE_A", "ROUTE_B"]:
        subset = [
            r for r in complete
            if r.get("route_family") == route
        ]
        lines.append(fmt(route, summarize(subset)))

    lines.append("")
    lines.append("=" * 128)
    lines.append("TEMPORAL SEQUENCE BY DIRECTION")
    lines.append("=" * 128)

    for d in ["BULLISH", "BEARISH"]:
        subset = [
            r for r in complete
            if r.get("direction") == d
        ]
        lines.append(fmt(d, summarize(subset)))

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
    print("FEATURES CSV =", FEATURES_CSV)
    print("SEQUENCE CSV =", SEQUENCE_CSV)
    print("SUMMARY TXT  =", SUMMARY_TXT)
    if args.run_replay:
        print("REPLAY LOG   =", REPLAY_LOG)


if __name__ == "__main__":
    main()
