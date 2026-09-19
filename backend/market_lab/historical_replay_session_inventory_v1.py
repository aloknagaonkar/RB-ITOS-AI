from __future__ import annotations
from bisect import bisect_left
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.orm import Session
from .historical_replay_data_v1 import readiness as base_readiness
from .historical_replay_day_v1_1 import resolve_session_config_id
from .historical_replay_snapshot_index_v1 import HistoricalReplaySnapshotIndexV1
from .storage import Observation, make_engine

MODEL = "HISTORICAL_REPLAY_SESSION_INVENTORY_V1"
IST = ZoneInfo("Asia/Kolkata")

def expected_checkpoints(d: date):
    x = datetime.combine(d, time(9,20), tzinfo=IST)
    end = datetime.combine(d, time(15,25), tzinfo=IST)
    out = []
    while x <= end:
        out.append(x)
        x += timedelta(minutes=5)
    return out

def coverage(times, d, tolerance_seconds: int):
    tol = timedelta(seconds=tolerance_seconds)
    n = 0
    for cp in expected_checkpoints(d):
        i = bisect_left(times, cp)
        if i < len(times) and timedelta(0) <= times[i] - cp <= tol:
            n += 1
    return n

def _dir_dates(root):
    p = Path(root)
    out = set()
    if not p.exists():
        return out
    for child in p.iterdir():
        if child.is_dir():
            try:
                out.add(date.fromisoformat(child.name))
            except ValueError:
                pass
    return out

def build_inventory(engine=None):
    engine = engine or make_engine()
    with Session(engine) as session:
        values = session.scalars(select(Observation.session_date).distinct()).all()
    dates = set()
    for value in values:
        try:
            dates.add(date.fromisoformat(str(value)))
        except ValueError:
            pass
    dates |= _dir_dates("data/live-observation/replay-cache")
    dates |= _dir_dates("data/live-observation/replay")

    rows = []
    for d in sorted(dates, reverse=True):
        config_id = None
        raw = strict = legacy = 0
        reason = None
        try:
            config_id = resolve_session_config_id(engine, d)
            index = HistoricalReplaySnapshotIndexV1.load(engine, config_id, d, tolerance_seconds=30)
            raw = index.raw_count
            strict = coverage(index.times, d, 30)
            legacy = coverage(index.times, d, 65)
        except RuntimeError as exc:
            reason = str(exc)

        futures = "UNKNOWN"
        try:
            value = base_readiness(d, engine=engine)
            for item in value.get("datasets") or []:
                if str(item.get("name") or "").upper() == "NIFTY_FUTURES_1M":
                    futures = str(item.get("status") or "UNKNOWN").upper()
        except Exception:
            pass

        if raw == 0:
            classification = "UNAVAILABLE"
        elif strict == 74:
            classification = "STRICT_READY"
        elif legacy == 74:
            classification = "LEGACY_COMPATIBLE"
        else:
            classification = "PARTIAL"

        rows.append({
            "session_date": d.isoformat(),
            "classification": classification,
            "config_id": config_id,
            "snapshot_records": raw,
            "strict_covered": strict,
            "legacy_covered": legacy,
            "expected_checkpoints": 74,
            "futures_status": futures,
            "strict_replay_possible": strict == 74 and futures == "AVAILABLE",
            "legacy_replay_candidate": legacy == 74 and strict < 74,
            "reason": reason,
        })

    counts = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    return {
        "model": MODEL,
        "strict_tolerance_seconds": 30,
        "legacy_tolerance_seconds": 65,
        "counts": counts,
        "rows": rows,
    }
