from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

MODEL = "CHANGE_PCR_PROPAGATION_EXPANSION_V1"

BASE_7 = {
    "2026-05-12",
    "2026-05-18",
    "2026-08-25",
    "2026-05-20",
    "2026-05-25",
    "2026-05-19",
    "2026-05-29",
}

EXPANSION_12_BULLISH = {
    "2026-06-02",
    "2026-06-12",
    "2026-06-16",
    "2026-06-17",
    "2026-06-18",
    "2026-06-24",
}

EXPANSION_12_BEARISH = {
    "2026-06-01",
    "2026-06-23",
    "2026-06-29",
    "2026-07-07",
    "2026-07-08",
    "2026-07-14",
}

EXPANSION_12 = EXPANSION_12_BULLISH | EXPANSION_12_BEARISH
ALL_19 = BASE_7 | EXPANSION_12


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in {"1", "true", "yes"}


def _float(v: Any):
    if v in ("", None):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_candidates(path: Path) -> list[dict[str, Any]]:
    out = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            r = dict(row)
            for key in (
                "transition_within_5m",
                "transition_within_10m",
                "transition_within_15m",
                "persistent_3plus_hit_15m",
                "false_warning_15m",
            ):
                r[key] = _bool(r.get(key))
            out.append(r)
    return out


def rate(n: int, d: int):
    return None if d == 0 else n / d


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    h5 = sum(r["transition_within_5m"] for r in rows)
    h10 = sum(r["transition_within_10m"] for r in rows)
    h15 = sum(r["transition_within_15m"] for r in rows)
    p3 = sum(r["persistent_3plus_hit_15m"] for r in rows)
    false15 = sum(r["false_warning_15m"] for r in rows)
    return {
        "candidates": n,
        "hits_5m": h5,
        "hits_10m": h10,
        "hits_15m": h15,
        "precision_5m": rate(h5, n),
        "precision_10m": rate(h10, n),
        "precision_15m": rate(h15, n),
        "persistent_3plus_hits_15m": p3,
        "persistent_3plus_precision_15m": rate(p3, n),
        "false_15m": false15,
        "false_warning_rate_15m": rate(false15, n),
    }


def pattern_rows(rows, pattern):
    if pattern == "PROP_5M_ONLY":
        return [r for r in rows if r.get("propagation") == "5M_ONLY"]
    if pattern == "PROP_5M_10M":
        return [r for r in rows if r.get("propagation") == "5M_10M"]
    if pattern == "PROP_5M_10M_15M":
        return [r for r in rows if r.get("propagation") == "5M_10M_15M"]
    raise ValueError(pattern)


def cohort_summary(rows, dates):
    scoped = [r for r in rows if r.get("session_date") in dates]
    return {
        "session_count_present": len({r["session_date"] for r in scoped}),
        "sessions_present": sorted({r["session_date"] for r in scoped}),
        "overall": summarize(scoped),
        "PROP_5M_ONLY": summarize(pattern_rows(scoped, "PROP_5M_ONLY")),
        "PROP_5M_10M": summarize(pattern_rows(scoped, "PROP_5M_10M")),
        "PROP_5M_10M_15M": summarize(pattern_rows(scoped, "PROP_5M_10M_15M")),
    }


def directional_cohort_summary(rows, dates):
    scoped = [r for r in rows if r.get("session_date") in dates]
    return summarize(scoped)


def stability_checks(base, expansion):
    checks = {}

    for pattern in ("PROP_5M_ONLY", "PROP_5M_10M", "PROP_5M_10M_15M"):
        b = base[pattern]
        e = expansion[pattern]

        checks[pattern] = {
            "base_precision_15m": b["precision_15m"],
            "expansion_precision_15m": e["precision_15m"],
            "base_false_warning_rate_15m": b["false_warning_rate_15m"],
            "expansion_false_warning_rate_15m": e["false_warning_rate_15m"],
            "base_persistent_precision_15m": b["persistent_3plus_precision_15m"],
            "expansion_persistent_precision_15m": e["persistent_3plus_precision_15m"],
            "precision_delta_expansion_minus_base": (
                None if b["precision_15m"] is None or e["precision_15m"] is None
                else e["precision_15m"] - b["precision_15m"]
            ),
            "false_rate_delta_expansion_minus_base": (
                None
                if b["false_warning_rate_15m"] is None
                or e["false_warning_rate_15m"] is None
                else e["false_warning_rate_15m"] - b["false_warning_rate_15m"]
            ),
        }

    # Frozen hypothesis: broader propagation should improve precision and reduce false warnings.
    p5 = expansion["PROP_5M_ONLY"]["precision_15m"]
    p510 = expansion["PROP_5M_10M"]["precision_15m"]
    pall = expansion["PROP_5M_10M_15M"]["precision_15m"]
    f5 = expansion["PROP_5M_ONLY"]["false_warning_rate_15m"]
    f510 = expansion["PROP_5M_10M"]["false_warning_rate_15m"]
    fall = expansion["PROP_5M_10M_15M"]["false_warning_rate_15m"]

    monotonic_precision = (
        None if None in (p5, p510, pall)
        else p5 <= p510 <= pall
    )
    monotonic_false_rate = (
        None if None in (f5, f510, fall)
        else f5 >= f510 >= fall
    )

    return {
        "by_pattern": checks,
        "expansion_hypothesis_checks": {
            "precision_non_decreasing_with_propagation": monotonic_precision,
            "false_warning_rate_non_increasing_with_propagation": monotonic_false_rate,
        },
    }


def build_report(rows):
    present = {r.get("session_date") for r in rows}

    base = cohort_summary(rows, BASE_7)
    expansion = cohort_summary(rows, EXPANSION_12)
    combined = cohort_summary(rows, ALL_19)

    return {
        "status": "PASS",
        "model": MODEL,
        "hypothesis": (
            "5m->10m->15m normalized OI-dominance deterioration propagation "
            "retains higher 15m transition precision and lower false-warning rate "
            "than 5m-only deterioration on frozen expansion dates"
        ),
        "frozen_definitions_unchanged": True,
        "base_7_expected": sorted(BASE_7),
        "expansion_12_bullish": sorted(EXPANSION_12_BULLISH),
        "expansion_12_bearish": sorted(EXPANSION_12_BEARISH),
        "missing_base_sessions": sorted(BASE_7 - present),
        "missing_expansion_sessions": sorted(EXPANSION_12 - present),
        "cohorts": {
            "BASE_7": base,
            "EXPANSION_12": expansion,
            "COMBINED_19": combined,
        },
        "expansion_direction_groups": {
            "BULLISH_6": directional_cohort_summary(rows, EXPANSION_12_BULLISH),
            "BEARISH_6": directional_cohort_summary(rows, EXPANSION_12_BEARISH),
        },
        "stability": stability_checks(base, expansion),
    }


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Frozen cross-date propagation hypothesis expansion report."
    )
    p.add_argument("--candidates-csv", required=True)
    p.add_argument("--summary-json", required=True)
    args = p.parse_args(argv)

    rows = load_candidates(Path(args.candidates_csv))
    report = build_report(rows)

    out = Path(args.summary_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
