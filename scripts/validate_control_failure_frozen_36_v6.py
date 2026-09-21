from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

MODEL = "CONTROL_FAILURE_FROZEN_36_VALIDATION_V6"

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


def _f(v: Any) -> float | None:
    if v in (None, ""):
        return None
    return float(v)


def _minutes_between(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    ta = datetime.fromisoformat(a)
    # move-start artifacts sometimes carry HH:MM only.
    if "T" not in b:
        tb = datetime.fromisoformat(f"{ta.date().isoformat()}T{b}:00{ta.strftime('%z')[:3]}:{ta.strftime('%z')[3:]}")
    else:
        tb = datetime.fromisoformat(b)
    return (ta - tb).total_seconds() / 60.0


def _positioning_path(root: Path, ds: str) -> Path:
    return root / ds / "positioning.json"


def _expiry_from_positioning(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    sessions = doc.get("sessions") or []
    if len(sessions) != 1:
        return None
    expiry = sessions[0].get("expiry") or sessions[0].get("expiry_date")
    return str(expiry) if expiry else None


def resolve_expiry(ds: str, build_root: Path) -> tuple[str | None, str]:
    p = _positioning_path(build_root, ds)
    exp = _expiry_from_positioning(p)
    if exp:
        return exp, "POSITIONING_JSON"
    try:
        from market_lab.historical_oi_canonical_90_orchestrator_v1 import resolve_exact_expiry
        r = resolve_exact_expiry(ds, build_root=build_root)
    except Exception as exc:
        return None, f"RESOLVER_ERROR:{type(exc).__name__}"
    if r.get("status") == "RESOLVED":
        return str(r["expiry"]), str(r.get("source") or "RESOLVED")
    return None, str(r.get("status") or "UNRESOLVED")


def build_missing(ds: str, expiry: str) -> None:
    cmd = [
        sys.executable, "-m", "market_lab.historical_oi_build_job_v1",
        "--job-id", f"control-failure-v6-{ds.replace('-', '')}",
        "--session-date", ds,
        "--expiry", expiry,
    ]
    subprocess.run(cmd, check=True)


def dte(ds: str, expiry: str | None) -> int | None:
    if not expiry:
        return None
    return (date.fromisoformat(expiry) - date.fromisoformat(ds)).days


def discover_move_start_replay(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    roots = [Path("data/historical-evidence"), Path("data")]
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.json"):
            if p in seen or p.stat().st_size > 50_000_000:
                continue
            seen.add(p)
            name = p.name.lower()
            if "move" not in name and "trend" not in name and "replay" not in name:
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if doc.get("research_version") == "TREND_DAY_MOVE_START_OI_REPLAY_V1":
                candidates.append(p)
    if len(candidates) == 1:
        return candidates[0]
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
            # all modes/offsets repeat the same anchor; first is enough.
            out.setdefault(ds, str(ms))
    return out


def run_v5(dates: list[str], output_dir: Path, wings: int = 2) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "scripts/analyze_control_failure_historical_v5.py",
        "--dates", *dates,
        "--wings", str(wings),
        "--output-dir", str(output_dir),
    ]
    subprocess.run(cmd, check=True)
    p = output_dir / "control-failure-events-v5.csv"
    if not p.exists():
        raise FileNotFoundError(p)
    return p


def read_events(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def directional_hit(row: dict[str, str], minutes: int) -> bool | None:
    v = _f(row.get(f"move_{minutes}m"))
    if v is None:
        return None
    return v > 0


@dataclass
class ValidationRow:
    session_date: str
    known_direction: str
    expiry: str | None
    dte: int | None
    pm2_rule_status: str
    event_count: int
    same_direction_count: int
    opposite_direction_count: int
    first_same_direction_checkpoint: str | None
    first_same_direction_order: str | None
    first_same_direction_atm_state: str | None
    first_same_direction_bullish_strikes: int | None
    first_same_direction_bearish_strikes: int | None
    first_same_direction_imbalance: float | None
    first_same_direction_velocity: float | None
    first_same_direction_acceleration: float | None
    first_same_direction_move_5m: float | None
    first_same_direction_move_10m: float | None
    first_same_direction_move_15m: float | None
    first_same_direction_move_30m: float | None
    retrospective_move_start: str | None
    lead_lag_minutes: float | None


def make_matrix(events: list[dict[str, str]], expiry_by_date: dict[str, str | None], move_starts: dict[str, str]) -> list[ValidationRow]:
    by_date: dict[str, list[dict[str, str]]] = {d: [] for d in ALL_DATES}
    for e in events:
        ds = e.get("session_date")
        if ds in by_date:
            by_date[ds].append(e)

    rows: list[ValidationRow] = []
    for ds in ALL_DATES:
        day = sorted(by_date[ds], key=lambda r: r.get("detected_checkpoint") or "")
        known = CLASS_BY_DATE[ds]
        same = [r for r in day if r.get("direction") == known]
        opp = [r for r in day if r.get("direction") != known]
        first = same[0] if same else None
        expiry = expiry_by_date.get(ds)
        dd = dte(ds, expiry)
        status = "STRICT_D1_PM2" if dd == 1 else ("EXPLORATORY_PM2_NON_D1" if dd is not None else "EXPIRY_UNKNOWN")
        move_start = move_starts.get(ds)
        checkpoint = first.get("detected_checkpoint") if first else None
        rows.append(ValidationRow(
            session_date=ds,
            known_direction=known,
            expiry=expiry,
            dte=dd,
            pm2_rule_status=status,
            event_count=len(day),
            same_direction_count=len(same),
            opposite_direction_count=len(opp),
            first_same_direction_checkpoint=checkpoint,
            first_same_direction_order=first.get("component_order") if first else None,
            first_same_direction_atm_state=first.get("atm_state") if first else None,
            first_same_direction_bullish_strikes=int(first["bullish_strikes"]) if first and first.get("bullish_strikes") else None,
            first_same_direction_bearish_strikes=int(first["bearish_strikes"]) if first and first.get("bearish_strikes") else None,
            first_same_direction_imbalance=_f(first.get("imbalance")) if first else None,
            first_same_direction_velocity=_f(first.get("imbalance_velocity")) if first else None,
            first_same_direction_acceleration=_f(first.get("imbalance_acceleration")) if first else None,
            first_same_direction_move_5m=_f(first.get("move_5m")) if first else None,
            first_same_direction_move_10m=_f(first.get("move_10m")) if first else None,
            first_same_direction_move_15m=_f(first.get("move_15m")) if first else None,
            first_same_direction_move_30m=_f(first.get("move_30m")) if first else None,
            retrospective_move_start=move_start,
            lead_lag_minutes=_minutes_between(checkpoint, move_start) if checkpoint and move_start else None,
        ))
    return rows


def _avg(vals: list[float | None]) -> float | None:
    xs = [x for x in vals if x is not None]
    return sum(xs) / len(xs) if xs else None


def summarize(matrix: list[ValidationRow]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for scope, subset in [
        ("ALL_36_PM2_EXPLORATORY", matrix),
        ("STRICT_D1_PM2_ONLY", [r for r in matrix if r.dte == 1]),
    ]:
        by_dir: dict[str, Any] = {}
        for direction in ("BULLISH", "BEARISH"):
            rows = [r for r in subset if r.known_direction == direction]
            detected = [r for r in rows if r.first_same_direction_checkpoint]
            with_anchor = [r for r in detected if r.lead_lag_minutes is not None]
            by_dir[direction] = {
                "sessions": len(rows),
                "sessions_with_same_direction_event": len(detected),
                "detection_rate_pct": (len(detected) / len(rows) * 100.0) if rows else None,
                "sessions_with_opposite_events": sum(r.opposite_direction_count > 0 for r in rows),
                "avg_opposite_event_count": _avg([float(r.opposite_direction_count) for r in rows]),
                "first_event_order_counts": dict(Counter(r.first_same_direction_order for r in detected)),
                "avg_first_move_5m": _avg([r.first_same_direction_move_5m for r in detected]),
                "avg_first_move_10m": _avg([r.first_same_direction_move_10m for r in detected]),
                "avg_first_move_15m": _avg([r.first_same_direction_move_15m for r in detected]),
                "avg_first_move_30m": _avg([r.first_same_direction_move_30m for r in detected]),
                "move_start_anchor_available": len(with_anchor),
                "signal_at_or_before_move_start": sum((r.lead_lag_minutes or 999999) <= 0 for r in with_anchor),
                "signal_within_5m_after_move_start": sum(0 < (r.lead_lag_minutes or -999999) <= 5 for r in with_anchor),
                "signal_within_10m_after_move_start": sum(5 < (r.lead_lag_minutes or -999999) <= 10 for r in with_anchor),
                "signal_within_15m_after_move_start": sum(10 < (r.lead_lag_minutes or -999999) <= 15 for r in with_anchor),
                "avg_lead_lag_minutes": _avg([r.lead_lag_minutes for r in with_anchor]),
            }
        out[scope] = by_dir
    return out


def write_csv(path: Path, rows: list[ValidationRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(rows[0]).keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-root", default="data/historical-evidence/historical-oi-build")
    ap.add_argument("--output-dir", default="data/historical-evidence/control-failure-frozen-36-v6")
    ap.add_argument("--move-start-replay")
    ap.add_argument("--build-missing", action="store_true", help="Build missing positioning.json only when exact expiry can be resolved from existing evidence/cache.")
    ap.add_argument("--skip-v5-run", action="store_true", help="Reuse existing events CSV in output-dir.")
    args = ap.parse_args()

    build_root = Path(args.build_root)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    inventory: list[dict[str, Any]] = []
    expiry_by_date: dict[str, str | None] = {}
    runnable: list[str] = []

    for ds in ALL_DATES:
        p = _positioning_path(build_root, ds)
        expiry, source = resolve_expiry(ds, build_root)
        if args.build_missing and not p.exists() and expiry:
            build_missing(ds, expiry)
        exists = p.exists()
        if exists:
            # Prefer exact expiry recorded by the resulting build.
            expiry = _expiry_from_positioning(p) or expiry
        expiry_by_date[ds] = expiry
        dd = dte(ds, expiry)
        inventory.append({
            "session_date": ds,
            "known_direction": CLASS_BY_DATE[ds],
            "positioning_exists": exists,
            "expiry": expiry,
            "expiry_source": source,
            "dte": dd,
            "pm2_rule_status": "STRICT_D1_PM2" if dd == 1 else ("EXPLORATORY_PM2_NON_D1" if dd is not None else "EXPIRY_UNKNOWN"),
        })
        if exists:
            runnable.append(ds)

    inv_path = out / "frozen-36-inventory-v6.csv"
    with inv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(inventory[0].keys()))
        w.writeheader(); w.writerows(inventory)

    missing = [r["session_date"] for r in inventory if not r["positioning_exists"]]
    if missing:
        print(f"MISSING_POSITIONING_COUNT={len(missing)} dates={' '.join(missing)}")
        print(f"INVENTORY_CSV: {inv_path}")
        print("Safe-stop: full 36 validation requires positioning.json for every frozen date.")
        return 2

    events_path = out / "v5" / "control-failure-events-v5.csv"
    if not args.skip_v5_run:
        events_path = run_v5(ALL_DATES, out / "v5", wings=2)
    elif not events_path.exists():
        raise FileNotFoundError(events_path)

    events = read_events(events_path)
    replay = discover_move_start_replay(args.move_start_replay)
    move_starts = load_move_starts(replay)
    matrix = make_matrix(events, expiry_by_date, move_starts)
    matrix_path = out / "frozen-36-validation-matrix-v6.csv"
    write_csv(matrix_path, matrix)

    summary = {
        "model": MODEL,
        "frozen_population": {"bullish": len(BULLISH_DATES), "bearish": len(BEARISH_DATES), "total": len(ALL_DATES)},
        "methodology": {
            "v5_logic_changed": False,
            "v5_wings": 2,
            "pm2_interpretation": "STRICT only when DTE=1 per current expiry-aware rule; non-D1 rows retained as exploratory comparability view.",
            "same_physical_strikes": True,
            "nearest_strike_fallback": False,
            "interpolation": False,
            "move_start_anchor": "TREND_DAY_MOVE_START_OI_REPLAY_V1 retrospective price-only anchor when discoverable/provided",
        },
        "move_start_replay": str(replay) if replay else None,
        "summary": summarize(matrix),
        "artifacts": {
            "inventory_csv": str(inv_path),
            "v5_events_csv": str(events_path),
            "matrix_csv": str(matrix_path),
        },
    }
    summary_path = out / "frozen-36-validation-summary-v6.json"
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(f"model={MODEL} sessions={len(matrix)} move_start_replay={replay or 'NONE'}")
    for scope, block in summary["summary"].items():
        print(f"\n=== {scope} ===")
        for direction, s in block.items():
            print(
                f"{direction}: sessions={s['sessions']} detected={s['sessions_with_same_direction_event']} "
                f"rate={s['detection_rate_pct']}% opposite_sessions={s['sessions_with_opposite_events']} "
                f"avg+5={s['avg_first_move_5m']} avg+10={s['avg_first_move_10m']} "
                f"avg+15={s['avg_first_move_15m']} avg+30={s['avg_first_move_30m']} "
                f"orders={s['first_event_order_counts']} avg_lead_lag={s['avg_lead_lag_minutes']}"
            )
    print(f"INVENTORY_CSV: {inv_path}")
    print(f"MATRIX_CSV: {matrix_path}")
    print(f"SUMMARY_JSON: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
