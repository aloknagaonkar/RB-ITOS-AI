from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime, time, timedelta
from typing import Any

from .domain import IST
from .historical_replay_day_v1_1 import resolve_session_config_id
from .historical_replay_snapshot_index_v1 import HistoricalReplaySnapshotIndexV1
from .storage import make_engine

MODEL = "HISTORICAL_REPLAY_STRICT_READINESS_V1"
FIRST_CHECKPOINT = time(9, 20)
LAST_CHECKPOINT = time(15, 25)
STEP_MINUTES = 5
TOLERANCE_SECONDS = 30


def expected_checkpoints(session_date: date) -> list[datetime]:
    current = datetime.combine(session_date, FIRST_CHECKPOINT, IST)
    end = datetime.combine(session_date, LAST_CHECKPOINT, IST)
    rows = []
    while current <= end:
        rows.append(current)
        current += timedelta(minutes=STEP_MINUTES)
    return rows


def snapshot_checkpoint_coverage(session_date: date, *, engine=None) -> dict[str, Any]:
    engine = engine or make_engine()
    expected = expected_checkpoints(session_date)

    try:
        config_id = resolve_session_config_id(engine, session_date)
    except Exception as exc:
        return {
            "model": MODEL,
            "session_date": session_date.isoformat(),
            "config_id": None,
            "expected_checkpoint_count": len(expected),
            "covered_checkpoint_count": 0,
            "missing_checkpoint_count": len(expected),
            "coverage_complete": False,
            "first_missing_checkpoint": expected[0].isoformat() if expected else None,
            "missing_checkpoints": [x.isoformat() for x in expected],
            "reason": f"CONFIG_UNAVAILABLE: {type(exc).__name__}: {exc}",
        }

    index = HistoricalReplaySnapshotIndexV1.load(
        engine, config_id, session_date, tolerance_seconds=TOLERANCE_SECONDS
    )

    missing = []
    covered = 0
    tolerance = timedelta(seconds=TOLERANCE_SECONDS)

    for checkpoint in expected:
        i = bisect_left(index.times, checkpoint)
        if i >= len(index.times):
            missing.append(checkpoint.isoformat())
            continue
        delta = index.times[i] - checkpoint
        if delta < timedelta(0) or delta > tolerance:
            missing.append(checkpoint.isoformat())
            continue
        covered += 1

    return {
        "model": MODEL,
        "session_date": session_date.isoformat(),
        "config_id": config_id,
        "expected_checkpoint_count": len(expected),
        "covered_checkpoint_count": covered,
        "missing_checkpoint_count": len(missing),
        "coverage_complete": covered == len(expected),
        "first_missing_checkpoint": missing[0] if missing else None,
        "missing_checkpoints": missing,
        "raw_snapshot_count": index.raw_count,
        "tolerance_seconds": TOLERANCE_SECONDS,
        "reason": None if not missing else "MISSING_EXACT_5M_CHECKPOINT_SNAPSHOTS",
    }
