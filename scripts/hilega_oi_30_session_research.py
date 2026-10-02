from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import csv
import json

DATES = [
    "2026-07-29","2026-07-30","2026-07-31",
    "2026-08-03","2026-08-04","2026-08-05",
    "2026-08-06","2026-08-07","2026-08-10",
    "2026-08-11","2026-08-12","2026-08-13",
    "2026-08-14","2026-08-17","2026-08-18",
    "2026-08-19","2026-08-20","2026-08-21",
    "2026-08-24","2026-08-25","2026-08-26",
    "2026-08-27","2026-08-28","2026-08-31",
    "2026-09-01","2026-09-02","2026-09-03",
    "2026-09-04","2026-09-07","2026-09-08",
]

STEP = 50

MODELS = {
    "MODEL_A_FIXED_5": {
        0: 5, 1: 5, 2: 5, 3: 5, 4: 5,
    },
    "MODEL_C_EXPIRY_AWARE": {
        0: 3, 1: 2, 2: 5, 3: 5, 4: 4,
    },
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

OUT = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "hilega-moving-atm-expiry-width-30-session-v1.csv"
)

OUT.parent.mkdir(parents=True, exist_ok=True)


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


def pct(delta, previous):
    if previous in (None, 0):
        return None
    return delta / previous * 100.0


def pcr(pe, ce):
    if ce in (None, 0):
        return None
    return pe / ce


def parse_ts(value):
    return datetime.fromisoformat(str(value))


def load_trades(session_date):
    path = TRADES_ROOT / session_date / "directional-trades.csv"
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


print("=" * 120)
print("DISCOVERING HISTORICAL PER-STRIKE OI SOURCES")
print("=" * 120)

oi_files = {}

for root in OI_ROOTS:
    if not root.exists():
        continue

    for path in root.glob("*.json"):
        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
            )
        except Exception:
            continue

        d = str(data.get("session_date", ""))
        if d not in DATES:
            continue

        rows = data.get("rows", [])

        usable = sum(
            1
            for r in rows
            if (
                r.get("timestamp") is not None
                and r.get("strike") is not None
                and r.get("ce_open_interest") is not None
                and r.get("pe_open_interest") is not None
            )
        )

        if usable == 0:
            continue

        old = oi_files.get(d)
        if old is None or usable > old["usable"]:
            oi_files[d] = {
                "path": path,
                "usable": usable,
                "expiry": data.get("expiry"),
            }

for d in DATES:
    info = oi_files.get(d)
    if info:
        print(
            d,
            "expiry=", info["expiry"],
            "rows=", info["usable"],
            "source=", info["path"],
        )
    else:
        print(d, "NO OI SOURCE")


def load_oi_session(session_date):
    info = oi_files.get(session_date)
    if info is None:
        return None

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
    if snapshot is None:
        return None

    values = []
    for strike in strikes:
        item = snapshot.get(float(strike))
        if item is None:
            return None
        values.append(item)

    return {
        "ce": sum(v["ce"] for v in values),
        "pe": sum(v["pe"] for v in values),
    }


output = []

print()
print("=" * 120)
print("BUILDING HILEGA + MOVING ATM OI JOIN")
print("=" * 120)

for session_date in DATES:
    trades = load_trades(session_date)
    oi = load_oi_session(session_date)

    print(
        session_date,
        "trades=", len(trades),
        "oi=", "AVAILABLE" if oi else "MISSING",
    )

    if oi is None or not oi["snapshots"]:
        continue

    example_ts = next(iter(oi["snapshots"]))
    tz = example_ts.tzinfo
    session_dt = datetime.fromisoformat(session_date)
    weekday = session_dt.weekday()

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

        for model_name, mapping in MODELS.items():
            wings = mapping[weekday]

            base_row = {
                "model": model_name,
                "session_date": session_date,
                "weekday": DAY_NAMES.get(weekday, str(weekday)),
                "expiry": oi["expiry"],
                "entry_time": trade["entry_time"],
                "direction": trade["direction"],
                "entry_event": trade["entry_event"],
                "exit_time": trade["exit_time"],
                "points": float(trade["points"]),
                "outcome": trade["outcome"],
                "wings": wings,
                "strike_count": wings * 2 + 1,
                "oi_source": oi["source"],
            }

            if current_snapshot is None:
                base_row["data_status"] = "CURRENT_SNAPSHOT_MISSING"
                output.append(base_row)
                continue

            if previous_snapshot is None:
                base_row["data_status"] = "PREVIOUS_SNAPSHOT_MISSING"
                output.append(base_row)
                continue

            if signal_atm is None:
                base_row["data_status"] = "SIGNAL_ATM_MISSING"
                output.append(base_row)
                continue

            strikes = [
                signal_atm + i * STEP
                for i in range(-wings, wings + 1)
            ]

            current = aggregate(current_snapshot, strikes)
            previous = aggregate(previous_snapshot, strikes)

            if current is None or previous is None:
                current_missing = [
                    s for s in strikes
                    if s not in current_snapshot
                ]

                previous_missing = [
                    s for s in strikes
                    if s not in previous_snapshot
                ]

                base_row.update({
                    "data_status": "INCOMPLETE_SAME_PHYSICAL_PANEL",
                    "signal_atm": signal_atm,
                    "strike_low": min(strikes),
                    "strike_high": max(strikes),
                    "current_missing_strikes": ",".join(
                        str(int(x)) for x in current_missing
                    ),
                    "previous_missing_strikes": ",".join(
                        str(int(x)) for x in previous_missing
                    ),
                })

                output.append(base_row)
                continue

            ce_delta = current["ce"] - previous["ce"]
            pe_delta = current["pe"] - previous["pe"]

            ce_pct = pct(ce_delta, previous["ce"])
            pe_pct = pct(pe_delta, previous["pe"])

            current_pcr = pcr(current["pe"], current["ce"])
            previous_pcr = pcr(previous["pe"], previous["ce"])

            state = classify(ce_delta, pe_delta)
            rel = relation(trade["direction"], state)

            base_row.update({
                "data_status": "AVAILABLE",
                "signal_atm": signal_atm,
                "strike_low": min(strikes),
                "strike_high": max(strikes),
                "signal_timestamp": signal_ts.isoformat(),
                "previous_timestamp": previous_ts.isoformat(),
                "current_ce_oi": current["ce"],
                "previous_ce_oi": previous["ce"],
                "current_pe_oi": current["pe"],
                "previous_pe_oi": previous["pe"],
                "ce_delta": ce_delta,
                "pe_delta": pe_delta,
                "ce_delta_pct": ce_pct,
                "pe_delta_pct": pe_pct,
                "current_pcr": current_pcr,
                "previous_pcr": previous_pcr,
                "pcr_delta": (
                    current_pcr - previous_pcr
                    if (
                        current_pcr is not None
                        and previous_pcr is not None
                    )
                    else None
                ),
                "intensity_sum_abs_pct": (
                    abs(ce_pct) + abs(pe_pct)
                    if (
                        ce_pct is not None
                        and pe_pct is not None
                    )
                    else None
                ),
                "oi_state": state,
                "relation": rel,
            })

            output.append(base_row)


fields = []
for row in output:
    for key in row:
        if key not in fields:
            fields.append(key)

with OUT.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(output)


def show(label, rows):
    if not rows:
        print(f"{label:32s} n=0")
        return

    pts = [float(r["points"]) for r in rows]
    wins = sum(x > 0 for x in pts)
    losses = sum(x < 0 for x in pts)

    print(
        f"{label:32s} "
        f"n={len(pts):3d} "
        f"win={wins:3d} "
        f"loss={losses:3d} "
        f"wr={wins/len(pts)*100:6.2f}% "
        f"avg={sum(pts)/len(pts):+8.2f} "
        f"total={sum(pts):+9.2f}"
    )


available = [
    r for r in output
    if r.get("data_status") == "AVAILABLE"
]

print()
print("=" * 120)
print("OUTPUT")
print("=" * 120)
print("CSV =", OUT)
print("rows =", len(output))

print()
print("=" * 120)
print("DATA COVERAGE BY MODEL")
print("=" * 120)

for model_name in MODELS:
    rows = [
        r for r in output
        if r["model"] == model_name
    ]

    status_counts = defaultdict(int)
    for r in rows:
        status_counts[r.get("data_status", "UNKNOWN")] += 1

    print()
    print(model_name)
    print("total trades =", len(rows))

    for status, count in sorted(status_counts.items()):
        print(f"  {status:40s} {count}")


print()
print("=" * 120)
print("30-SESSION MODEL COMPARISON")
print("=" * 120)

for model_name in MODELS:
    rows = [
        r for r in available
        if r["model"] == model_name
    ]

    print()
    print(model_name)
    print("-" * 120)

    show("ALL AVAILABLE", rows)

    for rel in ["MATCH", "OPPOSITE", "AMBIGUOUS"]:
        show(
            rel,
            [
                r for r in rows
                if r.get("relation") == rel
            ],
        )


print()
print("=" * 120)
print("MATCH BY DIRECTION")
print("=" * 120)

for model_name in MODELS:
    print()
    print(model_name)

    rows = [
        r for r in available
        if (
            r["model"] == model_name
            and r.get("relation") == "MATCH"
        )
    ]

    for direction in ["BULLISH", "BEARISH"]:
        show(
            direction,
            [
                r for r in rows
                if r["direction"] == direction
            ],
        )


print()
print("=" * 120)
print("MATCH BY WEEKDAY")
print("=" * 120)

for model_name in MODELS:
    print()
    print(model_name)

    for day in ["WED", "THU", "FRI", "MON", "TUE"]:
        show(
            day,
            [
                r for r in available
                if (
                    r["model"] == model_name
                    and r["weekday"] == day
                    and r.get("relation") == "MATCH"
                )
            ],
        )


print()
print("=" * 120)
print("RAW OI STATE PERFORMANCE")
print("=" * 120)

for model_name in MODELS:
    print()
    print(model_name)

    for state in [
        "BULLISH",
        "BEARISH",
        "TWO_SIDE_BUILD",
        "TWO_SIDE_UNWIND",
        "NEUTRAL",
    ]:
        show(
            state,
            [
                r for r in available
                if (
                    r["model"] == model_name
                    and r.get("oi_state") == state
                )
            ],
        )


print()
print("=" * 120)
print("MODEL C MATCH INTENSITY THRESHOLD SENSITIVITY")
print("RESEARCH ONLY — NO THRESHOLD IS BEING FROZEN")
print("=" * 120)

model_c_matches = [
    r for r in available
    if (
        r["model"] == "MODEL_C_EXPIRY_AWARE"
        and r.get("relation") == "MATCH"
        and r.get("intensity_sum_abs_pct") is not None
    )
]

for threshold in [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0]:
    selected = [
        r for r in model_c_matches
        if float(r["intensity_sum_abs_pct"]) < threshold
    ]

    show(
        f"SUMABS < {threshold:.1f}%",
        selected,
    )


print()
print("=" * 120)
print("MODEL C MATCH TRADE DETAIL")
print("=" * 120)

for r in sorted(
    model_c_matches,
    key=lambda x: (
        x["session_date"],
        x["entry_time"],
    ),
):
    print(
        r["session_date"],
        r["weekday"],
        r["entry_time"],
        f"{r['direction']:7s}",
        f"±{r['wings']}",
        f"ATM={float(r['signal_atm']):.0f}",
        f"CE%={float(r['ce_delta_pct']):+7.2f}",
        f"PE%={float(r['pe_delta_pct']):+7.2f}",
        f"SUMABS={float(r['intensity_sum_abs_pct']):6.2f}",
        f"PCRΔ={float(r['pcr_delta']):+.4f}",
        f"points={float(r['points']):+7.2f}",
    )
