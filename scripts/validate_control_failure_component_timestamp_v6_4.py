from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

MODEL = "CONTROL_FAILURE_COMPONENT_TIMESTAMP_ATTRIBUTION_V6_4"
PRIMARY_WINDOW_MINUTES = 15


def _dt(v: str) -> datetime:
    return datetime.fromisoformat(v)


def _f(v: Any) -> float | None:
    if v in (None, ""):
        return None
    return float(v)


def _median(xs: list[float | None]) -> float | None:
    ys = [x for x in xs if x is not None]
    return float(statistics.median(ys)) if ys else None


def _mean(xs: list[float | None]) -> float | None:
    ys = [x for x in xs if x is not None]
    return sum(ys) / len(ys) if ys else None


def resolve_move_start(reference_checkpoint: str, move_start: str) -> datetime:
    if "T" in move_start:
        return _dt(move_start)
    ref = _dt(reference_checkpoint)
    off = ref.strftime("%z")
    off = f"{off[:3]}:{off[3:]}" if off else ""
    return datetime.fromisoformat(f"{ref.date().isoformat()}T{move_start}:00{off}")


def lead_lag_minutes(checkpoint: str, move_start: str) -> float:
    cp = _dt(checkpoint)
    ms = resolve_move_start(checkpoint, move_start)
    return (cp - ms).total_seconds() / 60.0


def candle_relation(candle_start: str, candle_end: str, move_start: str) -> str:
    start = _dt(candle_start)
    end = _dt(candle_end)
    ms = resolve_move_start(candle_end, move_start)
    if ms < start:
        return "MOVE_BEFORE_SIGNAL_CANDLE"
    if start <= ms <= end:
        return "MOVE_INSIDE_SIGNAL_CANDLE"
    return "MOVE_AFTER_SIGNAL_CANDLE"


def component_order_timing(failure_ll: float | None, decay_ll: float | None) -> str:
    vals = [("FAILURE", failure_ll), ("DECAY", decay_ll)]
    vals = [(name, val) for name, val in vals if val is not None]
    if not vals:
        return "NO_COMPONENT_TIMESTAMPS"
    if len(vals) == 1:
        return f"{vals[0][0]}_ONLY"
    if failure_ll == decay_ll:
        return "SAME_CANDLE"
    return "FAILURE_THEN_DECAY" if failure_ll < decay_ll else "DECAY_THEN_FAILURE"


def earliest_component(failure_cp: str | None, decay_cp: str | None, move_start: str) -> tuple[str | None, float | None]:
    pairs: list[tuple[datetime, str, float]] = []
    for name, cp in (("FAILURE", failure_cp), ("DECAY", decay_cp)):
        if cp:
            pairs.append((_dt(cp), name, lead_lag_minutes(cp, move_start)))
    if not pairs:
        return None, None
    pairs.sort(key=lambda x: x[0])
    return pairs[0][1], pairs[0][2]


def closest_component(failure_cp: str | None, decay_cp: str | None, move_start: str) -> tuple[str | None, float | None]:
    vals: list[tuple[float, int, str, float]] = []
    for name, cp in (("FAILURE", failure_cp), ("DECAY", decay_cp)):
        if not cp:
            continue
        ll = lead_lag_minutes(cp, move_start)
        vals.append((abs(ll), 0 if ll <= 0 else 1, name, ll))
    if not vals:
        return None, None
    vals.sort(key=lambda x: (x[0], x[1], x[2]))
    return vals[0][2], vals[0][3]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


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
    ap.add_argument("--v6-3-dir", default="data/historical-evidence/control-failure-move-start-proximity-v6-3")
    ap.add_argument("--output-dir", default="data/historical-evidence/control-failure-component-timestamp-v6-4")
    args = ap.parse_args()

    events_path = Path(args.v6_2_dir) / "control-failure-events-expiry-aware-v6-2.csv"
    prox_path = Path(args.v6_3_dir) / "move-start-proximity-detail-v6-3.csv"
    if not events_path.exists():
        raise FileNotFoundError(events_path)
    if not prox_path.exists():
        raise FileNotFoundError(prox_path)

    events = load_csv(events_path)
    prox = load_csv(prox_path)
    event_index = {
        (r.get("session_date"), r.get("direction"), r.get("detected_checkpoint")): r
        for r in events
        if r.get("session_date") and r.get("direction") and r.get("detected_checkpoint")
    }

    matched = [
        r for r in prox
        if int(r.get("window_minutes") or -1) == PRIMARY_WINDOW_MINUTES
        and str(r.get("candidate_found", "")).lower() in {"true", "1", "yes"}
    ]

    detail: list[dict[str, Any]] = []
    for r in matched:
        key = (r.get("session_date"), r.get("known_direction"), r.get("signal_checkpoint"))
        ev = event_index.get(key)
        if ev is None:
            raise RuntimeError(f"No V6.2 event found for matched V6.3 row: {key}")

        move_start = r["move_start_time"]
        failure_cp = ev.get("failure_checkpoint") or None
        decay_cp = ev.get("decay_checkpoint") or None
        signal_cp = r.get("signal_checkpoint") or ev.get("detected_checkpoint")
        candle_start = r.get("signal_candle_start") or ev.get("detection_candle_start")
        candle_end = r.get("signal_candle_end") or ev.get("detection_candle_end")

        signal_ll = lead_lag_minutes(signal_cp, move_start) if signal_cp else None
        failure_ll = lead_lag_minutes(failure_cp, move_start) if failure_cp else None
        decay_ll = lead_lag_minutes(decay_cp, move_start) if decay_cp else None
        candle_start_ll = lead_lag_minutes(candle_start, move_start) if candle_start else None
        candle_end_ll = lead_lag_minutes(candle_end, move_start) if candle_end else None
        earliest_name, earliest_ll = earliest_component(failure_cp, decay_cp, move_start)
        closest_name, closest_ll = closest_component(failure_cp, decay_cp, move_start)

        detail.append({
            "session_date": r.get("session_date"),
            "known_direction": r.get("known_direction"),
            "move_start_time": move_start,
            "selected_wings": r.get("selected_wings") or ev.get("selected_wings"),
            "component_order": ev.get("component_order"),
            "signal_checkpoint": signal_cp,
            "signal_lead_lag_minutes": signal_ll,
            "signal_candle_start": candle_start,
            "signal_candle_end": candle_end,
            "signal_candle_start_ll": candle_start_ll,
            "signal_candle_end_ll": candle_end_ll,
            "move_vs_signal_candle": candle_relation(candle_start, candle_end, move_start) if candle_start and candle_end else None,
            "failure_checkpoint": failure_cp,
            "failure_lead_lag_minutes": failure_ll,
            "decay_checkpoint": decay_cp,
            "decay_lead_lag_minutes": decay_ll,
            "timing_order_from_timestamps": component_order_timing(failure_ll, decay_ll),
            "earliest_component": earliest_name,
            "earliest_component_lead_lag_minutes": earliest_ll,
            "closest_component": closest_name,
            "closest_component_lead_lag_minutes": closest_ll,
            "earliest_component_pre_or_at_move": (earliest_ll is not None and earliest_ll <= 0),
            "any_component_pre_or_at_move": any(v is not None and v <= 0 for v in (failure_ll, decay_ll)),
            "signal_pre_or_at_move": signal_ll is not None and signal_ll <= 0,
            "atm_state": ev.get("atm_state"),
            "bullish_strikes": ev.get("bullish_strikes"),
            "bearish_strikes": ev.get("bearish_strikes"),
            "imbalance": ev.get("imbalance"),
            "imbalance_velocity": ev.get("imbalance_velocity"),
            "imbalance_acceleration": ev.get("imbalance_acceleration"),
            "move_5m": _f(ev.get("move_5m")),
            "move_10m": _f(ev.get("move_10m")),
            "move_15m": _f(ev.get("move_15m")),
            "move_30m": _f(ev.get("move_30m")),
            "mfe_30m": _f(ev.get("mfe_30m")),
            "mae_30m": _f(ev.get("mae_30m")),
        })

    summary: list[dict[str, Any]] = []
    for direction in ("BULLISH", "BEARISH"):
        rows = [r for r in detail if r["known_direction"] == direction]
        summary.append({
            "known_direction": direction,
            "matched_sessions": len(rows),
            "signal_pre_or_at_count": sum(1 for r in rows if r["signal_pre_or_at_move"]),
            "any_component_pre_or_at_count": sum(1 for r in rows if r["any_component_pre_or_at_move"]),
            "move_inside_signal_candle_count": sum(1 for r in rows if r["move_vs_signal_candle"] == "MOVE_INSIDE_SIGNAL_CANDLE"),
            "median_signal_lead_lag_minutes": _median([_f(r.get("signal_lead_lag_minutes")) for r in rows]),
            "median_earliest_component_lead_lag_minutes": _median([_f(r.get("earliest_component_lead_lag_minutes")) for r in rows]),
            "median_closest_component_lead_lag_minutes": _median([_f(r.get("closest_component_lead_lag_minutes")) for r in rows]),
            "median_move_15m": _median([_f(r.get("move_15m")) for r in rows]),
            "median_move_30m": _median([_f(r.get("move_30m")) for r in rows]),
            "component_orders": json.dumps(dict(Counter(r.get("component_order") for r in rows)), sort_keys=True),
            "earliest_components": json.dumps(dict(Counter(r.get("earliest_component") for r in rows)), sort_keys=True),
        })

    out = Path(args.output_dir)
    fields = list(detail[0].keys()) if detail else []
    summary_fields = list(summary[0].keys()) if summary else []
    write_csv(out / "component-timestamp-detail-v6-4.csv", detail, fields)
    write_csv(out / "component-timestamp-summary-v6-4.csv", summary, summary_fields)

    doc = {
        "model": MODEL,
        "source_v6_2_events": str(events_path),
        "source_v6_3_proximity": str(prox_path),
        "primary_window_minutes": PRIMARY_WINDOW_MINUTES,
        "signal_logic_changed": False,
        "expiry_aware_baskets_changed": False,
        "evaluation_only": True,
        "lead_lag_definition": "component_or_signal_time - retrospective_move_start_time",
        "detail_rows": detail,
        "summary": summary,
    }
    (out / "component-timestamp-summary-v6-4.json").write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(f"model={MODEL} matched_pm15_events={len(detail)}")
    print("\n=== COMPONENT TIMESTAMP ATTRIBUTION (PRIMARY ±15m MATCHES) ===")
    for r in detail:
        failure_txt = (
            f"{r['failure_checkpoint']}({r['failure_lead_lag_minutes']:+.0f}m)"
            if r['failure_checkpoint'] else "—"
        )
        decay_txt = (
            f"{r['decay_checkpoint']}({r['decay_lead_lag_minutes']:+.0f}m)"
            if r['decay_checkpoint'] else "—"
        )
        earliest_txt = (
            f"{r['earliest_component']}({r['earliest_component_lead_lag_minutes']:+.0f}m)"
            if r['earliest_component'] else "—"
        )
        closest_txt = (
            f"{r['closest_component']}({r['closest_component_lead_lag_minutes']:+.0f}m)"
            if r['closest_component'] else "—"
        )
        print(
            f"{r['session_date']} {r['known_direction']} move={r['move_start_time']} "
            f"signal={r['signal_checkpoint']}({r['signal_lead_lag_minutes']:+.0f}m) "
            f"failure={failure_txt} decay={decay_txt} order={r['component_order']}"
        )
        print(
            f"  candle={r['signal_candle_start']} -> {r['signal_candle_end']} "
            f"relation={r['move_vs_signal_candle']} earliest={earliest_txt} "
            f"closest={closest_txt} +15={r['move_15m']} +30={r['move_30m']}"
        )
    print("\n=== SUMMARY ===")
    for r in summary:
        print(
            f"{r['known_direction']}: matched={r['matched_sessions']} "
            f"signal_pre_or_at={r['signal_pre_or_at_count']} "
            f"any_component_pre_or_at={r['any_component_pre_or_at_count']} "
            f"move_inside_signal_candle={r['move_inside_signal_candle_count']} "
            f"median_signal_ll={r['median_signal_lead_lag_minutes']} "
            f"median_earliest_component_ll={r['median_earliest_component_lead_lag_minutes']} "
            f"median_closest_component_ll={r['median_closest_component_lead_lag_minutes']}"
        )
    print(f"DETAIL_CSV: {out / 'component-timestamp-detail-v6-4.csv'}")
    print(f"SUMMARY_CSV: {out / 'component-timestamp-summary-v6-4.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
