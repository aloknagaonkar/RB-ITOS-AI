from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

MODEL = "CONTROL_FAILURE_EXPIRY_AWARE_VALIDATION_V6_2"

BULLISH_DATES = [
    "2026-05-18", "2026-05-20", "2026-05-25",
    "2026-06-02", "2026-06-12", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-24",
    "2026-07-06", "2026-07-10", "2026-07-13", "2026-07-17", "2026-07-27", "2026-07-29",
    "2026-08-03", "2026-08-25", "2026-09-02",
]
BEARISH_DATES = [
    "2026-05-12", "2026-05-19", "2026-05-29",
    "2026-06-01", "2026-06-23", "2026-06-29",
    "2026-07-07", "2026-07-08", "2026-07-14", "2026-07-16", "2026-07-22",
    "2026-08-18", "2026-08-24", "2026-08-26", "2026-08-27",
    "2026-09-03", "2026-09-07", "2026-09-08",
]
ALL_DATES = sorted(BULLISH_DATES + BEARISH_DATES)
CLASS_BY_DATE = {d: "BULLISH" for d in BULLISH_DATES} | {d: "BEARISH" for d in BEARISH_DATES}
ORDERS = ("SAME_CANDLE", "FAILURE_THEN_DECAY", "DECAY_THEN_FAILURE")


def _f(v: Any) -> float | None:
    if v in (None, ""):
        return None
    return float(v)


def _mean(vals: list[float | None]) -> float | None:
    xs = [x for x in vals if x is not None]
    return sum(xs) / len(xs) if xs else None


def _median(vals: list[float | None]) -> float | None:
    xs = [x for x in vals if x is not None]
    return float(statistics.median(xs)) if xs else None


def weekday_sessions_to_expiry(session_date: str, expiry: str) -> int:
    """Count Mon-Fri sessions strictly after session_date through expiry, inclusive.

    This encodes the user's frozen rule semantics. Exact expiry is read from the
    historical build. The count is intentionally surfaced in outputs so holiday
    edge-cases can be audited rather than hidden.
    """
    s = date.fromisoformat(session_date)
    e = date.fromisoformat(expiry)
    if e < s:
        raise ValueError(f"expiry {expiry} precedes session {session_date}")
    count = 0
    cur = s + timedelta(days=1)
    while cur <= e:
        if cur.weekday() < 5:
            count += 1
        cur += timedelta(days=1)
    return count


def wings_for_sessions_left(sessions_left: int) -> int:
    # Frozen expiry-aware rule: D0->±1, D1->±2, D2->±3, D3->±4, D4+->±5.
    if sessions_left < 0:
        raise ValueError(sessions_left)
    return min(5, sessions_left + 1)


def _positioning_path(root: Path, ds: str) -> Path:
    return root / ds / "positioning.json"


def read_positioning_meta(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "status": "MISSING", "expiry": None}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"exists": True, "status": f"INVALID_JSON:{type(exc).__name__}", "expiry": None}
    sessions = doc.get("sessions") or []
    if len(sessions) != 1:
        return {"exists": True, "status": f"INVALID_SESSION_COUNT:{len(sessions)}", "expiry": None}
    s = sessions[0]
    expiry = s.get("expiry") or s.get("expiry_date")
    return {"exists": True, "status": str(s.get("status") or "UNKNOWN"), "expiry": str(expiry) if expiry else None}


def discover_move_start_replay(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    for p in [Path("data/historical-evidence/trend-day-move-start-oi-replay-v1.json")]:
        if p.exists():
            return p
    return None


def load_move_starts(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("research_version") != "TREND_DAY_MOVE_START_OI_REPLAY_V1":
        raise ValueError(f"Unexpected replay version in {path}")
    out: dict[str, str] = {}
    for r in doc.get("rows") or []:
        ds = str(r.get("session_date") or "")
        ms = r.get("move_start_time")
        if ds and ms:
            out.setdefault(ds, str(ms))
    return out


def lead_lag_minutes(checkpoint: str | None, move_start: str | None) -> float | None:
    if not checkpoint or not move_start:
        return None
    a = datetime.fromisoformat(checkpoint)
    if "T" in move_start:
        b = datetime.fromisoformat(move_start)
    else:
        off = a.strftime("%z")
        off = f"{off[:3]}:{off[3:]}" if off else ""
        b = datetime.fromisoformat(f"{a.date().isoformat()}T{move_start}:00{off}")
    return (a - b).total_seconds() / 60.0


def run_v5_group(dates: list[str], wings: int, output_dir: Path) -> list[dict[str, str]]:
    if not dates:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "scripts/analyze_control_failure_historical_v5.py",
        "--dates", *dates,
        "--wings", str(wings),
        "--output-dir", str(output_dir),
    ]
    subprocess.run(cmd, check=True)
    p = output_dir / "control-failure-events-v5.csv"
    with p.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["selected_wings"] = str(wings)
    return rows


def write_dict_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        if fieldnames:
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k) for k in fieldnames})


@dataclass
class MatrixRow:
    session_date: str
    known_direction: str
    build_status: str
    expiry: str | None
    weekday_sessions_to_expiry: int | None
    selected_wings: int | None
    basket_size: int | None
    event_count: int
    same_direction_count: int
    opposite_direction_count: int
    first_same_direction_checkpoint: str | None
    first_same_direction_order: str | None
    first_same_direction_move_5m: float | None
    first_same_direction_move_10m: float | None
    first_same_direction_move_15m: float | None
    first_same_direction_move_30m: float | None
    move_start: str | None
    lead_lag_minutes: float | None


def make_matrix(events: list[dict[str, str]], inventory: dict[str, dict[str, Any]], move_starts: dict[str, str]) -> list[MatrixRow]:
    by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in events:
        by_date[r["session_date"]].append(r)
    out: list[MatrixRow] = []
    for ds in ALL_DATES:
        day = sorted(by_date.get(ds, []), key=lambda r: r.get("detected_checkpoint") or "")
        known = CLASS_BY_DATE[ds]
        same = [r for r in day if r.get("direction") == known]
        opp = [r for r in day if r.get("direction") != known]
        first = same[0] if same else None
        inv = inventory[ds]
        ms = move_starts.get(ds)
        cp = first.get("detected_checkpoint") if first else None
        out.append(MatrixRow(
            session_date=ds,
            known_direction=known,
            build_status=str(inv["status"]),
            expiry=inv.get("expiry"),
            weekday_sessions_to_expiry=inv.get("sessions_left"),
            selected_wings=inv.get("wings"),
            basket_size=(2 * int(inv["wings"]) + 1) if inv.get("wings") is not None else None,
            event_count=len(day),
            same_direction_count=len(same),
            opposite_direction_count=len(opp),
            first_same_direction_checkpoint=cp,
            first_same_direction_order=first.get("component_order") if first else None,
            first_same_direction_move_5m=_f(first.get("move_5m")) if first else None,
            first_same_direction_move_10m=_f(first.get("move_10m")) if first else None,
            first_same_direction_move_15m=_f(first.get("move_15m")) if first else None,
            first_same_direction_move_30m=_f(first.get("move_30m")) if first else None,
            move_start=ms,
            lead_lag_minutes=lead_lag_minutes(cp, ms),
        ))
    return out


def event_order_study(events: list[dict[str, str]], move_starts: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for known in ("BULLISH", "BEARISH"):
        known_dates = {d for d, v in CLASS_BY_DATE.items() if v == known}
        for relation in ("SAME_DIRECTION", "OPPOSITE_DIRECTION"):
            for order in ORDERS:
                subset = [
                    r for r in events
                    if r.get("session_date") in known_dates
                    and r.get("component_order") == order
                    and ((r.get("direction") == known) == (relation == "SAME_DIRECTION"))
                ]
                leads = [lead_lag_minutes(r.get("detected_checkpoint"), move_starts.get(r.get("session_date", ""))) for r in subset]
                m5 = [_f(r.get("move_5m")) for r in subset]
                m10 = [_f(r.get("move_10m")) for r in subset]
                m15 = [_f(r.get("move_15m")) for r in subset]
                m30 = [_f(r.get("move_30m")) for r in subset]
                mfe = [_f(r.get("mfe_30m")) for r in subset]
                mae = [_f(r.get("mae_30m")) for r in subset]
                rows.append({
                    "known_day_direction": known,
                    "event_relation": relation,
                    "component_order": order,
                    "events": len(subset),
                    "unique_sessions": len({r.get("session_date") for r in subset}),
                    "avg_lead_lag_minutes": _mean(leads),
                    "median_lead_lag_minutes": _median(leads),
                    "avg_move_5m": _mean(m5),
                    "median_move_5m": _median(m5),
                    "avg_move_10m": _mean(m10),
                    "median_move_10m": _median(m10),
                    "avg_move_15m": _mean(m15),
                    "median_move_15m": _median(m15),
                    "avg_move_30m": _mean(m30),
                    "median_move_30m": _median(m30),
                    "avg_mfe_30m": _mean(mfe),
                    "median_mfe_30m": _median(mfe),
                    "avg_mae_30m": _mean(mae),
                    "median_mae_30m": _median(mae),
                    "positive_15m_rate_pct": (sum(x is not None and x > 0 for x in m15) / sum(x is not None for x in m15) * 100.0) if any(x is not None for x in m15) else None,
                    "positive_30m_rate_pct": (sum(x is not None and x > 0 for x in m30) / sum(x is not None for x in m30) * 100.0) if any(x is not None for x in m30) else None,
                })
    return rows


def print_mapping(inventory: dict[str, dict[str, Any]]) -> None:
    print("\n=== EXPIRY-AWARE BASKET MAP ===")
    print("DATE        DIR      EXPIRY      SESS_LEFT WINGS SIZE STATUS")
    for ds in ALL_DATES:
        r = inventory[ds]
        print(f"{ds}  {CLASS_BY_DATE[ds]:7}  {str(r.get('expiry') or '—'):10}  {str(r.get('sessions_left') if r.get('sessions_left') is not None else '—'):>9}  {str(r.get('wings') if r.get('wings') is not None else '—'):>5}  {str((2*r['wings']+1) if r.get('wings') is not None else '—'):>4} {r['status']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-root", default="data/historical-evidence/historical-oi-build")
    ap.add_argument("--output-dir", default="data/historical-evidence/control-failure-expiry-aware-v6-2")
    ap.add_argument("--move-start-replay")
    ap.add_argument("--skip-v5-run", action="store_true")
    args = ap.parse_args()

    build_root = Path(args.build_root)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    inventory: dict[str, dict[str, Any]] = {}
    groups: dict[int, list[str]] = defaultdict(list)
    inv_rows: list[dict[str, Any]] = []
    for ds in ALL_DATES:
        meta = read_positioning_meta(_positioning_path(build_root, ds))
        expiry = meta.get("expiry")
        sessions_left = None
        wings = None
        if meta.get("status") == "AVAILABLE" and expiry:
            sessions_left = weekday_sessions_to_expiry(ds, expiry)
            wings = wings_for_sessions_left(sessions_left)
            groups[wings].append(ds)
        inventory[ds] = {**meta, "sessions_left": sessions_left, "wings": wings}
        inv_rows.append({
            "session_date": ds,
            "known_direction": CLASS_BY_DATE[ds],
            "status": meta.get("status"),
            "expiry": expiry,
            "weekday_sessions_to_expiry": sessions_left,
            "selected_wings": wings,
            "basket_size": (2 * wings + 1) if wings is not None else None,
        })

    inv_path = out / "expiry-aware-inventory-v6-2.csv"
    write_dict_csv(inv_path, inv_rows)
    print_mapping(inventory)

    available = [d for d in ALL_DATES if inventory[d].get("status") == "AVAILABLE" and inventory[d].get("wings") is not None]
    unavailable = [d for d in ALL_DATES if d not in available]
    print(f"\nAVAILABLE={len(available)} UNAVAILABLE={len(unavailable)}")
    if unavailable:
        print("UNAVAILABLE_DATES=" + " ".join(unavailable))

    merged_events_path = out / "control-failure-events-expiry-aware-v6-2.csv"
    events: list[dict[str, str]] = []
    if args.skip_v5_run:
        if not merged_events_path.exists():
            raise FileNotFoundError(merged_events_path)
        with merged_events_path.open(newline="", encoding="utf-8") as fh:
            events = list(csv.DictReader(fh))
    else:
        for wings in sorted(groups):
            dates = groups[wings]
            print(f"\nRUN_WINGS=±{wings} sessions={len(dates)} dates={' '.join(dates)}")
            events.extend(run_v5_group(dates, wings, out / f"v5-pm{wings}"))
        event_fields = list(events[0].keys()) if events else []
        write_dict_csv(merged_events_path, events, event_fields)

    replay = discover_move_start_replay(args.move_start_replay)
    move_starts = load_move_starts(replay)
    matrix = make_matrix(events, inventory, move_starts)
    matrix_path = out / "expiry-aware-validation-matrix-v6-2.csv"
    matrix_rows = [asdict(r) for r in matrix]
    write_dict_csv(matrix_path, matrix_rows)

    order_rows = event_order_study(events, move_starts)
    order_path = out / "component-order-study-v6-2.csv"
    write_dict_csv(order_path, order_rows)

    summary = {
        "model": MODEL,
        "frozen_population": {"bullish": 18, "bearish": 18, "total": 36},
        "available_sessions": len(available),
        "unavailable_sessions": len(unavailable),
        "expiry_aware_rule": {
            "0_sessions_left": "ATM±1",
            "1_session_left": "ATM±2",
            "2_sessions_left": "ATM±3",
            "3_sessions_left": "ATM±4",
            "4_or_more_sessions_left": "ATM±5",
            "count_semantics": "Mon-Fri sessions strictly after session date through exact recorded expiry, inclusive",
        },
        "v5_logic_changed": False,
        "same_physical_strikes": True,
        "nearest_strike_fallback": False,
        "interpolation": False,
        "move_start_replay": str(replay) if replay else None,
        "group_counts": {f"pm{k}": len(v) for k, v in sorted(groups.items())},
        "component_order_study": order_rows,
        "artifacts": {
            "inventory_csv": str(inv_path),
            "merged_events_csv": str(merged_events_path),
            "matrix_csv": str(matrix_path),
            "component_order_csv": str(order_path),
        },
    }
    summary_path = out / "expiry-aware-validation-summary-v6-2.json"
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(f"\nmodel={MODEL} available_sessions={len(available)} events={len(events)} move_start_replay={replay or 'NONE'}")
    print("\n=== EARLIER SUGGESTED TEST: COMPONENT ORDER STUDY ===")
    for r in order_rows:
        if r["event_relation"] != "SAME_DIRECTION":
            continue
        print(
            f"{r['known_day_direction']} {r['component_order']}: events={r['events']} sessions={r['unique_sessions']} "
            f"median_lead_lag={r['median_lead_lag_minutes']} avg15={r['avg_move_15m']} med15={r['median_move_15m']} "
            f"avg30={r['avg_move_30m']} med30={r['median_move_30m']} hit15={r['positive_15m_rate_pct']}% hit30={r['positive_30m_rate_pct']}%"
        )
    print(f"INVENTORY_CSV: {inv_path}")
    print(f"EVENTS_CSV: {merged_events_path}")
    print(f"MATRIX_CSV: {matrix_path}")
    print(f"ORDER_STUDY_CSV: {order_path}")
    print(f"SUMMARY_JSON: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
