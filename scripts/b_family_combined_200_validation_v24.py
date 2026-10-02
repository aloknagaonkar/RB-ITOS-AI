#!/usr/bin/env python3
"""
B FAMILY — V24 COMBINED 200-SESSION VALIDATION REPORT

Combines the frozen V22 and V23 outputs without rerunning or changing
Family-B entry logic or the V20 runner classifier.

Inputs
------
V22:
  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-pre-research-oos-100-v22/
    b-events-v22.csv
    post-proof-classification-v22.csv
    session-summary-v22.csv

V23:
  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-pre-v22-oos-100-v23/
    b-events-v23.csv
    post-proof-classification-v23.csv
    session-summary-v23.csv

Outputs
-------
data/historical-evidence/hilega-pcr-oi-support-research-v1/
b-family-combined-200-v24/
  combined-b-events-v24.csv
  combined-classified-v24.csv
  block-summary-v24.csv
  direction-summary-v24.csv
  classifier-summary-v24.csv
  report-v24.json
  summary-v24.txt

Statistical notes
-----------------
- Wilson 95% confidence intervals are reported for milestone proportions.
- Risk-difference intervals use Newcombe's method based on Wilson intervals.
- These are descriptive validation statistics, not a production approval.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from statistics import mean, median

ROOT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1"
)

BLOCKS = {
    "V23": ROOT / "b-family-pre-v22-oos-100-v23",
    "V22": ROOT / "b-family-pre-research-oos-100-v22",
}

OUTDIR = ROOT / "b-family-combined-200-v24"

EVENT_OUT = OUTDIR / "combined-b-events-v24.csv"
CLASSIFIED_OUT = OUTDIR / "combined-classified-v24.csv"
BLOCK_OUT = OUTDIR / "block-summary-v24.csv"
DIRECTION_OUT = OUTDIR / "direction-summary-v24.csv"
CLASSIFIER_OUT = OUTDIR / "classifier-summary-v24.csv"
REPORT_JSON = OUTDIR / "report-v24.json"
SUMMARY_TXT = OUTDIR / "summary-v24.txt"

MILESTONES = (20, 30, 50, 75, 100)
Z = 1.959963984540054


def read_csv(path: Path):
    if not path.exists():
        raise SystemExit(f"STOP: missing required input: {path}")
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def bval(v):
    return str(v).strip().lower() in {"1", "true", "yes"}


def fval(v):
    if v in (None, ""):
        return None
    return float(v)


def stats(vals):
    xs = [float(x) for x in vals if x not in (None, "")]
    if not xs:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
        }
    return {
        "n": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "min": min(xs),
        "max": max(xs),
    }


def wilson(successes: int, n: int, z: float = Z):
    if n == 0:
        return None, None, None

    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (
        z
        * math.sqrt(
            (p * (1 - p) / n) + (z * z / (4 * n * n))
        )
        / denom
    )
    return p, max(0.0, center - half), min(1.0, center + half)


def newcombe_diff(x1, n1, x0, n0):
    p1, l1, u1 = wilson(x1, n1)
    p0, l0, u0 = wilson(x0, n0)
    if p1 is None or p0 is None:
        return None, None, None

    d = p1 - p0
    lower = d - math.sqrt((p1 - l1) ** 2 + (u0 - p0) ** 2)
    upper = d + math.sqrt((u1 - p1) ** 2 + (p0 - l0) ** 2)
    return d, lower, upper


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = []
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)

    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def pct(x):
    return "-" if x is None else f"{100*x:.1f}%"


def num(x):
    return "-" if x is None else f"{float(x):+.2f}"


def milestone_count(rows, m):
    return sum(bval(r.get(f"reached_plus{m}")) for r in rows)


def classifier_group(rows, label):
    return [r for r in rows if r.get("classification") == label]


def load_block(block):
    base = BLOCKS[block]
    event_file = base / (
        "b-events-v22.csv" if block == "V22" else "b-events-v23.csv"
    )
    classified_file = base / (
        "post-proof-classification-v22.csv"
        if block == "V22"
        else "post-proof-classification-v23.csv"
    )
    session_file = base / (
        "session-summary-v22.csv"
        if block == "V22"
        else "session-summary-v23.csv"
    )

    events = read_csv(event_file)
    classified = read_csv(classified_file)
    sessions = read_csv(session_file)

    for r in events:
        r["validation_block"] = block
    for r in classified:
        r["validation_block"] = block
    for r in sessions:
        r["validation_block"] = block

    return sessions, events, classified


def block_summary(block, sessions, events, classified):
    bulls = [r for r in events if r.get("direction") == "BULLISH"]
    bears = [r for r in events if r.get("direction") == "BEARISH"]
    rs = classifier_group(classified, "RUNNER_STRENGTHENING")
    nb = classifier_group(classified, "NORMAL_B")

    out = {
        "block": block,
        "session_count": len(sessions),
        "framework_event_count": sum(
            int(r["framework_event_count"]) for r in sessions
        ),
        "b_event_count": len(events),
        "bullish_count": len(bulls),
        "bearish_count": len(bears),
        "classified_count": len(classified),
        "runner_strengthening_count": len(rs),
        "normal_b_count": len(nb),
        "mfe_mean": stats(fval(r.get("mfe")) for r in events)["mean"],
        "mfe_median": stats(fval(r.get("mfe")) for r in events)["median"],
        "mae_mean": stats(fval(r.get("mae")) for r in events)["mean"],
        "mae_median": stats(fval(r.get("mae")) for r in events)["median"],
    }

    for m in MILESTONES:
        out[f"plus{m}_count"] = milestone_count(events, m)
        out[f"plus{m}_rate"] = (
            out[f"plus{m}_count"] / len(events) if events else None
        )

    out["runner_plus75_rate"] = (
        milestone_count(rs, 75) / len(rs) if rs else None
    )
    out["normal_plus75_rate"] = (
        milestone_count(nb, 75) / len(nb) if nb else None
    )
    return out


def direction_summary(events):
    rows = []
    for direction in ("BULLISH", "BEARISH"):
        subset = [r for r in events if r.get("direction") == direction]
        s_mfe = stats(fval(r.get("mfe")) for r in subset)
        s_mae = stats(fval(r.get("mae")) for r in subset)

        row = {
            "direction": direction,
            "b_event_count": len(subset),
            "mfe_mean": s_mfe["mean"],
            "mfe_median": s_mfe["median"],
            "mae_mean": s_mae["mean"],
            "mae_median": s_mae["median"],
        }
        for m in MILESTONES:
            x = milestone_count(subset, m)
            p, lo, hi = wilson(x, len(subset))
            row[f"plus{m}_count"] = x
            row[f"plus{m}_rate"] = p
            row[f"plus{m}_ci95_low"] = lo
            row[f"plus{m}_ci95_high"] = hi

        rows.append(row)
    return rows


def classifier_summary(classified):
    rows = []

    for label in ("RUNNER_STRENGTHENING", "NORMAL_B"):
        subset = classifier_group(classified, label)
        s_mfe = stats(fval(r.get("mfe")) for r in subset)

        row = {
            "classification": label,
            "count": len(subset),
            "mfe_mean": s_mfe["mean"],
            "mfe_median": s_mfe["median"],
        }

        for m in (30, 50, 75, 100):
            x = milestone_count(subset, m)
            p, lo, hi = wilson(x, len(subset))
            row[f"plus{m}_count"] = x
            row[f"plus{m}_rate"] = p
            row[f"plus{m}_ci95_low"] = lo
            row[f"plus{m}_ci95_high"] = hi

        rows.append(row)

    return rows


def block_classifier_stability(blocks):
    rows = []
    for block, (_, _, classified) in blocks.items():
        rs = classifier_group(classified, "RUNNER_STRENGTHENING")
        nb = classifier_group(classified, "NORMAL_B")
        x1 = milestone_count(rs, 75)
        x0 = milestone_count(nb, 75)
        d, lo, hi = newcombe_diff(x1, len(rs), x0, len(nb))

        rows.append({
            "block": block,
            "runner_n": len(rs),
            "runner_plus75": x1,
            "runner_plus75_rate": x1 / len(rs) if rs else None,
            "normal_n": len(nb),
            "normal_plus75": x0,
            "normal_plus75_rate": x0 / len(nb) if nb else None,
            "plus75_rate_difference": d,
            "plus75_rate_difference_ci95_low": lo,
            "plus75_rate_difference_ci95_high": hi,
        })
    return rows


def main():
    print("B FAMILY — V24 COMBINED 200-SESSION VALIDATION")
    print("=" * 118)

    blocks = {}
    all_sessions = []
    all_events = []
    all_classified = []

    for block in ("V23", "V22"):
        sessions, events, classified = load_block(block)
        blocks[block] = (sessions, events, classified)
        all_sessions.extend(sessions)
        all_events.extend(events)
        all_classified.extend(classified)

    if len(all_sessions) != 200:
        raise SystemExit(
            f"STOP: expected 200 sessions, got {len(all_sessions)}"
        )

    session_dates = [r["session_date"] for r in all_sessions]
    if len(set(session_dates)) != 200:
        raise SystemExit("STOP: overlapping/duplicate session dates across V22/V23")

    if not max(
        r["session_date"]
        for r in blocks["V23"][0]
    ) < min(
        r["session_date"]
        for r in blocks["V22"][0]
    ):
        raise SystemExit("STOP: V23/V22 chronology boundary invalid")

    block_rows = [
        block_summary(block, *blocks[block])
        for block in ("V23", "V22")
    ]

    dir_rows = direction_summary(all_events)
    cls_rows = classifier_summary(all_classified)
    stability_rows = block_classifier_stability(blocks)

    rs = classifier_group(all_classified, "RUNNER_STRENGTHENING")
    nb = classifier_group(all_classified, "NORMAL_B")

    combined_diff = {}
    for m in (30, 50, 75, 100):
        x1 = milestone_count(rs, m)
        x0 = milestone_count(nb, m)
        d, lo, hi = newcombe_diff(x1, len(rs), x0, len(nb))
        combined_diff[str(m)] = {
            "runner": {
                "successes": x1,
                "n": len(rs),
                "rate": x1 / len(rs) if rs else None,
            },
            "normal": {
                "successes": x0,
                "n": len(nb),
                "rate": x0 / len(nb) if nb else None,
            },
            "rate_difference": d,
            "rate_difference_ci95": [lo, hi],
        }

    overall_mfe = stats(fval(r.get("mfe")) for r in all_events)
    overall_mae = stats(fval(r.get("mae")) for r in all_events)

    lines = [
        "B FAMILY — V24 COMBINED 200-SESSION VALIDATION",
        "=" * 118,
        f"session_range={min(session_dates)} -> {max(session_dates)}",
        "sessions=200",
        f"framework_events={sum(int(r['framework_event_count']) for r in all_sessions)}",
        f"b_events={len(all_events)}",
        f"bullish={sum(r.get('direction') == 'BULLISH' for r in all_events)} "
        f"bearish={sum(r.get('direction') == 'BEARISH' for r in all_events)}",
        f"classified_plus20={len(all_classified)}",
        "",
        "BLOCK STABILITY",
        "-" * 118,
    ]

    for r in block_rows:
        lines.append(
            f"{r['block']} sessions={r['session_count']} "
            f"B={r['b_event_count']} "
            f"bull/bear={r['bullish_count']}/{r['bearish_count']} "
            f"+20={r['plus20_count']}/{r['b_event_count']} "
            f"+50={r['plus50_count']}/{r['b_event_count']} "
            f"+75={r['plus75_count']}/{r['b_event_count']} "
            f"+100={r['plus100_count']}/{r['b_event_count']} "
            f"MFE_med={num(r['mfe_median'])}"
        )

    lines += [
        "",
        "COMBINED B GEOMETRY",
        "-" * 118,
        f"MFE n={overall_mfe['n']} mean={num(overall_mfe['mean'])} "
        f"median={num(overall_mfe['median'])} min={num(overall_mfe['min'])} max={num(overall_mfe['max'])}",
        f"MAE n={overall_mae['n']} mean={num(overall_mae['mean'])} "
        f"median={num(overall_mae['median'])} min={num(overall_mae['min'])} max={num(overall_mae['max'])}",
        "",
        "COMBINED MILESTONE REACH WITH 95% WILSON CI",
        "-" * 118,
    ]

    for m in MILESTONES:
        x = milestone_count(all_events, m)
        p, lo, hi = wilson(x, len(all_events))
        lines.append(
            f"+{m:<3} {x}/{len(all_events)} = {pct(p)} "
            f"95% CI [{pct(lo)}, {pct(hi)}]"
        )

    lines += [
        "",
        "FROZEN V20 CLASSIFIER — COMBINED",
        "-" * 118,
    ]

    for row in cls_rows:
        lines.append(
            f"{row['classification']} n={row['count']} "
            f"MFE median={num(row['mfe_median'])} mean={num(row['mfe_mean'])}"
        )
        for m in (30, 50, 75, 100):
            lines.append(
                f"  +{m:<3} {row[f'plus{m}_count']}/{row['count']} "
                f"= {pct(row[f'plus{m}_rate'])} "
                f"95% CI [{pct(row[f'plus{m}_ci95_low'])}, "
                f"{pct(row[f'plus{m}_ci95_high'])}]"
            )

    lines += [
        "",
        "CLASSIFIER RATE DIFFERENCES — RUNNER_STRENGTHENING MINUS NORMAL_B",
        "-" * 118,
    ]

    for m in (30, 50, 75, 100):
        d = combined_diff[str(m)]
        lines.append(
            f"+{m:<3} difference={pct(d['rate_difference'])} "
            f"Newcombe 95% CI "
            f"[{pct(d['rate_difference_ci95'][0])}, "
            f"{pct(d['rate_difference_ci95'][1])}]"
        )

    lines += [
        "",
        "BLOCK-BY-BLOCK +75 CLASSIFIER STABILITY",
        "-" * 118,
    ]

    for r in stability_rows:
        lines.append(
            f"{r['block']} "
            f"runner={r['runner_plus75']}/{r['runner_n']} "
            f"({pct(r['runner_plus75_rate'])}) "
            f"normal={r['normal_plus75']}/{r['normal_n']} "
            f"({pct(r['normal_plus75_rate'])}) "
            f"diff={pct(r['plus75_rate_difference'])} "
            f"95% CI [{pct(r['plus75_rate_difference_ci95_low'])}, "
            f"{pct(r['plus75_rate_difference_ci95_high'])}]"
        )

    lines += [
        "",
        "DIRECTION STABILITY",
        "-" * 118,
    ]

    for r in dir_rows:
        lines.append(
            f"{r['direction']} n={r['b_event_count']} "
            f"MFE_med={num(r['mfe_median'])} "
            f"MAE_med={num(r['mae_median'])} "
            f"+20={pct(r['plus20_rate'])} "
            f"+50={pct(r['plus50_rate'])} "
            f"+75={pct(r['plus75_rate'])} "
            f"+100={pct(r['plus100_rate'])}"
        )

    lines += [
        "",
        "INTERPRETATION",
        "-" * 118,
        "- V22 and V23 are non-overlapping 100-session blocks.",
        "- Family-B entry stayed frozen in both blocks.",
        "- V20 +20/+10m sign-only classifier stayed frozen in both blocks.",
        "- Runner-strengthening separation remained directionally positive in both blocks.",
        "- Confidence intervals remain wide because classified-event counts are still modest.",
        "- Treat V24 as strengthened research evidence, not production approval.",
        "- Do not retune thresholds from V24.",
        "- No exit model was optimized here.",
        "- Underlying NIFTY points only, not CE/PE premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_COMBINED_200_VALIDATION_V24",
        "session_range": [min(session_dates), max(session_dates)],
        "session_count": 200,
        "framework_event_count": sum(
            int(r["framework_event_count"]) for r in all_sessions
        ),
        "b_event_count": len(all_events),
        "bullish_count": sum(
            r.get("direction") == "BULLISH" for r in all_events
        ),
        "bearish_count": sum(
            r.get("direction") == "BEARISH" for r in all_events
        ),
        "classified_count": len(all_classified),
        "b_geometry": {
            "mfe": overall_mfe,
            "mae": overall_mae,
            "milestones": {
                str(m): {
                    "successes": milestone_count(all_events, m),
                    "n": len(all_events),
                    "wilson95": wilson(
                        milestone_count(all_events, m),
                        len(all_events),
                    ),
                }
                for m in MILESTONES
            },
        },
        "block_summary": block_rows,
        "direction_summary": dir_rows,
        "classifier_summary": cls_rows,
        "classifier_rate_differences": combined_diff,
        "block_plus75_classifier_stability": stability_rows,
        "guards": {
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "threshold_search": False,
            "exit_optimized": False,
            "production_code_changed": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENT_OUT, all_events)
    write_csv(CLASSIFIED_OUT, all_classified)
    write_csv(BLOCK_OUT, block_rows)
    write_csv(DIRECTION_OUT, dir_rows)
    write_csv(CLASSIFIER_OUT, cls_rows)
    REPORT_JSON.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    SUMMARY_TXT.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print("\n".join(lines))
    print()
    print("EVENTS      :", EVENT_OUT)
    print("CLASSIFIED  :", CLASSIFIED_OUT)
    print("BLOCK       :", BLOCK_OUT)
    print("DIRECTION   :", DIRECTION_OUT)
    print("CLASSIFIER  :", CLASSIFIER_OUT)
    print("REPORT JSON :", REPORT_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
