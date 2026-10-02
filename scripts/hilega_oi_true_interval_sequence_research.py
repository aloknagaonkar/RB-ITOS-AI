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
# HILEGA + OI/PCR TRUE INTERVAL SEQUENCE RESEARCH V2
# ============================================================
#
# IMPORTANT CORRECTION VS V1:
#
# V1 labels such as "15m -> 10m -> 5m" were based on cumulative
# comparisons:
#   T vs T-15
#   T vs T-10
#   T vs T-5
#
# Those are multi-horizon features, but they are NOT true temporal
# transitions between consecutive intervals.
#
# V2 computes true causal intervals over the SAME signal-time
# physical strike panel:
#   I1 = T-15 -> T-10
#   I2 = T-10 -> T-5
#   I3 = T-5  -> T
#
# PCR path is also corrected:
#   PCR(T-15), PCR(T-10), PCR(T-5), PCR(T)
#
# Research only:
# - Hilega unchanged
# - no execution
# - no paper orders
# - no signal blocking
# - moving ATM at signal T
# - exact same physical strikes across all four snapshots
# - no interpolation/substitution
# ============================================================

STEP = 50
SESSION_COUNT = 180

MODEL_C_WINGS = {
    0: 3,
    1: 2,
    2: 5,
    3: 5,
    4: 4,
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
    "data/historical-evidence/hilega-directional-replay-v1"
)

OUT_DIR = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "true-interval-sequence-v2"
)
OUT_DIR.mkdir(parents=True, exist_ok=True)

FEATURES_CSV = OUT_DIR / "hilega-180-true-interval-sequence-features-v2.csv"
SEQUENCE_CSV = OUT_DIR / "hilega-180-true-interval-sequence-summary-v2.csv"
SUMMARY_TXT = OUT_DIR / "hilega-180-true-interval-sequence-report-v2.txt"
REPLAY_LOG = OUT_DIR / "historical-replay-build-v2.log"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--run-replay", action="store_true")
    p.add_argument("--skip-replay", action="store_true")
    return p.parse_args()


def valid_oi_row(r):
    try:
        ce = r.get("ce_open_interest")
        pe = r.get("pe_open_interest")
        if ce is None or pe is None:
            return False
        return float(ce) != 0 or float(pe) != 0
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

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    REPLAY_LOG.write_text(proc.stdout or "", encoding="utf-8")

    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


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
        info["path"].read_text(encoding="utf-8", errors="ignore")
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

        snapshots[ts][strike] = {"ce": ce, "pe": pe}

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


def interval_features(start_agg, end_agg, direction, prefix):
    ce_delta = end_agg["ce"] - start_agg["ce"]
    pe_delta = end_agg["pe"] - start_agg["pe"]

    ce_pct = pct(ce_delta, start_agg["ce"])
    pe_pct = pct(pe_delta, start_agg["pe"])

    pcr_start = pcr(start_agg["pe"], start_agg["ce"])
    pcr_end = pcr(end_agg["pe"], end_agg["ce"])

    state = classify(ce_delta, pe_delta)
    rel = relation(direction, state)

    intensity = (
        abs(ce_pct) + abs(pe_pct)
        if ce_pct is not None and pe_pct is not None
        else None
    )

    return {
        f"{prefix}_ce_pct": ce_pct,
        f"{prefix}_pe_pct": pe_pct,
        f"{prefix}_intensity": intensity,
        f"{prefix}_pcr_start": pcr_start,
        f"{prefix}_pcr_end": pcr_end,
        f"{prefix}_pcr_delta": (
            pcr_end - pcr_start
            if pcr_start is not None and pcr_end is not None
            else None
        ),
        f"{prefix}_state": state,
        f"{prefix}_relation": rel,
    }


def classify_pcr_path(values):
    if any(v is None for v in values):
        return "INCOMPLETE"

    a, b, c, d = values

    if a < b < c < d:
        return "STEADY_RISE"
    if a > b > c > d:
        return "STEADY_FALL"

    diffs = [b - a, c - b, d - c]

    pos = sum(x > 0 for x in diffs)
    neg = sum(x < 0 for x in diffs)

    if pos >= 2 and diffs[-1] > 0:
        return "MOSTLY_RISING"
    if neg >= 2 and diffs[-1] < 0:
        return "MOSTLY_FALLING"

    return "MIXED"


def build_features(dates, sources):
    out = []

    for d in dates:
        info = sources.get(d)
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

            t0 = datetime(
                session_dt.year,
                session_dt.month,
                session_dt.day,
                hh,
                mm,
                tzinfo=tz,
            )

            timestamps = {
                "t15": t0 - timedelta(minutes=15),
                "t10": t0 - timedelta(minutes=10),
                "t5": t0 - timedelta(minutes=5),
                "t0": t0,
            }

            signal_atm = oi["atm_by_ts"].get(t0)

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

            if signal_atm is None:
                base["data_status"] = "SIGNAL_ATM_MISSING"
                out.append(base)
                continue

            strikes = [
                signal_atm + i * STEP
                for i in range(-wings, wings + 1)
            ]

            snapshots = {}
            missing = None

            for key, ts in timestamps.items():
                snap = oi["snapshots"].get(ts)
                if snap is None:
                    missing = f"{key.upper()}_SNAPSHOT_MISSING"
                    break

                agg = aggregate(snap, strikes)
                if agg is None:
                    missing = f"{key.upper()}_INCOMPLETE_SAME_PHYSICAL_PANEL"
                    break

                snapshots[key] = agg

            base.update({
                "signal_atm": signal_atm,
                "strike_low": min(strikes),
                "strike_high": max(strikes),
            })

            if missing:
                base["data_status"] = missing
                out.append(base)
                continue

            base["data_status"] = "AVAILABLE"

            # True consecutive intervals:
            # T-15 -> T-10, T-10 -> T-5, T-5 -> T.
            base.update(
                interval_features(
                    snapshots["t15"],
                    snapshots["t10"],
                    trade["direction"],
                    "i15_10",
                )
            )
            base.update(
                interval_features(
                    snapshots["t10"],
                    snapshots["t5"],
                    trade["direction"],
                    "i10_5",
                )
            )
            base.update(
                interval_features(
                    snapshots["t5"],
                    snapshots["t0"],
                    trade["direction"],
                    "i5_0",
                )
            )

            base["state_sequence_true"] = " -> ".join([
                base["i15_10_state"],
                base["i10_5_state"],
                base["i5_0_state"],
            ])

            base["relation_sequence_true"] = " -> ".join([
                base["i15_10_relation"],
                base["i10_5_relation"],
                base["i5_0_relation"],
            ])

            pcr_values = [
                pcr(snapshots["t15"]["pe"], snapshots["t15"]["ce"]),
                pcr(snapshots["t10"]["pe"], snapshots["t10"]["ce"]),
                pcr(snapshots["t5"]["pe"], snapshots["t5"]["ce"]),
                pcr(snapshots["t0"]["pe"], snapshots["t0"]["ce"]),
            ]

            base["pcr_t15"] = pcr_values[0]
            base["pcr_t10"] = pcr_values[1]
            base["pcr_t5"] = pcr_values[2]
            base["pcr_t0"] = pcr_values[3]
            base["pcr_path"] = classify_pcr_path(pcr_values)

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


def groups(rows, field):
    g = defaultdict(list)
    for r in rows:
        g[str(r.get(field, "UNKNOWN"))].append(r)
    return g


def sequence_summary_rows(rows):
    recs = []

    for seq, subset in groups(rows, "state_sequence_true").items():
        for direction in ["ALL", "BULLISH", "BEARISH"]:
            ss = subset if direction == "ALL" else [
                r for r in subset
                if r.get("direction") == direction
            ]

            s = summarize(ss)

            recs.append({
                "sequence": seq,
                "direction": direction,
                "n": s["n"],
                "wins": s["wins"],
                "losses": s["losses"],
                "win_rate": s["wr"],
                "avg_points": s["avg"],
                "median_points": s["median"],
                "total_points": s["total"],
                "cap20_points": s["cap20"],
            })

    return recs


def report_sequences(lines, rows, direction=None):
    subset = rows

    if direction:
        subset = [
            r for r in rows
            if r.get("direction") == direction
        ]

    ranked = []

    for seq, ss in groups(subset, "state_sequence_true").items():
        s = summarize(ss)
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

    title = direction or "ALL"

    lines.append("")
    lines.append("=" * 128)
    lines.append(
        f"TRUE STATE SEQUENCES T-15->T-10 -> T-10->T-5 -> T-5->T — {title} — min n=10"
    )
    lines.append("=" * 128)

    for seq, s in ranked[:20]:
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
    print("TRUE INTERVAL SEQUENCE RESEARCH V2")
    print("=" * 120)
    print("real OI sessions =", len(dates))
    print("date range        =", dates[0], "to", dates[-1])
    print("existing replay   =", len(dates) - len(missing_replay))
    print("missing replay    =", len(missing_replay))

    if args.run_replay:
        run_replay(dates)
    elif not args.skip_replay and missing_replay:
        print("Replay missing. Run with --run-replay")
        raise SystemExit(2)

    rows = build_features(dates, sources)
    write_csv(FEATURES_CSV, rows)

    available = [
        r for r in rows
        if r.get("data_status") == "AVAILABLE"
    ]

    write_csv(
        SEQUENCE_CSV,
        sequence_summary_rows(available),
    )

    lines = []
    lines.append("=" * 128)
    lines.append("HILEGA + OI/PCR TRUE INTERVAL SEQUENCE RESEARCH V2")
    lines.append("=" * 128)
    lines.append("")
    lines.append(
        "Corrected temporal intervals over the same signal-time physical strike panel:"
    )
    lines.append(
        "I1 = T-15 -> T-10 | I2 = T-10 -> T-5 | I3 = T-5 -> T"
    )
    lines.append("")
    lines.append(fmt("ALL AVAILABLE TRUE-SEQUENCE TRADES", summarize(available)))

    lines.append("")
    lines.append("=" * 128)
    lines.append("TRUE INTERVAL RELATION BASELINES")
    lines.append("=" * 128)

    for prefix, label in [
        ("i15_10", "T-15 -> T-10"),
        ("i10_5", "T-10 -> T-5"),
        ("i5_0", "T-5 -> T"),
    ]:
        for rel in ["MATCH", "OPPOSITE", "AMBIGUOUS"]:
            subset = [
                r for r in available
                if r.get(f"{prefix}_relation") == rel
            ]
            lines.append(fmt(f"{label} {rel}", summarize(subset)))

    lines.append("")
    lines.append("=" * 128)
    lines.append("TRUE RELATION SEQUENCES — min n=10")
    lines.append("=" * 128)

    ranked_rel = []

    for seq, subset in groups(
        available,
        "relation_sequence_true",
    ).items():
        s = summarize(subset)
        if s["n"] >= 10:
            ranked_rel.append((seq, s))

    ranked_rel.sort(
        key=lambda x: (
            x[1]["cap20"],
            x[1]["median"],
            x[1]["n"],
        ),
        reverse=True,
    )

    for seq, s in ranked_rel[:20]:
        lines.append(fmt(seq, s))

    report_sequences(lines, available, None)
    report_sequences(lines, available, "BULLISH")
    report_sequences(lines, available, "BEARISH")

    lines.append("")
    lines.append("=" * 128)
    lines.append("CORRECT PCR PATH T-15 -> T-10 -> T-5 -> T")
    lines.append("=" * 128)

    for k, subset in groups(available, "pcr_path").items():
        lines.append(fmt(k, summarize(subset)))

    lines.append("")
    lines.append("=" * 128)
    lines.append("BY HILEGA ROUTE")
    lines.append("=" * 128)

    for route in ["OPENING", "ROUTE_A", "ROUTE_B"]:
        subset = [
            r for r in available
            if r.get("route_family") == route
        ]
        lines.append(fmt(route, summarize(subset)))

    lines.append("")
    lines.append("=" * 128)
    lines.append("BY HILEGA DIRECTION")
    lines.append("=" * 128)

    for d in ["BULLISH", "BEARISH"]:
        subset = [
            r for r in available
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
