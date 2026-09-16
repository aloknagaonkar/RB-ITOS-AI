from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import IST
from .oi_vwap_causal_runtime_v1 import _directional_p1, _p2_persists, _vwap_aligned
from .oi_vwap_live_feature_engine_v1 import OICheckpointFeature, build_oi_checkpoint_feature
from .oi_vwap_live_futures_v1 import FuturesVWAPFeature, completed_futures_vwap
from .storage import Observation


@dataclass(frozen=True)
class ReplayEvent:
    session_date: str
    timestamp: str
    event_type: str
    status: str
    reason_code: str | None = None
    direction: str | None = None
    observation_id: int | None = None
    data: dict = field(default_factory=dict)


@dataclass
class ReplaySessionResult:
    session_date: str
    events: list[ReplayEvent] = field(default_factory=list)
    p1_count: int = 0
    wait_p2_count: int = 0
    p2_confirmed_count: int = 0
    p2_failed_count: int = 0
    vwap_reject_count: int = 0
    feature_block_count: int = 0


def _norm5(ts: datetime) -> datetime:
    ts = ts.astimezone(IST)
    minute = ts.minute - (ts.minute % 5)
    return ts.replace(minute=minute, second=0, microsecond=0)


def _obs_ts(obs: Observation) -> datetime:
    raw = obs.snapshot["received_at"]
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(IST)


def _checkpoint_observations(rows: list[Observation]) -> list[Observation]:
    """Use the first observation in each 5-minute bucket to avoid same-bucket lookahead."""
    out: list[Observation] = []
    seen = set()
    for row in sorted(rows, key=_obs_ts):
        key = _norm5(_obs_ts(row))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _feature(session: Session, *, config_id: int, observation: Observation) -> OICheckpointFeature:
    return build_oi_checkpoint_feature(
        session,
        config_id=config_id,
        observation_id=observation.id,
    )


def _previous_feature(
    session: Session,
    *,
    config_id: int,
    checkpoints: list[Observation],
    index: int,
) -> OICheckpointFeature | None:
    if index <= 0:
        return None
    try:
        return _feature(
            session,
            config_id=config_id,
            observation=checkpoints[index - 1],
        )
    except Exception:
        return None


def _historical_vwap(candles: Iterable, available_at: datetime) -> FuturesVWAPFeature | None:
    try:
        return completed_futures_vwap(list(candles), available_at=available_at)
    except Exception:
        return None


def replay_session(
    engine,
    *,
    config_id: int,
    session_date: str,
    futures_candles: Iterable,
) -> ReplaySessionResult:
    result = ReplaySessionResult(session_date=session_date)

    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(Observation)
                .where(
                    Observation.config_id == config_id,
                    Observation.session_date == session_date,
                )
                .order_by(Observation.id)
            ).all()
        )
        checkpoints = _checkpoint_observations(rows)
        waiting: tuple[str, str, int] | None = None

        for idx, obs in enumerate(checkpoints):
            ts = _obs_ts(obs)

            try:
                current = _feature(session, config_id=config_id, observation=obs)
            except Exception as exc:
                result.feature_block_count += 1
                result.events.append(
                    ReplayEvent(
                        session_date=session_date,
                        timestamp=ts.isoformat(),
                        event_type="FEATURE_BLOCKED",
                        status="FAIL",
                        reason_code=type(exc).__name__,
                        observation_id=obs.id,
                        data={"detail": str(exc)},
                    )
                )
                continue

            if waiting is not None:
                direction, p1_time, p1_obs = waiting
                expected = _norm5(
                    datetime.fromisoformat(p1_time.replace("Z", "+00:00"))
                ) + timedelta(minutes=5)
                current_cp = _norm5(
                    datetime.fromisoformat(current.timestamp.replace("Z", "+00:00"))
                )

                if current_cp < expected:
                    continue

                if current_cp > expected:
                    result.p2_failed_count += 1
                    result.events.append(
                        ReplayEvent(
                            session_date=session_date,
                            timestamp=current.timestamp,
                            event_type="P2_FAILED",
                            status="FAIL",
                            reason_code="P2_CHECKPOINT_MISSED",
                            direction=direction,
                            observation_id=current.observation_id,
                            data={"p1_observation_id": p1_obs},
                        )
                    )
                    waiting = None
                    continue

                if _p2_persists(direction, current):
                    result.p2_confirmed_count += 1
                    result.events.append(
                        ReplayEvent(
                            session_date=session_date,
                            timestamp=current.timestamp,
                            event_type="P2_CONFIRMED_RUNTIME",
                            status="PASS",
                            direction=direction,
                            observation_id=current.observation_id,
                            data={"p1_observation_id": p1_obs},
                        )
                    )
                else:
                    result.p2_failed_count += 1
                    result.events.append(
                        ReplayEvent(
                            session_date=session_date,
                            timestamp=current.timestamp,
                            event_type="P2_FAILED",
                            status="FAIL",
                            reason_code="P2_PERSISTENCE_FAILED",
                            direction=direction,
                            observation_id=current.observation_id,
                            data={"p1_observation_id": p1_obs},
                        )
                    )
                waiting = None
                continue

            previous = _previous_feature(
                session,
                config_id=config_id,
                checkpoints=checkpoints,
                index=idx,
            )
            direction, reason = _directional_p1(current, previous)

            if direction is None:
                result.events.append(
                    ReplayEvent(
                        session_date=session_date,
                        timestamp=current.timestamp,
                        event_type="P1_NOT_DETECTED",
                        status="SKIPPED",
                        reason_code=reason,
                        observation_id=current.observation_id,
                    )
                )
                continue

            result.p1_count += 1
            result.events.append(
                ReplayEvent(
                    session_date=session_date,
                    timestamp=current.timestamp,
                    event_type="P1_DETECTED",
                    status="PASS",
                    direction=direction,
                    observation_id=current.observation_id,
                )
            )

            vwap = _historical_vwap(futures_candles, ts)
            if vwap is None:
                result.feature_block_count += 1
                result.events.append(
                    ReplayEvent(
                        session_date=session_date,
                        timestamp=current.timestamp,
                        event_type="FUTURES_DATA_INVALID",
                        status="FAIL",
                        reason_code="FUTURES_VWAP_MISSING",
                        direction=direction,
                        observation_id=current.observation_id,
                    )
                )
                continue

            if not _vwap_aligned(direction, vwap.side):
                result.vwap_reject_count += 1
                result.events.append(
                    ReplayEvent(
                        session_date=session_date,
                        timestamp=current.timestamp,
                        event_type="VWAP_NOT_ALIGNED",
                        status="FAIL",
                        reason_code="VWAP_NOT_ALIGNED",
                        direction=direction,
                        observation_id=current.observation_id,
                        data={"vwap": asdict(vwap)},
                    )
                )
                continue

            result.wait_p2_count += 1
            waiting = (direction, current.timestamp, current.observation_id)
            result.events.append(
                ReplayEvent(
                    session_date=session_date,
                    timestamp=current.timestamp,
                    event_type="WAIT_P2",
                    status="WAITING",
                    direction=direction,
                    observation_id=current.observation_id,
                    data={"vwap": asdict(vwap)},
                )
            )

    return result


def summarize(results: list[ReplaySessionResult]) -> dict:
    return {
        "sessions": len(results),
        "p1_count": sum(r.p1_count for r in results),
        "wait_p2_count": sum(r.wait_p2_count for r in results),
        "p2_confirmed_count": sum(r.p2_confirmed_count for r in results),
        "p2_failed_count": sum(r.p2_failed_count for r in results),
        "vwap_reject_count": sum(r.vwap_reject_count for r in results),
        "feature_block_count": sum(r.feature_block_count for r in results),
    }
