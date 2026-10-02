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
# HILEGA + PCR/OI 180-SESSION WALK-FORWARD RESEARCH
# ============================================================
#
# Research only.
# - Does not modify Hilega directional rules.
# - Does not enable execution, paper orders, or option selection.
# - Uses exact same physical strikes at T and T-horizon.
# - Uses latest signal-time moving ATM.
#
# Chronological partitions:
#   TRAIN      = oldest 60 real-OI sessions
#   VALIDATION = middle 60
#   EVALUATION = newest 60
#
# IMPORTANT:
# The newest sessions have already been inspected in prior research.
# Therefore EVALUATION is a retrospective walk-forward evaluation,
# NOT a pristine never-seen holdout. A future/live forward sample is
# still required before any production rule is frozen.
# ============================================================

SESSION_BLOCK = 60
STEP = 50

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
    "180-session-walkforward-v1"
)

OUT_DIR.mkdir(parents=True, exist_ok=True)

FEATURES_CSV = OUT_DIR / "hilega-180-session-features-v1.csv"
TRAIN_CSV = OUT_DIR / "train-oldest-60-v1.csv"
VALIDATION_CSV = OUT_DIR / "validation-middle-60-v1.csv"
EVALUATION_CSV = OUT_DIR / "evaluation-newest-60-v1.csv"
CANDIDATES_CSV = OUT_DIR / "train-discovered-candidates-v1.csv"
SUMMARY_TXT = OUT_DIR / "walkforward-summary-v1.txt"
REPLAY_LOG = OUT_DIR / "historical-replay-build-v1.log"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--run-replay",
        action="store_true",
        help="Build/rebuild Hilega replay for all 180 target dates.",
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
    print("GENERATING HILEGA REPLAY FOR 180-SESSION WALK-FORWARD")
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


def days_to_expiry(session_date, expiry):
    try:
        return (
            date.fromisoformat(expiry)
            - date.fromisoformat(session_date)
        ).days
    except Exception:
        return None


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
        f"{prefix}_ce_delta": ce_delta,
        f"{prefix}_pe_delta": pe_delta,
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


def build_features(session_dates, oi_sources, split_name):
    out = []

    for d in session_dates:
        info = oi_sources.get(d)
        trades = load_trades(d)

        if info is None:
            out.append({
                "split": split_name,
                "session_date": d,
                "data_status": "OI_SOURCE_MISSING",
            })
            continue

        if not trades:
            out.append({
                "split": split_name,
                "session_date": d,
                "data_status": "HILEGA_REPLAY_MISSING_OR_NO_TRADES",
            })
            continue

        oi = load_oi_session(info)

        if not oi["snapshots"]:
            out.append({
                "split": split_name,
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
                "split": split_name,
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

            # 5m / 10m / 15m — always same signal-time physical panel.
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

            ce5 = base.get("h5_ce_pct")
            pe5 = base.get("h5_pe_pct")

            base["dominant_leg_5m"] = dominant_leg(
                trade["direction"],
                ce5,
                pe5,
            )

            out.append(base)

    return out


def write_csv(path, rows):
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def available(rows):
    return [
        r for r in rows
        if r.get("data_status") == "AVAILABLE"
    ]


def to_float(v):
    try:
        if v in (None, ""):
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def summarize(rows):
    pts = [
        to_float(r.get("points"))
        for r in rows
    ]
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
        return f"{label:50s} n=0"

    return (
        f"{label:50s} "
        f"n={s['n']:3d} "
        f"win={s['wins']:3d} "
        f"loss={s['losses']:3d} "
        f"wr={s['wr']:6.2f}% "
        f"avg={s['avg']:+8.2f} "
        f"median={s['median']:+7.2f} "
        f"total={s['total']:+9.2f} "
        f"cap20={s['cap20']:+9.2f}"
    )


def loso_stats(rows):
    sessions = sorted(
        {
            r.get("session_date")
            for r in rows
            if r.get("session_date")
        }
    )

    folds = []

    for d in sessions:
        s = summarize(
            [
                r for r in rows
                if r.get("session_date") != d
            ]
        )
        if s["n"]:
            folds.append(s)

    if not folds:
        return None

    return {
        "folds": len(folds),
        "positive_total": sum(s["total"] > 0 for s in folds),
        "positive_cap20": sum(s["cap20"] > 0 for s in folds),
        "total_min": min(s["total"] for s in folds),
        "total_max": max(s["total"] for s in folds),
        "cap20_min": min(s["cap20"] for s in folds),
        "cap20_max": max(s["cap20"] for s in folds),
    }


# ============================================================
# TRAIN-ONLY candidate family
# ============================================================
#
# Limited, explicit search family. No validation/evaluation data
# are used to construct these candidates.
#
# Minimum train sample size = 15.
# Candidate ranking emphasizes capped points and median, not raw
# total, to reduce dependence on extreme directional winners.
# ============================================================

INTENSITY_BANDS = [
    ("ANY_INTENSITY", None, None),
    ("INT_0_2", 0.0, 2.0),
    ("INT_2_3", 2.0, 3.0),
    ("INT_3_5", 3.0, 5.0),
    ("INT_5_8", 5.0, 8.0),
]

DIRECTIONS = [
    "ANY_DIRECTION",
    "BULLISH",
    "BEARISH",
]

TIME_MODES = [
    "ALL_TIMES",
    "EXCLUDE_13H",
]

RELATION_10_MODES = [
    "ANY_10M",
    "MATCH_10M",
    "NOT_OPPOSITE_10M",
]

RELATION_15_MODES = [
    "ANY_15M",
    "MATCH_15M",
    "NOT_OPPOSITE_15M",
]


def candidate_match(
    r,
    intensity_low,
    intensity_high,
    direction_mode,
    time_mode,
    rel10_mode,
    rel15_mode,
):
    if r.get("h5_relation") != "MATCH":
        return False

    if intensity_low is not None:
        x = to_float(r.get("h5_intensity"))
        if x is None or not (
            intensity_low <= x < intensity_high
        ):
            return False

    if (
        direction_mode != "ANY_DIRECTION"
        and r.get("direction") != direction_mode
    ):
        return False

    if (
        time_mode == "EXCLUDE_13H"
        and r.get("time_bucket") == "13:00-13:59"
    ):
        return False

    if rel10_mode == "MATCH_10M":
        if r.get("h10_relation") != "MATCH":
            return False

    elif rel10_mode == "NOT_OPPOSITE_10M":
        if r.get("h10_status") != "AVAILABLE":
            return False
        if r.get("h10_relation") == "OPPOSITE":
            return False

    if rel15_mode == "MATCH_15M":
        if r.get("h15_relation") != "MATCH":
            return False

    elif rel15_mode == "NOT_OPPOSITE_15M":
        if r.get("h15_status") != "AVAILABLE":
            return False
        if r.get("h15_relation") == "OPPOSITE":
            return False

    return True


def discover_train_candidates(train_rows):
    candidates = []

    for band_name, lo, hi in INTENSITY_BANDS:
        for direction_mode in DIRECTIONS:
            for time_mode in TIME_MODES:
                for rel10_mode in RELATION_10_MODES:
                    for rel15_mode in RELATION_15_MODES:

                        name = "|".join([
                            band_name,
                            direction_mode,
                            time_mode,
                            rel10_mode,
                            rel15_mode,
                        ])

                        subset = [
                            r for r in train_rows
                            if candidate_match(
                                r,
                                lo,
                                hi,
                                direction_mode,
                                time_mode,
                                rel10_mode,
                                rel15_mode,
                            )
                        ]

                        s = summarize(subset)

                        if s["n"] < 15:
                            continue

                        loso = loso_stats(subset)

                        if loso is None:
                            continue

                        # Conservative train eligibility:
                        # positive capped result,
                        # non-negative median,
                        # >= 45% winners,
                        # >= 70% LOSO folds positive on capped total.
                        eligible = (
                            s["cap20"] > 0
                            and s["median"] >= 0
                            and s["wr"] >= 45.0
                            and (
                                loso["positive_cap20"]
                                / loso["folds"]
                                >= 0.70
                            )
                        )

                        # Rank score is descriptive only.
                        # More weight on cap20/median/sample size than raw total.
                        score = (
                            (s["cap20"] / s["n"])
                            + 0.50 * s["median"]
                            + 0.02 * s["n"]
                        )

                        candidates.append({
                            "candidate_name": name,
                            "intensity_band": band_name,
                            "intensity_low": lo,
                            "intensity_high": hi,
                            "direction_mode": direction_mode,
                            "time_mode": time_mode,
                            "rel10_mode": rel10_mode,
                            "rel15_mode": rel15_mode,
                            "train_n": s["n"],
                            "train_wins": s["wins"],
                            "train_losses": s["losses"],
                            "train_wr": s["wr"],
                            "train_avg": s["avg"],
                            "train_median": s["median"],
                            "train_total": s["total"],
                            "train_cap20": s["cap20"],
                            "train_loso_positive_cap20":
                                loso["positive_cap20"],
                            "train_loso_folds":
                                loso["folds"],
                            "train_eligible": eligible,
                            "train_rank_score": score,
                        })

    candidates.sort(
        key=lambda x: (
            x["train_eligible"],
            x["train_rank_score"],
        ),
        reverse=True,
    )

    return candidates


def apply_candidate(rows, c):
    band = c["intensity_band"]

    band_lookup = {
        x[0]: (x[1], x[2])
        for x in INTENSITY_BANDS
    }

    lo, hi = band_lookup[band]

    return [
        r for r in rows
        if candidate_match(
            r,
            lo,
            hi,
            c["direction_mode"],
            c["time_mode"],
            c["rel10_mode"],
            c["rel15_mode"],
        )
    ]


def evaluate_candidates(candidates, validation_rows, evaluation_rows):
    # Only first 10 train-eligible candidates are carried forward.
    carried = [
        c for c in candidates
        if c["train_eligible"]
    ][:10]

    for c in carried:
        val = summarize(
            apply_candidate(validation_rows, c)
        )

        c.update({
            "validation_n": val["n"],
            "validation_wins": val["wins"],
            "validation_losses": val["losses"],
            "validation_wr": val["wr"],
            "validation_avg": val["avg"],
            "validation_median": val["median"],
            "validation_total": val["total"],
            "validation_cap20": val["cap20"],
        })

        # Predeclared validation gate.
        c["validation_pass"] = (
            val["n"] >= 10
            and val["cap20"] is not None
            and val["cap20"] > 0
            and val["median"] is not None
            and val["median"] >= 0
            and val["wr"] is not None
            and val["wr"] >= 45.0
        )

    survivors = [
        c for c in carried
        if c.get("validation_pass")
    ]

    # Evaluation is reported for validation survivors only.
    for c in survivors:
        ev = summarize(
            apply_candidate(evaluation_rows, c)
        )

        c.update({
            "evaluation_n": ev["n"],
            "evaluation_wins": ev["wins"],
            "evaluation_losses": ev["losses"],
            "evaluation_wr": ev["wr"],
            "evaluation_avg": ev["avg"],
            "evaluation_median": ev["median"],
            "evaluation_total": ev["total"],
            "evaluation_cap20": ev["cap20"],
        })

    return carried, survivors


def main():
    args = parse_args()

    sources = discover_oi_sources()
    dates = sorted(sources)

    if len(dates) < 180:
        raise SystemExit(
            f"Need 180 real-OI sessions; found {len(dates)}."
        )

    # Exactly 180 chronological real-OI sessions.
    dates = dates[-180:]

    train_dates = dates[:60]
    validation_dates = dates[60:120]
    evaluation_dates = dates[120:180]

    missing_replay = [
        d for d in dates
        if not replay_file(d).exists()
    ]

    print("=" * 120)
    print("180-SESSION CHRONOLOGICAL WALK-FORWARD")
    print("=" * 120)
    print("real OI sessions =", len(dates))
    print("TRAIN             =", train_dates[0], "to", train_dates[-1])
    print("VALIDATION        =", validation_dates[0], "to", validation_dates[-1])
    print("EVALUATION        =", evaluation_dates[0], "to", evaluation_dates[-1])
    print("existing replay   =", 180 - len(missing_replay))
    print("missing replay    =", len(missing_replay))

    if args.run_replay:
        run_replay(dates)

    elif not args.skip_replay and missing_replay:
        print()
        print("Replay missing. Run with --run-replay")
        print("missing dates =", len(missing_replay))
        raise SystemExit(2)

    still_missing = [
        d for d in dates
        if not replay_file(d).exists()
    ]

    if still_missing:
        print("WARNING: replay still missing =", len(still_missing))

    train_rows = build_features(
        train_dates,
        sources,
        "TRAIN_OLDEST_60",
    )
    val_rows = build_features(
        validation_dates,
        sources,
        "VALIDATION_MIDDLE_60",
    )
    eval_rows = build_features(
        evaluation_dates,
        sources,
        "EVALUATION_NEWEST_60",
    )

    all_rows = train_rows + val_rows + eval_rows

    write_csv(FEATURES_CSV, all_rows)
    write_csv(TRAIN_CSV, train_rows)
    write_csv(VALIDATION_CSV, val_rows)
    write_csv(EVALUATION_CSV, eval_rows)

    train_a = available(train_rows)
    val_a = available(val_rows)
    eval_a = available(eval_rows)

    candidates = discover_train_candidates(train_a)
    carried, survivors = evaluate_candidates(
        candidates,
        val_a,
        eval_a,
    )

    write_csv(CANDIDATES_CSV, candidates)

    lines = []

    lines.append("=" * 128)
    lines.append("HILEGA + PCR/OI 180-SESSION WALK-FORWARD RESEARCH")
    lines.append("=" * 128)
    lines.append("")
    lines.append(
        "IMPORTANT: newest sessions were previously inspected; "
        "EVALUATION is retrospective, not a pristine never-seen holdout."
    )
    lines.append(
        "A future/live forward sample is still required before any "
        "production filter is frozen."
    )

    lines.append("")
    lines.append("DATE PARTITIONS")
    lines.append(
        f"TRAIN      {train_dates[0]} -> {train_dates[-1]}"
    )
    lines.append(
        f"VALIDATION {validation_dates[0]} -> {validation_dates[-1]}"
    )
    lines.append(
        f"EVALUATION {evaluation_dates[0]} -> {evaluation_dates[-1]}"
    )

    lines.append("")
    lines.append("=" * 128)
    lines.append("BASELINES BY SPLIT")
    lines.append("=" * 128)

    for name, rows in [
        ("TRAIN", train_a),
        ("VALIDATION", val_a),
        ("EVALUATION", eval_a),
    ]:
        lines.append(fmt(f"{name} ALL AVAILABLE", summarize(rows)))

        m5 = [
            r for r in rows
            if r.get("h5_relation") == "MATCH"
        ]
        lines.append(fmt(f"{name} 5M MATCH", summarize(m5)))

        m10 = [
            r for r in rows
            if r.get("h10_relation") == "MATCH"
        ]
        lines.append(fmt(f"{name} 10M MATCH", summarize(m10)))

        m15 = [
            r for r in rows
            if r.get("h15_relation") == "MATCH"
        ]
        lines.append(fmt(f"{name} 15M MATCH", summarize(m15)))

    lines.append("")
    lines.append("=" * 128)
    lines.append("TRAIN-ONLY DISCOVERY")
    lines.append("=" * 128)
    lines.append(
        "Limited explicit candidate family; minimum TRAIN n=15."
    )
    lines.append(
        "Eligibility requires positive capped points, non-negative median, "
        ">=45% WR, and >=70% positive LOSO capped folds."
    )
    lines.append("")

    eligible = [
        c for c in candidates
        if c["train_eligible"]
    ]

    lines.append(
        f"train candidates tested = {len(candidates)}"
    )
    lines.append(
        f"train eligible          = {len(eligible)}"
    )
    lines.append(
        f"carried to validation   = {len(carried)}"
    )
    lines.append(
        f"validation survivors    = {len(survivors)}"
    )

    for i, c in enumerate(carried, 1):
        lines.append("")
        lines.append(
            f"#{i} {c['candidate_name']}"
        )

        lines.append(
            "  TRAIN "
            f"n={c['train_n']} "
            f"wr={c['train_wr']:.2f}% "
            f"median={c['train_median']:+.2f} "
            f"total={c['train_total']:+.2f} "
            f"cap20={c['train_cap20']:+.2f}"
        )

        if c.get("validation_n") is not None:
            lines.append(
                "  VALIDATION "
                f"n={c['validation_n']} "
                f"wr={c['validation_wr']:.2f}% "
                f"median={c['validation_median']:+.2f} "
                f"total={c['validation_total']:+.2f} "
                f"cap20={c['validation_cap20']:+.2f} "
                f"PASS={c['validation_pass']}"
            )

        if c.get("evaluation_n") is not None:
            lines.append(
                "  EVALUATION "
                f"n={c['evaluation_n']} "
                f"wr={c['evaluation_wr']:.2f}% "
                f"median={c['evaluation_median']:+.2f} "
                f"total={c['evaluation_total']:+.2f} "
                f"cap20={c['evaluation_cap20']:+.2f}"
            )

    lines.append("")
    lines.append("=" * 128)
    lines.append("VALIDATION SURVIVORS ON EVALUATION")
    lines.append("=" * 128)

    if not survivors:
        lines.append("NONE")
    else:
        for c in survivors:
            lines.append("")
            lines.append(c["candidate_name"])
            lines.append(
                "  EVALUATION "
                f"n={c['evaluation_n']} "
                f"wins={c['evaluation_wins']} "
                f"losses={c['evaluation_losses']} "
                f"wr={c['evaluation_wr']:.2f}% "
                f"avg={c['evaluation_avg']:+.2f} "
                f"median={c['evaluation_median']:+.2f} "
                f"total={c['evaluation_total']:+.2f} "
                f"cap20={c['evaluation_cap20']:+.2f}"
            )

    # Report prior 3-5/no13h benchmark separately, explicitly contaminated.
    lines.append("")
    lines.append("=" * 128)
    lines.append("PRIOR 3-5% + NO-13H BENCHMARK")
    lines.append("CONTAMINATED BENCHMARK — NOT ELIGIBLE AS CLEAN WALK-FORWARD DISCOVERY")
    lines.append("=" * 128)

    def prior_benchmark(r):
        x = to_float(r.get("h5_intensity"))
        return (
            r.get("h5_relation") == "MATCH"
            and x is not None
            and 3.0 <= x < 5.0
            and r.get("time_bucket") != "13:00-13:59"
        )

    for name, rows in [
        ("TRAIN", train_a),
        ("VALIDATION", val_a),
        ("EVALUATION", eval_a),
    ]:
        subset = [r for r in rows if prior_benchmark(r)]
        lines.append(fmt(name, summarize(subset)))

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
    print("FEATURES CSV   =", FEATURES_CSV)
    print("TRAIN CSV      =", TRAIN_CSV)
    print("VALIDATION CSV =", VALIDATION_CSV)
    print("EVALUATION CSV =", EVALUATION_CSV)
    print("CANDIDATES CSV =", CANDIDATES_CSV)
    print("SUMMARY        =", SUMMARY_TXT)
    if args.run_replay:
        print("REPLAY LOG     =", REPLAY_LOG)


if __name__ == "__main__":
    main()
