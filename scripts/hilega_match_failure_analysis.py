from pathlib import Path
from collections import defaultdict
import csv
import math
import statistics

SRC = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "hilega-moving-atm-expiry-width-30-session-v1.csv"
)

OUT_DIR = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "match-failure-analysis-v1"
)

OUT_DIR.mkdir(parents=True, exist_ok=True)

DETAIL_CSV = OUT_DIR / "model-c-match-winner-loser-features-v1.csv"
SUMMARY_TXT = OUT_DIR / "model-c-match-winner-loser-summary-v1.txt"


def f(v):
    try:
        if v in (None, ""):
            return None
        return float(v)
    except Exception:
        return None


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
        from datetime import date
        d1 = date.fromisoformat(session_date)
        d2 = date.fromisoformat(expiry)
        return (d2 - d1).days
    except Exception:
        return None


def sign_pattern(ce, pe):
    if ce is None or pe is None:
        return "UNKNOWN"
    if ce < 0 and pe > 0:
        return "BULLISH"
    if ce > 0 and pe < 0:
        return "BEARISH"
    if ce > 0 and pe > 0:
        return "BUILD"
    if ce < 0 and pe < 0:
        return "UNWIND"
    return "NEUTRAL"


def safe_ratio(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def add_derived(r):
    ce_pct = f(r.get("ce_delta_pct"))
    pe_pct = f(r.get("pe_delta_pct"))
    pcr_delta = f(r.get("pcr_delta"))
    current_pcr = f(r.get("current_pcr"))
    previous_pcr = f(r.get("previous_pcr"))
    points = f(r.get("points"))

    r = dict(r)
    r["route_family"] = route_family(r.get("entry_event"))
    r["time_bucket"] = time_bucket(r.get("entry_time", ""))
    r["days_to_expiry"] = days_to_expiry(
        r.get("session_date", ""),
        r.get("expiry", ""),
    )
    r["winner"] = "YES" if (points is not None and points > 0) else "NO"

    r["abs_ce_pct"] = abs(ce_pct) if ce_pct is not None else None
    r["abs_pe_pct"] = abs(pe_pct) if pe_pct is not None else None
    r["abs_pcr_delta"] = abs(pcr_delta) if pcr_delta is not None else None

    # Which side contributes more to the directional MATCH move?
    # For bullish MATCH: CE unwind magnitude vs PE buildup magnitude.
    # For bearish MATCH: CE buildup magnitude vs PE unwind magnitude.
    direction = r.get("direction")

    if direction == "BULLISH" and ce_pct is not None and pe_pct is not None:
        r["directional_primary_leg_pct"] = pe_pct
        r["directional_secondary_leg_pct"] = abs(ce_pct)
        r["directional_leg_ratio"] = safe_ratio(pe_pct, abs(ce_pct))
        r["dominant_leg"] = (
            "PE_BUILD"
            if pe_pct > abs(ce_pct)
            else "CE_UNWIND"
        )
    elif direction == "BEARISH" and ce_pct is not None and pe_pct is not None:
        r["directional_primary_leg_pct"] = ce_pct
        r["directional_secondary_leg_pct"] = abs(pe_pct)
        r["directional_leg_ratio"] = safe_ratio(ce_pct, abs(pe_pct))
        r["dominant_leg"] = (
            "CE_BUILD"
            if ce_pct > abs(pe_pct)
            else "PE_UNWIND"
        )
    else:
        r["directional_primary_leg_pct"] = None
        r["directional_secondary_leg_pct"] = None
        r["directional_leg_ratio"] = None
        r["dominant_leg"] = "UNKNOWN"

    if current_pcr is not None:
        if current_pcr < 0.7:
            r["pcr_level_bucket"] = "<0.70"
        elif current_pcr < 0.9:
            r["pcr_level_bucket"] = "0.70-0.89"
        elif current_pcr < 1.1:
            r["pcr_level_bucket"] = "0.90-1.09"
        elif current_pcr < 1.3:
            r["pcr_level_bucket"] = "1.10-1.29"
        else:
            r["pcr_level_bucket"] = ">=1.30"
    else:
        r["pcr_level_bucket"] = "UNKNOWN"

    intensity = f(r.get("intensity_sum_abs_pct"))
    if intensity is None:
        r["intensity_bucket"] = "UNKNOWN"
    elif intensity < 1:
        r["intensity_bucket"] = "<1%"
    elif intensity < 2:
        r["intensity_bucket"] = "1-<2%"
    elif intensity < 3:
        r["intensity_bucket"] = "2-<3%"
    elif intensity < 5:
        r["intensity_bucket"] = "3-<5%"
    elif intensity < 8:
        r["intensity_bucket"] = "5-<8%"
    else:
        r["intensity_bucket"] = ">=8%"

    if pcr_delta is None:
        r["pcr_delta_bucket"] = "UNKNOWN"
    else:
        ap = abs(pcr_delta)
        if ap < 0.005:
            r["pcr_delta_bucket"] = "<0.005"
        elif ap < 0.01:
            r["pcr_delta_bucket"] = "0.005-<0.01"
        elif ap < 0.02:
            r["pcr_delta_bucket"] = "0.01-<0.02"
        elif ap < 0.04:
            r["pcr_delta_bucket"] = "0.02-<0.04"
        else:
            r["pcr_delta_bucket"] = ">=0.04"

    return r


def summarize(rows):
    if not rows:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "wr": None,
            "avg": None,
            "total": None,
        }

    pts = [f(r.get("points")) for r in rows]
    pts = [x for x in pts if x is not None]

    wins = sum(x > 0 for x in pts)
    losses = sum(x < 0 for x in pts)

    return {
        "n": len(pts),
        "wins": wins,
        "losses": losses,
        "wr": wins / len(pts) * 100 if pts else None,
        "avg": sum(pts) / len(pts) if pts else None,
        "total": sum(pts) if pts else None,
    }


def fmt(label, s):
    if s["n"] == 0:
        return f"{label:36s} n=0"
    return (
        f"{label:36s} "
        f"n={s['n']:3d} "
        f"win={s['wins']:3d} "
        f"loss={s['losses']:3d} "
        f"wr={s['wr']:6.2f}% "
        f"avg={s['avg']:+8.2f} "
        f"total={s['total']:+9.2f}"
    )


def group_report(lines, title, rows, field, order=None):
    lines.append("")
    lines.append("=" * 120)
    lines.append(title)
    lines.append("=" * 120)

    groups = defaultdict(list)
    for r in rows:
        groups[str(r.get(field, "UNKNOWN"))].append(r)

    keys = order or sorted(groups.keys())

    for k in keys:
        if k in groups:
            lines.append(fmt(k, summarize(groups[k])))


if not SRC.exists():
    raise SystemExit(f"MISSING INPUT: {SRC}")

with SRC.open(newline="", encoding="utf-8") as fobj:
    raw = list(csv.DictReader(fobj))

matches = [
    add_derived(r)
    for r in raw
    if (
        r.get("model") == "MODEL_C_EXPIRY_AWARE"
        and r.get("data_status") == "AVAILABLE"
        and r.get("relation") == "MATCH"
    )
]

if not matches:
    raise SystemExit("No MODEL_C_EXPIRY_AWARE AVAILABLE MATCH rows found.")

fields = []
for row in matches:
    for k in row.keys():
        if k not in fields:
            fields.append(k)

with DETAIL_CSV.open("w", newline="", encoding="utf-8") as fobj:
    w = csv.DictWriter(fobj, fieldnames=fields)
    w.writeheader()
    w.writerows(matches)

lines = []

lines.append("=" * 120)
lines.append("HILEGA MODEL C MATCH — WINNER VS LOSER FEATURE ANALYSIS")
lines.append("=" * 120)
lines.append("")
lines.append(fmt("ALL MATCH", summarize(matches)))

winners = [r for r in matches if r["winner"] == "YES"]
losers = [r for r in matches if r["winner"] == "NO"]

lines.append(fmt("WINNERS", summarize(winners)))
lines.append(fmt("LOSERS", summarize(losers)))

group_report(
    lines,
    "BY DIRECTION",
    matches,
    "direction",
    ["BULLISH", "BEARISH"],
)

group_report(
    lines,
    "BY ENTRY ROUTE",
    matches,
    "route_family",
    ["OPENING", "ROUTE_A", "ROUTE_B", "OTHER"],
)

group_report(
    lines,
    "BY TIME OF DAY",
    matches,
    "time_bucket",
    [
        "09:15-09:59",
        "10:00-10:59",
        "11:00-11:59",
        "12:00-12:59",
        "13:00-13:59",
        "14:00-14:55",
    ],
)

group_report(
    lines,
    "BY WEEKDAY",
    matches,
    "weekday",
    ["WED", "THU", "FRI", "MON", "TUE"],
)

group_report(
    lines,
    "BY DAYS TO EXPIRY",
    matches,
    "days_to_expiry",
)

group_report(
    lines,
    "BY INTENSITY",
    matches,
    "intensity_bucket",
    ["<1%", "1-<2%", "2-<3%", "3-<5%", "5-<8%", ">=8%"],
)

group_report(
    lines,
    "BY ABS PCR CHANGE",
    matches,
    "pcr_delta_bucket",
    [
        "<0.005",
        "0.005-<0.01",
        "0.01-<0.02",
        "0.02-<0.04",
        ">=0.04",
    ],
)

group_report(
    lines,
    "BY PCR LEVEL",
    matches,
    "pcr_level_bucket",
    [
        "<0.70",
        "0.70-0.89",
        "0.90-1.09",
        "1.10-1.29",
        ">=1.30",
    ],
)

group_report(
    lines,
    "BY DOMINANT MATCH LEG",
    matches,
    "dominant_leg",
)

# ------------------------------------------------------------
# Numeric winner/loss comparison
# ------------------------------------------------------------

lines.append("")
lines.append("=" * 120)
lines.append("NUMERIC WINNER VS LOSER COMPARISON")
lines.append("=" * 120)

numeric_fields = [
    "ce_delta_pct",
    "pe_delta_pct",
    "intensity_sum_abs_pct",
    "previous_pcr",
    "current_pcr",
    "pcr_delta",
    "abs_pcr_delta",
    "directional_primary_leg_pct",
    "directional_secondary_leg_pct",
    "directional_leg_ratio",
]

for field in numeric_fields:
    lines.append("")
    lines.append(field)

    for name, subset in [
        ("WINNER", winners),
        ("LOSER", losers),
    ]:
        vals = [f(r.get(field)) for r in subset]
        vals = [x for x in vals if x is not None and math.isfinite(x)]

        if not vals:
            lines.append(f"  {name:8s} n=0")
            continue

        lines.append(
            f"  {name:8s} "
            f"n={len(vals):3d} "
            f"mean={statistics.mean(vals):+.4f} "
            f"median={statistics.median(vals):+.4f} "
            f"min={min(vals):+.4f} "
            f"max={max(vals):+.4f}"
        )

# ------------------------------------------------------------
# Simple two-feature slices, descriptive only
# ------------------------------------------------------------

lines.append("")
lines.append("=" * 120)
lines.append("DESCRIPTIVE TWO-FEATURE SLICES")
lines.append("RESEARCH ONLY — DO NOT TREAT AS A TRADING RULE")
lines.append("=" * 120)

slices = [
    (
        "ROUTE_B + intensity < 2%",
        lambda r:
            r["route_family"] == "ROUTE_B"
            and f(r.get("intensity_sum_abs_pct")) is not None
            and f(r.get("intensity_sum_abs_pct")) < 2,
    ),
    (
        "ROUTE_B + intensity 2-5%",
        lambda r:
            r["route_family"] == "ROUTE_B"
            and f(r.get("intensity_sum_abs_pct")) is not None
            and 2 <= f(r.get("intensity_sum_abs_pct")) < 5,
    ),
    (
        "ABS PCR delta < 0.01",
        lambda r:
            f(r.get("abs_pcr_delta")) is not None
            and f(r.get("abs_pcr_delta")) < 0.01,
    ),
    (
        "ABS PCR delta 0.01-0.04",
        lambda r:
            f(r.get("abs_pcr_delta")) is not None
            and 0.01 <= f(r.get("abs_pcr_delta")) < 0.04,
    ),
    (
        "ABS PCR delta >= 0.04",
        lambda r:
            f(r.get("abs_pcr_delta")) is not None
            and f(r.get("abs_pcr_delta")) >= 0.04,
    ),
]

for label, pred in slices:
    subset = [r for r in matches if pred(r)]
    lines.append(fmt(label, summarize(subset)))

# ------------------------------------------------------------
# Session concentration
# ------------------------------------------------------------

group_report(
    lines,
    "BY SESSION",
    matches,
    "session_date",
)

SUMMARY_TXT.write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

print("\n".join(lines))
print()
print("=" * 120)
print("OUTPUT FILES")
print("=" * 120)
print("DETAIL CSV =", DETAIL_CSV)
print("SUMMARY TXT =", SUMMARY_TXT)
