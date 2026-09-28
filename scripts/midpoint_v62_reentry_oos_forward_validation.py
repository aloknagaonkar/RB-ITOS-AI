#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import statistics
from datetime import datetime
from pathlib import Path

FREEZE = Path("docs/V62_REENTRY_OOS_FREEZE.json")
DEFAULT_LEDGER = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-v62-forward-reentry-oos/reentry-oos-ledger-v62.csv"
)
DEFAULT_SUMMARY = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-v62-forward-reentry-oos/summary-v62.txt"
)
DEFAULT_REPORT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-v62-forward-reentry-oos/report-v62.json"
)

FIELDS = [
    "session_date",
    "family",
    "direction",
    "rescue_timestamp",
    "rescue_price",
    "reentry_timestamp",
    "reentry_price",
    "terminal_timestamp",
    "terminal_price",
    "r1_exit_timestamp",
    "r1_exit_price",
    "r2_exit_timestamp",
    "r2_exit_price",
    "notes",
]


def fnum(x):
    if x in ("", None):
        return None
    return float(x)


def dpoints(direction, a, b):
    if a is None or b is None:
        return None
    return b - a if direction == "BULLISH" else a - b


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def mdd(xs):
    eq = 0.0
    peak = 0.0
    dd = 0.0
    for x in xs:
        if x is None:
            continue
        eq += x
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return dd


def read_rows(path):
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def init_ledger(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        print(f"EXISTS: {path}")
        return
    with path.open("w", newline="") as fh:
        csv.DictWriter(fh, fieldnames=FIELDS).writeheader()
    print(f"CREATED: {path}")


def validate_freeze():
    spec = json.loads(FREEZE.read_text())
    ids = [x["id"] for x in spec["research_candidates"]]
    assert ids == ["R1", "R2"]
    assert spec["promotion_gate"]["minimum_comparable_reentry_events"] == 20
    print("PASS: V62 freeze spec is intact.")
    print("PASS: only R1 and R2 are registered research candidates.")
    print("PASS: minimum promotion gate = 20 comparable re-entry events.")


def summarize(ledger, summary_path, report_path):
    rows = read_rows(ledger)
    comparable = []
    for r in rows:
        direction = r["direction"]
        rescue = fnum(r["rescue_price"])
        reentry = fnum(r["reentry_price"])
        terminal = fnum(r["terminal_price"])
        r1exit = fnum(r["r1_exit_price"])
        r2exit = fnum(r["r2_exit_price"])

        if None in (rescue, reentry, terminal):
            continue

        first_leg = None
        # Entry price is intentionally not required in the forward ledger:
        # matched comparison begins at CAP20 rescue.  CAP20-only incremental
        # value after rescue = 0.  R1/R2 incremental value = second-leg result.
        current = dpoints(direction, reentry, terminal)
        r1 = dpoints(direction, reentry, r1exit) if r1exit is not None else None
        r2 = dpoints(direction, reentry, r2exit) if r2exit is not None else None

        comparable.append({
            "session_date": r["session_date"],
            "family": r["family"],
            "direction": direction,
            "current_second_leg": current,
            "r1_second_leg": r1,
            "r2_second_leg": r2,
        })

    def stats(key):
        vals = [x[key] for x in comparable if x[key] is not None]
        return {
            "n": len(vals),
            "sum": sum(vals) if vals else None,
            "mean": mean(vals),
            "median": median(vals),
            "positive": sum(v > 0 for v in vals),
            "positive_pct": round(100 * sum(v > 0 for v in vals) / len(vals), 2) if vals else None,
            "max_drawdown": mdd(vals) if vals else None,
        }

    report = {
        "model": "MIDPOINT_V62_FORWARD_REENTRY_OOS",
        "ledger_rows": len(rows),
        "matched_terminal_comparable": len(comparable),
        "CAP20_ONLY_INCREMENTAL_AFTER_RESCUE": {
            "n": len(comparable),
            "sum": 0.0 if comparable else None,
            "mean": 0.0 if comparable else None,
            "median": 0.0 if comparable else None,
        },
        "CURRENT_REENTRY": stats("current_second_leg"),
        "R1_REENTRY_PROTECT10_AFTER20": stats("r1_second_leg"),
        "R2_REENTRY_TRAIL20_AFTER20": stats("r2_second_leg"),
        "promotion_gate_minimum": 20,
        "promotion_gate_preferred": 30,
        "ready_for_minimum_gate": len(comparable) >= 20,
        "ready_for_preferred_gate": len(comparable) >= 30,
        "notes": [
            "This ledger is for genuinely new forward/OOS re-entry events only.",
            "Do not backfill the 9 V61 development cases into this ledger.",
            "CAP20-only is the zero-increment baseline after rescue.",
            "Unresolved/session-end-marked events are excluded from matched terminal comparison.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = [
        "MIDPOINT V62 — FORWARD RE-ENTRY OOS VALIDATION",
        "=" * 100,
        "R1/R2 frozen before forward OOS; no threshold tuning",
        "",
        f"ledger rows={len(rows)} matched terminal-comparable={len(comparable)}",
        f"minimum gate=20 preferred=30",
        "",
    ]
    for name in (
        "CURRENT_REENTRY",
        "R1_REENTRY_PROTECT10_AFTER20",
        "R2_REENTRY_TRAIL20_AFTER20",
    ):
        s = report[name]
        lines.append(
            f"{name}: n={s['n']} sum={s['sum']} mean={s['mean']} "
            f"median={s['median']} positive={s['positive']} "
            f"positive_pct={s['positive_pct']} maxDD={s['max_drawdown']}"
        )
    lines += [
        "",
        f"ready_minimum_gate={report['ready_for_minimum_gate']}",
        f"ready_preferred_gate={report['ready_for_preferred_gate']}",
        "",
        "IMPORTANT",
        "- Do not add any of the 9 V61 development cases to this forward ledger.",
        "- Do not tune R1 or R2 thresholds after this freeze.",
        "- Keep CAP20-only/no-reentry as the validated baseline until the OOS gate is met.",
        "",
        f"LEDGER={ledger}",
        f"REPORT={report_path}",
        f"SUMMARY={summary_path}",
    ]
    summary_path.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    p.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    p.add_argument("--init-ledger", action="store_true")
    p.add_argument("--validate-freeze", action="store_true")
    p.add_argument("--summarize", action="store_true")
    args = p.parse_args()

    if not any((args.init_ledger, args.validate_freeze, args.summarize)):
        args.validate_freeze = True
        args.init_ledger = True
        args.summarize = True

    if args.validate_freeze:
        validate_freeze()
    if args.init_ledger:
        init_ledger(args.ledger)
    if args.summarize:
        summarize(args.ledger, args.summary, args.report)


if __name__ == "__main__":
    main()
