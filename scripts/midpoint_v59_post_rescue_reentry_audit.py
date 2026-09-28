#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import statistics
from pathlib import Path

V55 = Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V57 = Path("scripts/midpoint_v57_full_historical_be_lifecycle_replay.py")

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-v59-post-rescue-reentry-audit"
)
CASE_CSV = OUTDIR / "reentry-cases-v59.csv"
SUMMARY_TXT = OUTDIR / "summary-v59.txt"
REPORT_JSON = OUTDIR / "report-v59.json"

REENTRY_EVENTS = {
    "POST_CAP20_REENTRY_TRIGGERED",
    "POST_RESCUE_REENTRY_TRIGGERED",
    "REENTRY_COUNT_1",
}
CAP20_EVENTS = {"CAP20_RESCUE_TRIGGERED", "CAP20_SHADOW_EXIT"}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def dt(ts: str):
    from datetime import datetime
    return datetime.fromisoformat(ts)


def dpoints(direction: str, a: float, b: float) -> float:
    return b - a if direction == "BULLISH" else a - b


def fav(direction: str, entry: float, row: dict) -> float:
    px = float(row["high"] if direction == "BULLISH" else row["low"])
    return dpoints(direction, entry, px)


def bars(u: dict, start: str, end: str | None = None):
    s = dt(start)
    e = dt(end) if end else None
    return [
        (ts, u[ts])
        for ts in sorted(u, key=dt)
        if dt(ts) >= s and (e is None or dt(ts) <= e)
    ]


def first(seg, event_types):
    types = {event_types} if isinstance(event_types, str) else set(event_types)
    return next((r for r in seg if r.get("event_type") in types), None)


def event_price(r):
    if r is None or r.get("underlying_price") is None:
        return None
    return float(r["underlying_price"])


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def main():
    v55 = load_module(V55, "v55_v59")
    v52 = load_module(V52, "v52_v59")
    canon = load_module(CANON, "canon_v59")
    v57 = load_module(V57, "v57_v59")

    cases = []

    for block in v52.BLOCKS:
        u, fut, framework = v55.load_block(block, v52, canon)
        for day in sorted(set(u).intersection(fut)):
            audit, open_active, active_family = v57.replay_session(day, u[day], fut[day])

            entries = [
                (i, r) for i, r in enumerate(audit)
                if r.get("event_type") in ("B_ENTRY", "E_ENTRY")
            ]

            for seq, (idx, en) in enumerate(entries, 1):
                next_idx = entries[seq][0] if seq < len(entries) else len(audit)
                seg = audit[idx:next_idx]

                rescue = first(seg, CAP20_EVENTS)
                if rescue is None:
                    continue

                richer = first(seg, {
                    "POST_CAP20_REENTRY_TRIGGERED",
                    "POST_RESCUE_REENTRY_TRIGGERED",
                })
                reentry = richer or first(seg, REENTRY_EVENTS)

                if reentry is None:
                    continue

                terminal = first(seg, "STRUCTURAL_TERMINAL")
                direction = en["direction"]
                family = en["family"]
                entry_px = float(en["underlying_price"])
                rescue_px = event_price(rescue)
                reentry_px = event_price(reentry)
                terminal_px = event_price(terminal)

                first_leg = (
                    dpoints(direction, entry_px, rescue_px)
                    if rescue_px is not None else None
                )
                second_leg = (
                    dpoints(direction, reentry_px, terminal_px)
                    if reentry_px is not None and terminal_px is not None else None
                )
                full = (
                    first_leg + second_leg
                    if first_leg is not None and second_leg is not None else None
                )
                baseline = (
                    dpoints(direction, entry_px, terminal_px)
                    if terminal_px is not None else None
                )
                rescue_improvement = (
                    first_leg - baseline
                    if first_leg is not None and baseline is not None else None
                )
                reentry_improvement = second_leg

                end_ts = terminal["event_timestamp"] if terminal else max(u[day], key=dt)
                pre_rescue = bars(u[day], en["event_timestamp"], rescue["event_timestamp"])
                post_rescue = bars(u[day], rescue["event_timestamp"], end_ts)
                post_reentry = bars(u[day], reentry["event_timestamp"], end_ts)

                pre_rescue_mfe = max(
                    [fav(direction, entry_px, r) for _, r in pre_rescue],
                    default=None,
                )
                post_rescue_peak_from_original = max(
                    [fav(direction, entry_px, r) for _, r in post_rescue],
                    default=None,
                )
                reentry_mfe = (
                    max([fav(direction, reentry_px, r) for _, r in post_reentry], default=None)
                    if reentry_px is not None else None
                )

                rescue_ev = rescue.get("evidence") or {}
                reentry_ev = reentry.get("evidence") or {}
                terminal_ev = terminal.get("evidence") if terminal else {}

                cases.append({
                    "block": block["name"],
                    "session_date": day,
                    "trade_seq": seq,
                    "family": family,
                    "direction": direction,
                    "entry_timestamp": en["event_timestamp"],
                    "entry_price": entry_px,
                    "rescue_timestamp": rescue["event_timestamp"],
                    "rescue_price": rescue_px,
                    "reentry_timestamp": reentry["event_timestamp"],
                    "reentry_price": reentry_px,
                    "terminal_timestamp": terminal["event_timestamp"] if terminal else "",
                    "terminal_price": terminal_px,
                    "comparable": terminal is not None and reentry_px is not None,
                    "first_leg_points": first_leg,
                    "second_leg_points": second_leg,
                    "full_points": full,
                    "baseline_structural_points": baseline,
                    "rescue_improvement_points": rescue_improvement,
                    "reentry_improvement_points": reentry_improvement,
                    "pre_rescue_mfe": pre_rescue_mfe,
                    "post_rescue_peak_from_original_entry": post_rescue_peak_from_original,
                    "later_new_mfe_after_rescue": (
                        pre_rescue_mfe is not None
                        and post_rescue_peak_from_original is not None
                        and post_rescue_peak_from_original > pre_rescue_mfe
                    ),
                    "reentry_mfe_points": reentry_mfe,
                    "reentry_profitable_at_terminal": (
                        second_leg is not None and second_leg > 0
                    ),
                    "rescue_event_type": rescue["event_type"],
                    "reentry_event_type": reentry["event_type"],
                    "rescue_evidence_json": json.dumps(rescue_ev, sort_keys=True),
                    "reentry_evidence_json": json.dumps(reentry_ev, sort_keys=True),
                    "terminal_evidence_json": json.dumps(terminal_ev or {}, sort_keys=True),
                })

    OUTDIR.mkdir(parents=True, exist_ok=True)

    fields = []
    for row in cases:
        for k in row:
            if k not in fields:
                fields.append(k)
    with CASE_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(cases)

    comparable = [c for c in cases if c["comparable"]]
    b = [c for c in cases if c["family"] == "B"]
    e = [c for c in cases if c["family"] == "E"]

    def summarize(xs):
        comp = [c for c in xs if c["comparable"]]
        return {
            "cases": len(xs),
            "comparable": len(comp),
            "later_new_mfe_after_rescue": sum(c["later_new_mfe_after_rescue"] for c in xs),
            "positive_second_leg": sum(c["reentry_profitable_at_terminal"] for c in comp),
            "negative_second_leg": sum(
                c["second_leg_points"] is not None and c["second_leg_points"] < 0
                for c in comp
            ),
            "second_leg_sum": sum(
                c["second_leg_points"] for c in comp if c["second_leg_points"] is not None
            ) if comp else None,
            "second_leg_mean": mean(c["second_leg_points"] for c in comp),
            "second_leg_median": median(c["second_leg_points"] for c in comp),
            "reentry_mfe_mean": mean(c["reentry_mfe_points"] for c in xs),
            "reentry_mfe_median": median(c["reentry_mfe_points"] for c in xs),
        }

    report = {
        "model": "MIDPOINT_V59_POST_RESCUE_REENTRY_AUDIT",
        "scope": "FOCUSED_AUDIT_OF_ALL_POST_CAP20_REENTRY_CASES_FROM_480_SESSION_REPLAY",
        "B": summarize(b),
        "E": summarize(e),
        "combined": summarize(cases),
        "case_count": len(cases),
        "notes": [
            "No strategy rules changed.",
            "Uses V57 parity-proven replay.",
            "This phase audits existing re-entry cases; it does not optimize a new rule.",
            "Primary question: why later-new-MFE exists while realized second-leg outcomes are weak.",
        ],
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = []
    lines.append("MIDPOINT V59 — POST-RESCUE RE-ENTRY AUDIT")
    lines.append("=" * 100)
    lines.append("480-session replay; existing frozen re-entry rule only; no tuning")
    lines.append("")
    for label, xs in [("B", b), ("E", e), ("B+E", cases)]:
        s = summarize(xs)
        lines.append(label)
        lines.append("-" * 100)
        lines.append(
            f"cases={s['cases']} comparable={s['comparable']} "
            f"later_new_mfe_after_rescue={s['later_new_mfe_after_rescue']}"
        )
        lines.append(
            f"positive_second_leg={s['positive_second_leg']} "
            f"negative_second_leg={s['negative_second_leg']}"
        )
        lines.append(
            f"second_leg sum/mean/median="
            f"{s['second_leg_sum']}/{s['second_leg_mean']}/{s['second_leg_median']}"
        )
        lines.append(
            f"reentry MFE mean/median="
            f"{s['reentry_mfe_mean']}/{s['reentry_mfe_median']}"
        )
        lines.append("")

    lines.append("CASES")
    lines.append("-" * 100)
    for c in cases:
        lines.append(
            f"{c['session_date']} {c['family']} {c['direction']} "
            f"rescue={c['rescue_timestamp']} reentry={c['reentry_timestamp']} "
            f"terminal={c['terminal_timestamp'] or 'OPEN'} "
            f"leg2={c['second_leg_points']} "
            f"reentry_MFE={c['reentry_mfe_points']} "
            f"later_new_MFE={c['later_new_mfe_after_rescue']}"
        )

    lines.append("")
    lines.append(f"CASE CSV   = {CASE_CSV}")
    lines.append(f"REPORT JSON= {REPORT_JSON}")
    lines.append(f"SUMMARY    = {SUMMARY_TXT}")

    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
