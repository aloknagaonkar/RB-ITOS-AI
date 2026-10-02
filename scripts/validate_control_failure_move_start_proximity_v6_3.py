from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

MODEL = "CONTROL_FAILURE_MOVE_START_PROXIMITY_V6_3"
WINDOWS = (5, 10, 15, 20, 30)
ORDERS = ("SAME_CANDLE", "FAILURE_THEN_DECAY", "DECAY_THEN_FAILURE")


def _f(v: Any) -> float | None:
    if v in (None, ""):
        return None
    return float(v)


def _mean(xs: list[float | None]) -> float | None:
    ys = [x for x in xs if x is not None]
    return sum(ys) / len(ys) if ys else None


def _median(xs: list[float | None]) -> float | None:
    ys = [x for x in xs if x is not None]
    return float(statistics.median(ys)) if ys else None


def _dt(v: str) -> datetime:
    return datetime.fromisoformat(v)


def lead_lag_minutes(checkpoint: str, move_start: str) -> float:
    a = _dt(checkpoint)
    if "T" in move_start:
        b = _dt(move_start)
    else:
        off = a.strftime("%z")
        off = f"{off[:3]}:{off[3:]}" if off else ""
        b = datetime.fromisoformat(f"{a.date().isoformat()}T{move_start}:00{off}")
    return (a - b).total_seconds() / 60.0


def load_move_starts(path: Path) -> dict[str, str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("research_version") != "TREND_DAY_MOVE_START_OI_REPLAY_V1":
        raise ValueError(f"Unexpected replay version: {doc.get('research_version')}")
    out: dict[str, str] = {}
    for r in doc.get("rows") or []:
        ds = str(r.get("session_date") or "")
        ms = r.get("move_start_time")
        if ds and ms:
            out.setdefault(ds, str(ms))
    return out


def load_known_directions(matrix_path: Path) -> dict[str, str]:
    with matrix_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return {r["session_date"]: r["known_direction"] for r in rows if r.get("session_date") and r.get("known_direction")}


def nearest_event(events: list[dict[str, str]], move_start: str, window: int) -> dict[str, str] | None:
    eligible = []
    for r in events:
        cp = r.get("detected_checkpoint")
        if not cp:
            continue
        delta = lead_lag_minutes(cp, move_start)
        if abs(delta) <= window:
            eligible.append((abs(delta), 0 if delta <= 0 else 1, delta, cp, r))
    if not eligible:
        return None
    # Closest first; on an exact distance tie prefer pre-move/at-move signal, then earlier timestamp.
    eligible.sort(key=lambda x: (x[0], x[1], x[3]))
    return eligible[0][4]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v6-2-dir", default="data/historical-evidence/control-failure-expiry-aware-v6-2")
    ap.add_argument("--move-start-replay", default="data/historical-evidence/trend-day-move-start-oi-replay-v1.json")
    ap.add_argument("--output-dir", default="data/historical-evidence/control-failure-move-start-proximity-v6-3")
    args = ap.parse_args()

    v62 = Path(args.v6_2_dir)
    events_path = v62 / "control-failure-events-expiry-aware-v6-2.csv"
    matrix_path = v62 / "expiry-aware-validation-matrix-v6-2.csv"
    replay_path = Path(args.move_start_replay)
    if not events_path.exists():
        raise FileNotFoundError(events_path)
    if not matrix_path.exists():
        raise FileNotFoundError(matrix_path)
    if not replay_path.exists():
        raise FileNotFoundError(replay_path)

    with events_path.open(newline="", encoding="utf-8") as fh:
        events = list(csv.DictReader(fh))
    known = load_known_directions(matrix_path)
    move_starts = load_move_starts(replay_path)

    by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in events:
        by_date[r["session_date"]].append(r)

    detail: list[dict[str, Any]] = []
    for ds, direction in sorted(known.items()):
        if ds not in move_starts:
            continue
        day_same = [r for r in by_date.get(ds, []) if r.get("direction") == direction]
        for window in WINDOWS:
            hit = nearest_event(day_same, move_starts[ds], window)
            row: dict[str, Any] = {
                "session_date": ds,
                "known_direction": direction,
                "move_start_time": move_starts[ds],
                "window_minutes": window,
                "candidate_found": bool(hit),
            }
            if hit:
                ll = lead_lag_minutes(hit["detected_checkpoint"], move_starts[ds])
                row.update({
                    "signal_checkpoint": hit.get("detected_checkpoint"),
                    "signal_candle_start": hit.get("detection_candle_start"),
                    "signal_candle_end": hit.get("detection_candle_end"),
                    "lead_lag_minutes": ll,
                    "abs_distance_minutes": abs(ll),
                    "pre_or_post_move": "PRE_OR_AT" if ll <= 0 else "POST",
                    "component_order": hit.get("component_order"),
                    "selected_wings": hit.get("selected_wings"),
                    "atm_state": hit.get("atm_state"),
                    "bullish_strikes": hit.get("bullish_strikes"),
                    "bearish_strikes": hit.get("bearish_strikes"),
                    "imbalance": hit.get("imbalance"),
                    "imbalance_velocity": hit.get("imbalance_velocity"),
                    "imbalance_acceleration": hit.get("imbalance_acceleration"),
                    "move_5m": _f(hit.get("move_5m")),
                    "move_10m": _f(hit.get("move_10m")),
                    "move_15m": _f(hit.get("move_15m")),
                    "move_30m": _f(hit.get("move_30m")),
                    "mfe_30m": _f(hit.get("mfe_30m")),
                    "mae_30m": _f(hit.get("mae_30m")),
                })
            detail.append(row)

    summary: list[dict[str, Any]] = []
    for window in WINDOWS:
        for direction in ("BULLISH", "BEARISH"):
            rows = [r for r in detail if r["window_minutes"] == window and r["known_direction"] == direction]
            found = [r for r in rows if r["candidate_found"]]
            leads = [_f(r.get("lead_lag_minutes")) for r in found]
            summary.append({
                "window_minutes": window,
                "known_direction": direction,
                "sessions_with_move_start": len(rows),
                "sessions_with_candidate": len(found),
                "detection_rate_pct": (100.0 * len(found) / len(rows)) if rows else None,
                "pre_or_at_move_count": sum(1 for r in found if r.get("pre_or_post_move") == "PRE_OR_AT"),
                "post_move_count": sum(1 for r in found if r.get("pre_or_post_move") == "POST"),
                "avg_lead_lag_minutes": _mean(leads),
                "median_lead_lag_minutes": _median(leads),
                "avg_abs_distance_minutes": _mean([_f(r.get("abs_distance_minutes")) for r in found]),
                "median_abs_distance_minutes": _median([_f(r.get("abs_distance_minutes")) for r in found]),
                "avg_move_5m": _mean([_f(r.get("move_5m")) for r in found]),
                "avg_move_10m": _mean([_f(r.get("move_10m")) for r in found]),
                "avg_move_15m": _mean([_f(r.get("move_15m")) for r in found]),
                "avg_move_30m": _mean([_f(r.get("move_30m")) for r in found]),
                "median_move_15m": _median([_f(r.get("move_15m")) for r in found]),
                "median_move_30m": _median([_f(r.get("move_30m")) for r in found]),
                "positive_15m_rate_pct": (100.0 * sum(1 for r in found if _f(r.get("move_15m")) is not None and _f(r.get("move_15m")) > 0) / sum(1 for r in found if _f(r.get("move_15m")) is not None)) if any(_f(r.get("move_15m")) is not None for r in found) else None,
                "positive_30m_rate_pct": (100.0 * sum(1 for r in found if _f(r.get("move_30m")) is not None and _f(r.get("move_30m")) > 0) / sum(1 for r in found if _f(r.get("move_30m")) is not None)) if any(_f(r.get("move_30m")) is not None for r in found) else None,
                "orders": json.dumps({o: sum(1 for r in found if r.get("component_order") == o) for o in ORDERS}, sort_keys=True),
            })

    order_summary: list[dict[str, Any]] = []
    # Primary ±15m window, split by component order.
    primary = [r for r in detail if r["window_minutes"] == 15 and r["candidate_found"]]
    for direction in ("BULLISH", "BEARISH"):
        for order in ORDERS:
            rows = [r for r in primary if r["known_direction"] == direction and r.get("component_order") == order]
            order_summary.append({
                "known_direction": direction,
                "component_order": order,
                "sessions": len(rows),
                "median_lead_lag_minutes": _median([_f(r.get("lead_lag_minutes")) for r in rows]),
                "median_abs_distance_minutes": _median([_f(r.get("abs_distance_minutes")) for r in rows]),
                "median_move_15m": _median([_f(r.get("move_15m")) for r in rows]),
                "median_move_30m": _median([_f(r.get("move_30m")) for r in rows]),
                "positive_15m_rate_pct": (100.0 * sum(1 for r in rows if _f(r.get("move_15m")) is not None and _f(r.get("move_15m")) > 0) / sum(1 for r in rows if _f(r.get("move_15m")) is not None)) if any(_f(r.get("move_15m")) is not None for r in rows) else None,
                "positive_30m_rate_pct": (100.0 * sum(1 for r in rows if _f(r.get("move_30m")) is not None and _f(r.get("move_30m")) > 0) / sum(1 for r in rows if _f(r.get("move_30m")) is not None)) if any(_f(r.get("move_30m")) is not None for r in rows) else None,
            })

    out = Path(args.output_dir)
    detail_fields = [
        "session_date","known_direction","move_start_time","window_minutes","candidate_found",
        "signal_checkpoint","signal_candle_start","signal_candle_end","lead_lag_minutes","abs_distance_minutes",
        "pre_or_post_move","component_order","selected_wings","atm_state","bullish_strikes","bearish_strikes",
        "imbalance","imbalance_velocity","imbalance_acceleration","move_5m","move_10m","move_15m","move_30m","mfe_30m","mae_30m"
    ]
    summary_fields = list(summary[0].keys()) if summary else []
    order_fields = list(order_summary[0].keys()) if order_summary else []
    write_csv(out / "move-start-proximity-detail-v6-3.csv", detail, detail_fields)
    write_csv(out / "move-start-proximity-summary-v6-3.csv", summary, summary_fields)
    write_csv(out / "move-start-proximity-order-study-v6-3.csv", order_summary, order_fields)

    doc = {
        "model": MODEL,
        "source_events": str(events_path),
        "source_move_start_replay": str(replay_path),
        "signal_logic_changed": False,
        "expiry_aware_baskets_reused": True,
        "evaluation_only": True,
        "windows_minutes": list(WINDOWS),
        "nearest_candidate_tie_break": "closest absolute distance; on tie prefer pre/at-move signal; then earlier timestamp",
        "primary_window_minutes": 15,
        "summary": summary,
        "order_study_primary_15m": order_summary,
    }
    (out / "move-start-proximity-summary-v6-3.json").write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(f"model={MODEL} events={len(events)} move_start_sessions={len(move_starts)}")
    print("\n=== MOVE-START PROXIMITY SUMMARY ===")
    for r in summary:
        print(
            f"±{r['window_minutes']}m {r['known_direction']}: "
            f"detected={r['sessions_with_candidate']}/{r['sessions_with_move_start']} "
            f"rate={r['detection_rate_pct']}% pre_or_at={r['pre_or_at_move_count']} post={r['post_move_count']} "
            f"median_ll={r['median_lead_lag_minutes']} median_abs={r['median_abs_distance_minutes']} "
            f"med15={r['median_move_15m']} med30={r['median_move_30m']} "
            f"hit15={r['positive_15m_rate_pct']}% hit30={r['positive_30m_rate_pct']}%"
        )
    print("\n=== PRIMARY ±15m ORDER STUDY ===")
    for r in order_summary:
        print(
            f"{r['known_direction']} {r['component_order']}: sessions={r['sessions']} "
            f"median_ll={r['median_lead_lag_minutes']} median_abs={r['median_abs_distance_minutes']} "
            f"med15={r['median_move_15m']} med30={r['median_move_30m']} "
            f"hit15={r['positive_15m_rate_pct']}% hit30={r['positive_30m_rate_pct']}%"
        )
    print(f"DETAIL_CSV: {out / 'move-start-proximity-detail-v6-3.csv'}")
    print(f"SUMMARY_CSV: {out / 'move-start-proximity-summary-v6-3.csv'}")
    print(f"ORDER_CSV: {out / 'move-start-proximity-order-study-v6-3.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
