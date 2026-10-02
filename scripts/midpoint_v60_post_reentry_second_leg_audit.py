#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import statistics
from datetime import datetime
from pathlib import Path

V55 = Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V57 = Path("scripts/midpoint_v57_full_historical_be_lifecycle_replay.py")

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-v60-post-reentry-second-leg-audit"
)

CASE_CSV = OUTDIR / "second-leg-cases-v60.csv"
SUMMARY_TXT = OUTDIR / "summary-v60.txt"
REPORT_JSON = OUTDIR / "report-v60.json"

REENTRY_EVENTS = {
    "POST_CAP20_REENTRY_TRIGGERED",
    "POST_RESCUE_REENTRY_TRIGGERED",
    "REENTRY_COUNT_1",
}
CAP20_EVENTS = {"CAP20_RESCUE_TRIGGERED", "CAP20_SHADOW_EXIT"}

THRESHOLDS = [10, 20, 30, 50, 75, 100]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def dpoints(direction: str, a: float, b: float) -> float:
    return b - a if direction == "BULLISH" else a - b


def favorable_from_reentry(direction: str, entry: float, row: dict) -> float:
    px = float(row["high"] if direction == "BULLISH" else row["low"])
    return dpoints(direction, entry, px)


def adverse_from_reentry(direction: str, entry: float, row: dict) -> float:
    px = float(row["low"] if direction == "BULLISH" else row["high"])
    return dpoints(direction, entry, px)


def close_move(direction: str, entry: float, row: dict) -> float:
    return dpoints(direction, entry, float(row["close"]))


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


def first_threshold_hit(direction, entry_px, bs, threshold):
    for ts, row in bs:
        if favorable_from_reentry(direction, entry_px, row) >= threshold:
            return ts
    return None


def first_close_at_or_below(direction, entry_px, bs, level, strictly=False):
    for ts, row in bs:
        move = close_move(direction, entry_px, row)
        if strictly:
            if move < level:
                return ts, move
        else:
            if move <= level:
                return ts, move
    return None, None


def first_close_negative(direction, entry_px, bs):
    return first_close_at_or_below(direction, entry_px, bs, 0.0, strictly=True)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def main():
    v55 = load_module(V55, "v55_v60")
    v52 = load_module(V52, "v52_v60")
    canon = load_module(CANON, "canon_v60")
    v57 = load_module(V57, "v57_v60")

    cases = []

    for block in v52.BLOCKS:
        u, fut, framework = v55.load_block(block, v52, canon)

        for day in sorted(set(u).intersection(fut)):
            audit, open_active, active_family = v57.replay_session(day, u[day], fut[day])

            entries = [
                (i, r)
                for i, r in enumerate(audit)
                if r.get("event_type") in ("B_ENTRY", "E_ENTRY")
            ]

            for seq, (idx, en) in enumerate(entries, 1):
                next_idx = entries[seq][0] if seq < len(entries) else len(audit)
                seg = audit[idx:next_idx]

                rescue = first(seg, CAP20_EVENTS)
                if rescue is None:
                    continue

                richer = first(
                    seg,
                    {
                        "POST_CAP20_REENTRY_TRIGGERED",
                        "POST_RESCUE_REENTRY_TRIGGERED",
                    },
                )
                reentry = richer or first(seg, REENTRY_EVENTS)
                if reentry is None:
                    continue

                terminal = first(seg, "STRUCTURAL_TERMINAL")

                direction = en["direction"]
                family = en["family"]
                rescue_px = event_price(rescue)
                reentry_px = event_price(reentry)
                terminal_px = event_price(terminal)

                if reentry_px is None:
                    continue

                end_ts = (
                    terminal["event_timestamp"]
                    if terminal is not None
                    else max(u[day], key=dt)
                )

                bs = bars(u[day], reentry["event_timestamp"], end_ts)

                mfe = max(
                    (favorable_from_reentry(direction, reentry_px, row) for _, row in bs),
                    default=None,
                )
                mae = min(
                    (adverse_from_reentry(direction, reentry_px, row) for _, row in bs),
                    default=None,
                )

                peak_ts = None
                peak_mfe = None
                for ts, row in bs:
                    x = favorable_from_reentry(direction, reentry_px, row)
                    if peak_mfe is None or x > peak_mfe:
                        peak_mfe = x
                        peak_ts = ts

                minutes_to_peak = (
                    (dt(peak_ts) - dt(reentry["event_timestamp"])).total_seconds() / 60.0
                    if peak_ts else None
                )

                threshold_hits = {
                    f"hit_{t}": mfe is not None and mfe >= t
                    for t in THRESHOLDS
                }
                threshold_times = {
                    f"hit_{t}_timestamp": first_threshold_hit(
                        direction, reentry_px, bs, t
                    ) or ""
                    for t in THRESHOLDS
                }

                ret20_ts, ret20_move = first_close_at_or_below(
                    direction, reentry_px, bs, 20.0, strictly=False
                )
                ret10_ts, ret10_move = first_close_at_or_below(
                    direction, reentry_px, bs, 10.0, strictly=False
                )
                ret0_ts, ret0_move = first_close_at_or_below(
                    direction, reentry_px, bs, 0.0, strictly=False
                )
                neg_ts, neg_move = first_close_negative(direction, reentry_px, bs)

                terminal_points = (
                    dpoints(direction, reentry_px, terminal_px)
                    if terminal_px is not None else None
                )
                giveback_peak_to_terminal = (
                    peak_mfe - terminal_points
                    if peak_mfe is not None and terminal_points is not None
                    else None
                )

                # Measure whether the trade had a meaningful favorable move before
                # returning to 0 / negative.
                peak_before_zero = None
                zero_boundary = ret0_ts or end_ts
                pre_zero_bars = bars(
                    u[day],
                    reentry["event_timestamp"],
                    zero_boundary,
                )
                if pre_zero_bars:
                    peak_before_zero = max(
                        favorable_from_reentry(direction, reentry_px, row)
                        for _, row in pre_zero_bars
                    )

                cases.append({
                    "block": block["name"],
                    "session_date": day,
                    "trade_seq": seq,
                    "family": family,
                    "direction": direction,
                    "rescue_timestamp": rescue["event_timestamp"],
                    "rescue_price": rescue_px,
                    "reentry_timestamp": reentry["event_timestamp"],
                    "reentry_price": reentry_px,
                    "terminal_timestamp": terminal["event_timestamp"] if terminal else "",
                    "terminal_price": terminal_px,
                    "comparable": terminal is not None,
                    "mfe_from_reentry": mfe,
                    "mae_from_reentry": mae,
                    "peak_timestamp": peak_ts or "",
                    "minutes_to_peak": minutes_to_peak,
                    "terminal_points": terminal_points,
                    "giveback_peak_to_terminal": giveback_peak_to_terminal,
                    "peak_before_close_back_to_zero": peak_before_zero,
                    "first_close_le_20_timestamp": ret20_ts or "",
                    "first_close_le_20_move": ret20_move,
                    "first_close_le_10_timestamp": ret10_ts or "",
                    "first_close_le_10_move": ret10_move,
                    "first_close_le_0_timestamp": ret0_ts or "",
                    "first_close_le_0_move": ret0_move,
                    "first_negative_close_timestamp": neg_ts or "",
                    "first_negative_close_move": neg_move,
                    **threshold_hits,
                    **threshold_times,
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

    def summarize(xs):
        comp = [c for c in xs if c["comparable"]]
        return {
            "cases": len(xs),
            "comparable": len(comp),
            "hit_rates": {
                str(t): {
                    "count": sum(c[f"hit_{t}"] for c in xs),
                    "pct": pct(sum(c[f"hit_{t}"] for c in xs), len(xs)),
                }
                for t in THRESHOLDS
            },
            "mfe_mean": mean(c["mfe_from_reentry"] for c in xs),
            "mfe_median": median(c["mfe_from_reentry"] for c in xs),
            "mae_mean": mean(c["mae_from_reentry"] for c in xs),
            "mae_median": median(c["mae_from_reentry"] for c in xs),
            "minutes_to_peak_mean": mean(c["minutes_to_peak"] for c in xs),
            "minutes_to_peak_median": median(c["minutes_to_peak"] for c in xs),
            "terminal_points_mean": mean(c["terminal_points"] for c in comp),
            "terminal_points_median": median(c["terminal_points"] for c in comp),
            "giveback_mean": mean(c["giveback_peak_to_terminal"] for c in comp),
            "giveback_median": median(c["giveback_peak_to_terminal"] for c in comp),
            "returned_to_20_or_less": sum(bool(c["first_close_le_20_timestamp"]) for c in xs),
            "returned_to_10_or_less": sum(bool(c["first_close_le_10_timestamp"]) for c in xs),
            "returned_to_0_or_less": sum(bool(c["first_close_le_0_timestamp"]) for c in xs),
            "negative_close_seen": sum(bool(c["first_negative_close_timestamp"]) for c in xs),
        }

    groups = {
        "B": [c for c in cases if c["family"] == "B"],
        "E": [c for c in cases if c["family"] == "E"],
        "B+E": cases,
    }

    report = {
        "model": "MIDPOINT_V60_POST_REENTRY_SECOND_LEG_AUDIT",
        "scope": "FIXED_EXISTING_REENTRY_TIMESTAMPS_NO_RULE_TUNING",
        "groups": {k: summarize(v) for k, v in groups.items()},
        "case_count": len(cases),
        "notes": [
            "Re-entry timestamps are not changed.",
            "No new exit rule is applied.",
            "Measures second-leg excursion, time-to-peak, giveback and first close back through +20/+10/0/negative.",
            "Uses V57 parity-proven historical replay.",
            "Underlying directional points only; no option P&L.",
        ],
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = []
    lines.append("MIDPOINT V60 — POST-REENTRY SECOND-LEG EXCURSION / GIVEBACK AUDIT")
    lines.append("=" * 108)
    lines.append("Existing re-entry timestamps frozen; no rule tuning")
    lines.append("")

    for label, xs in groups.items():
        s = summarize(xs)
        lines.append(label)
        lines.append("-" * 108)
        lines.append(f"cases={s['cases']} comparable={s['comparable']}")
        lines.append(
            " ".join(
                f"+{t}={s['hit_rates'][str(t)]['count']}/{s['cases']} "
                f"({s['hit_rates'][str(t)]['pct']}%)"
                for t in THRESHOLDS
            )
        )
        lines.append(
            f"MFE mean/median={s['mfe_mean']}/{s['mfe_median']} "
            f"MAE mean/median={s['mae_mean']}/{s['mae_median']}"
        )
        lines.append(
            f"time-to-peak mean/median minutes="
            f"{s['minutes_to_peak_mean']}/{s['minutes_to_peak_median']}"
        )
        lines.append(
            f"terminal points mean/median="
            f"{s['terminal_points_mean']}/{s['terminal_points_median']}"
        )
        lines.append(
            f"peak-to-terminal giveback mean/median="
            f"{s['giveback_mean']}/{s['giveback_median']}"
        )
        lines.append(
            f"returned <=+20={s['returned_to_20_or_less']} "
            f"<=+10={s['returned_to_10_or_less']} "
            f"<=0={s['returned_to_0_or_less']} "
            f"negative_close={s['negative_close_seen']}"
        )
        lines.append("")

    lines.append("CASES")
    lines.append("-" * 108)
    for c in cases:
        hit_txt = " ".join(
            f"+{t}={'Y' if c[f'hit_{t}'] else 'N'}"
            for t in THRESHOLDS
        )
        lines.append(
            f"{c['session_date']} {c['family']} {c['direction']} "
            f"reentry={c['reentry_timestamp']} "
            f"MFE={c['mfe_from_reentry']} "
            f"peak={c['peak_timestamp']} "
            f"mins_to_peak={c['minutes_to_peak']} "
            f"terminal={c['terminal_timestamp'] or 'OPEN'} "
            f"terminal_pts={c['terminal_points']} "
            f"giveback={c['giveback_peak_to_terminal']} "
            f"{hit_txt}"
        )

    lines.append("")
    lines.append(f"CASE CSV    = {CASE_CSV}")
    lines.append(f"REPORT JSON = {REPORT_JSON}")
    lines.append(f"SUMMARY     = {SUMMARY_TXT}")

    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
