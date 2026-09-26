from pathlib import Path
from collections import defaultdict
import csv
import statistics

SRC = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "match-failure-analysis-v1/"
    "model-c-match-winner-loser-features-v1.csv"
)

OUT_DIR = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "match-robustness-analysis-v1"
)
OUT_DIR.mkdir(parents=True, exist_ok=True)

SUMMARY = OUT_DIR / "match-robustness-summary-v1.txt"
CSV_OUT = OUT_DIR / "match-robustness-candidates-v1.csv"


def f(v):
    try:
        if v in (None, ""):
            return None
        return float(v)
    except Exception:
        return None


def summarize(rows):
    pts = [f(r.get("points")) for r in rows]
    pts = [x for x in pts if x is not None]

    if not pts:
        return {
            "n": 0, "wins": 0, "losses": 0,
            "wr": None, "avg": None, "median": None,
            "total": None, "trim20_total": None,
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
        "trim20_total": sum(capped),
    }


def fmt(name, s):
    if not s["n"]:
        return f"{name:38s} n=0"
    return (
        f"{name:38s} "
        f"n={s['n']:3d} "
        f"win={s['wins']:3d} "
        f"loss={s['losses']:3d} "
        f"wr={s['wr']:6.2f}% "
        f"avg={s['avg']:+8.2f} "
        f"median={s['median']:+7.2f} "
        f"total={s['total']:+9.2f} "
        f"cap20={s['trim20_total']:+9.2f}"
    )


def intensity(r):
    return f(r.get("intensity_sum_abs_pct"))


def abs_pcr(r):
    v = f(r.get("abs_pcr_delta"))
    if v is not None:
        return v
    v = f(r.get("pcr_delta"))
    return abs(v) if v is not None else None


def current_pcr(r):
    return f(r.get("current_pcr"))


if not SRC.exists():
    raise SystemExit(f"MISSING INPUT: {SRC}")

with SRC.open(newline="", encoding="utf-8") as fobj:
    rows = list(csv.DictReader(fobj))

# Deliberately limited set of candidate slices.
# These are based on broad findings from the prior analysis,
# not an exhaustive combinatorial search.
CANDIDATES = {
    "BASELINE_ALL_MATCH": lambda r: True,

    "EXCLUDE_13H": lambda r:
        r.get("time_bucket") != "13:00-13:59",

    "INTENSITY_3_TO_5": lambda r:
        intensity(r) is not None
        and 3.0 <= intensity(r) < 5.0,

    "EXCLUDE_CE_BUILD_DOMINANT": lambda r:
        r.get("dominant_leg") != "CE_BUILD",

    "PCR_LEVEL_1_10_TO_1_29": lambda r:
        current_pcr(r) is not None
        and 1.10 <= current_pcr(r) < 1.30,

    "ABS_PCR_0_02_TO_0_04": lambda r:
        abs_pcr(r) is not None
        and 0.02 <= abs_pcr(r) < 0.04,

    "INTENSITY_3_TO_5_EX13": lambda r:
        intensity(r) is not None
        and 3.0 <= intensity(r) < 5.0
        and r.get("time_bucket") != "13:00-13:59",

    "INTENSITY_3_TO_5_NO_CE_BUILD": lambda r:
        intensity(r) is not None
        and 3.0 <= intensity(r) < 5.0
        and r.get("dominant_leg") != "CE_BUILD",
}


lines = []
csv_rows = []

lines.append("=" * 128)
lines.append("HILEGA MATCH ROBUSTNESS ANALYSIS")
lines.append("RESEARCH ONLY — NO PRODUCTION FILTER IS BEING FROZEN")
lines.append("=" * 128)

for name, pred in CANDIDATES.items():
    selected = [r for r in rows if pred(r)]
    s = summarize(selected)

    lines.append("")
    lines.append(fmt(name, s))

    # Largest winner/loss contribution
    pts = sorted(
        [(f(r.get("points")), r) for r in selected if f(r.get("points")) is not None],
        key=lambda x: x[0]
    )

    if pts:
        worst = pts[0]
        best = pts[-1]

        lines.append(
            f"  worst={worst[0]:+.2f} "
            f"{worst[1].get('session_date')} {worst[1].get('entry_time')}"
        )
        lines.append(
            f"  best ={best[0]:+.2f} "
            f"{best[1].get('session_date')} {best[1].get('entry_time')}"
        )

        # Remove single best winner to expose outlier dependence
        without_best = list(selected)
        without_best.remove(best[1])
        sb = summarize(without_best)
        lines.append(
            "  without single best winner: "
            f"n={sb['n']} wr={sb['wr']:.2f}% "
            f"avg={sb['avg']:+.2f} total={sb['total']:+.2f}"
        )

    # Leave-one-session-out
    sessions = sorted({r.get("session_date") for r in selected if r.get("session_date")})
    folds = []

    for d in sessions:
        fold = [r for r in selected if r.get("session_date") != d]
        fs = summarize(fold)
        if fs["n"]:
            folds.append((d, fs))

    if folds:
        min_total = min(x[1]["total"] for x in folds)
        max_total = max(x[1]["total"] for x in folds)
        min_wr = min(x[1]["wr"] for x in folds)
        max_wr = max(x[1]["wr"] for x in folds)
        positive_total_folds = sum(x[1]["total"] > 0 for x in folds)

        lines.append(
            "  LOSO: "
            f"folds={len(folds)} "
            f"positive_total={positive_total_folds}/{len(folds)} "
            f"total_range={min_total:+.2f}..{max_total:+.2f} "
            f"wr_range={min_wr:.2f}%..{max_wr:.2f}%"
        )

        for d, fs in folds:
            csv_rows.append({
                "candidate": name,
                "excluded_session": d,
                "n": fs["n"],
                "wins": fs["wins"],
                "losses": fs["losses"],
                "win_rate": fs["wr"],
                "avg_points": fs["avg"],
                "median_points": fs["median"],
                "total_points": fs["total"],
                "cap20_total": fs["trim20_total"],
            })

# Session concentration for promising-but-small slice
lines.append("")
lines.append("=" * 128)
lines.append("INTENSITY 3-5% SESSION DETAIL")
lines.append("=" * 128)

sel = [r for r in rows if CANDIDATES["INTENSITY_3_TO_5"](r)]
by_session = defaultdict(list)
for r in sel:
    by_session[r.get("session_date")].append(r)

for d in sorted(by_session):
    lines.append(fmt(d, summarize(by_session[d])))

# Time bucket detail for intensity 3-5
lines.append("")
lines.append("=" * 128)
lines.append("INTENSITY 3-5% BY TIME BUCKET")
lines.append("=" * 128)

by_time = defaultdict(list)
for r in sel:
    by_time[r.get("time_bucket")].append(r)

for k in [
    "09:15-09:59",
    "10:00-10:59",
    "11:00-11:59",
    "12:00-12:59",
    "13:00-13:59",
    "14:00-14:55",
]:
    if k in by_time:
        lines.append(fmt(k, summarize(by_time[k])))

# Dominant leg detail
lines.append("")
lines.append("=" * 128)
lines.append("INTENSITY 3-5% BY DOMINANT LEG")
lines.append("=" * 128)

by_leg = defaultdict(list)
for r in sel:
    by_leg[r.get("dominant_leg")].append(r)

for k in sorted(by_leg):
    lines.append(fmt(k, summarize(by_leg[k])))

SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")

if csv_rows:
    fields = list(csv_rows[0].keys())
    with CSV_OUT.open("w", newline="", encoding="utf-8") as fobj:
        w = csv.DictWriter(fobj, fieldnames=fields)
        w.writeheader()
        w.writerows(csv_rows)

print("\n".join(lines))
print()
print("=" * 128)
print("OUTPUT FILES")
print("=" * 128)
print("SUMMARY =", SUMMARY)
print("LOSO CSV =", CSV_OUT)
