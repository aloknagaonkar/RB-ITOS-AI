
from __future__ import annotations

"""
P2C.1 runtime guard helpers.

These helpers are intentionally small and additive so the production runtime can
distinguish expected market-session prerequisites from generic feature failures.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import IST
from .paper_production_storage_v1 import PaperControl
from .storage import Observation


SESSION_BASELINE_UNAVAILABLE = "SESSION_BASELINE_UNAVAILABLE"
CHECKPOINT_ALREADY_PROCESSED = "CHECKPOINT_ALREADY_PROCESSED"
P2_CHECKPOINT_MISSED = "P2_CHECKPOINT_MISSED"


def classify_oi_feature_error(error: Exception) -> str:
    detail = str(error)
    if "09:20 session baseline unavailable" in detail:
        return SESSION_BASELINE_UNAVAILABLE
    return "OI_FEATURE_FAILED"


def authoritative_paper_control(session: Session) -> dict:
    row = session.get(PaperControl, 1)
    if row is None:
        return {
            "paper_enabled": False,
            "live_execution_enabled": False,
            "max_open_positions": 4,
        }
    return {
        "paper_enabled": bool(row.enabled),
        # V1 invariant: live remains off even if DB payload was corrupted.
        "live_execution_enabled": False,
        "max_open_positions": int(row.max_open_positions),
    }


def checkpoint_key_from_received_at(received_at: str) -> str:
    ts = datetime.fromisoformat(received_at.replace("Z", "+00:00")).astimezone(IST)
    minute = ts.minute - (ts.minute % 5)
    return ts.replace(minute=minute, second=0, microsecond=0).isoformat()


def latest_observation_checkpoint_key(
    session: Session,
    *,
    config_id: int,
) -> tuple[int, str] | None:
    row = session.scalar(
        select(Observation)
        .where(Observation.config_id == config_id)
        .order_by(Observation.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    return row.id, checkpoint_key_from_received_at(row.snapshot["received_at"])


def waiting_signal_expected_p2_time(p1_time: str) -> datetime:
    p1 = datetime.fromisoformat(p1_time.replace("Z", "+00:00")).astimezone(IST)
    from datetime import timedelta
    return p1 + timedelta(minutes=5)


def classify_p2_checkpoint(*, p1_time: str, current_time: str) -> str:
    expected = waiting_signal_expected_p2_time(p1_time)
    current = datetime.fromisoformat(current_time.replace("Z", "+00:00")).astimezone(IST)

    # Compare normalized 5-minute checkpoint labels.
    def norm(ts):
        m = ts.minute - (ts.minute % 5)
        return ts.replace(minute=m, second=0, microsecond=0)

    expected = norm(expected)
    current = norm(current)
    if current == expected:
        return "EXPECTED_P2"
    if current < expected:
        return "TOO_EARLY"
    return P2_CHECKPOINT_MISSED
