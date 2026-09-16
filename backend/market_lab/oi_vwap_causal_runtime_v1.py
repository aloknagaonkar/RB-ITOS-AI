
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import IST, PCRConfig
from .oi_vwap_live_feature_engine_v1 import OICheckpointFeature, build_oi_checkpoint_feature
from .paper_futures_health_v1 import validate_futures_vwap_health
from .paper_market_guard_v1 import validate_option_expiry
from .paper_production_storage_v1 import (
    PaperSignal,
    get_or_create_waiting_signal,
    record_event,
    reject_waiting_signal,
    update_paper_health,
)
from .storage import Configuration, Observation
from .upstox_live_futures_v1 import UpstoxLiveFuturesGatewayV1


RUNTIME_VERSION = "OI_VWAP_CAUSAL_RUNTIME_V1"
STRATEGY_VERSION = "1.0.0"


@dataclass(frozen=True)
class RuntimeDecision:
    status: str
    reason_code: str | None
    observation_id: int
    checkpoint_time: str | None
    signal_id: int | None
    direction: str | None
    paper_entry_allowed: bool
    evidence: dict


def _latest_waiting_signal(session: Session, session_date: str) -> PaperSignal | None:
    return session.scalar(
        select(PaperSignal)
        .where(
            PaperSignal.session_date == session_date,
            PaperSignal.status == "WAIT_P2",
        )
        .order_by(PaperSignal.id.desc())
        .limit(1)
    )


def _previous_checkpoint_feature(
    session: Session,
    *,
    config_id: int,
    current: OICheckpointFeature,
) -> OICheckpointFeature | None:
    current_ts = datetime.fromisoformat(current.timestamp.replace("Z", "+00:00")).astimezone(IST)
    previous_target = current_ts - timedelta(minutes=5)

    rows = list(
        session.scalars(
            select(Observation)
            .where(
                Observation.config_id == config_id,
                Observation.session_date == current.session_date,
            )
            .order_by(Observation.id)
        ).all()
    )

    best = None
    for row in rows:
        try:
            ts = datetime.fromisoformat(
                row.snapshot["received_at"].replace("Z", "+00:00")
            ).astimezone(IST)
        except Exception:
            continue
        delta = abs((ts - previous_target).total_seconds())
        if delta <= 120:
            candidate = (delta, row.id)
            if best is None or candidate < best[:2]:
                best = (delta, row.id, row)

    if best is None:
        return None
    try:
        return build_oi_checkpoint_feature(
            session,
            config_id=config_id,
            observation_id=best[2].id,
        )
    except Exception:
        return None


def _directional_p1(
    current: OICheckpointFeature,
    previous: OICheckpointFeature | None,
) -> tuple[str | None, str | None]:
    if previous is None:
        return None, "PREVIOUS_5M_FEATURE_UNAVAILABLE"
    if current.pcr_change_5m is None:
        return None, "PCR_CHANGE_UNAVAILABLE"
    if current.previous_session_imbalance is None:
        return None, "PREVIOUS_SESSION_IMBALANCE_UNAVAILABLE"

    bull = (
        previous.imbalance_5m <= 0
        and current.imbalance_5m > 0
        and current.pcr_change_5m > 0
        and current.session_imbalance > current.previous_session_imbalance
    )
    bear = (
        previous.imbalance_5m >= 0
        and current.imbalance_5m < 0
        and current.pcr_change_5m < 0
        and current.session_imbalance < current.previous_session_imbalance
    )

    if bull:
        return "BULLISH", None
    if bear:
        return "BEARISH", None
    return None, "NO_FRESH_P1"


def _p2_persists(direction: str, current: OICheckpointFeature) -> bool:
    if current.pcr_change_5m is None:
        return False
    if direction == "BULLISH":
        return current.imbalance_5m > 0 and current.pcr_change_5m > 0
    if direction == "BEARISH":
        return current.imbalance_5m < 0 and current.pcr_change_5m < 0
    return False


def _vwap_aligned(direction: str, side: str) -> bool:
    return (
        (direction == "BULLISH" and side == "ABOVE")
        or (direction == "BEARISH" and side == "BELOW")
    )


def evaluate_checkpoint(
    engine,
    *,
    config_id: int,
    observation_id: int,
    futures_gateway: UpstoxLiveFuturesGatewayV1,
    now: datetime | None = None,
) -> RuntimeDecision:
    now = now or datetime.now(IST)

    with Session(engine) as session, session.begin():
        config_row = session.get(Configuration, config_id)
        if config_row is None:
            return RuntimeDecision(
                "BLOCKED", "CONFIGURATION_NOT_FOUND", observation_id, None,
                None, None, False, {}
            )

        config = PCRConfig.model_validate(config_row.payload)
        expiry_guard = validate_option_expiry(config, today=now.astimezone(IST).date())
        if not expiry_guard.ok:
            record_event(
                session,
                event_type="MARKET_CONFIGURATION_INVALID",
                stage="GUARD",
                status="FAIL",
                reason_code=expiry_guard.reason_code,
                observation_id=observation_id,
                output_data=asdict(expiry_guard),
            )
            return RuntimeDecision(
                "BLOCKED", expiry_guard.reason_code, observation_id, None,
                None, None, False, {"expiry_guard": asdict(expiry_guard)}
            )

        try:
            current = build_oi_checkpoint_feature(
                session,
                config_id=config_id,
                observation_id=observation_id,
            )
        except Exception as exc:
            record_event(
                session,
                event_type="OI_FEATURE_FAILED",
                stage="FEATURES",
                status="FAIL",
                reason_code=type(exc).__name__,
                observation_id=observation_id,
                output_data={"detail": str(exc)},
            )
            return RuntimeDecision(
                "BLOCKED", "OI_FEATURE_FAILED", observation_id, None,
                None, None, False, {"detail": str(exc)}
            )

        waiting = _latest_waiting_signal(session, current.session_date)

        # If there is a waiting setup, the next completed checkpoint is P2.
        if waiting is not None:
            if waiting.p1_observation_id == current.observation_id:
                return RuntimeDecision(
                    "WAIT_P2",
                    None,
                    observation_id,
                    current.timestamp,
                    waiting.id,
                    waiting.direction,
                    False,
                    {"oi": asdict(current)},
                )

            persists = _p2_persists(waiting.direction, current)
            if not persists:
                reject_waiting_signal(
                    session,
                    waiting,
                    p2_observation_id=current.observation_id,
                    p2_time=current.timestamp,
                    reason_code="P2_PERSISTENCE_FAILED",
                    evidence_update={"p2": asdict(current)},
                )
                record_event(
                    session,
                    signal_id=waiting.id,
                    session_date=current.session_date,
                    observation_id=current.observation_id,
                    event_type="P2_FAILED",
                    stage="P2",
                    status="FAIL",
                    reason_code="P2_PERSISTENCE_FAILED",
                    output_data={"oi": asdict(current)},
                )
                return RuntimeDecision(
                    "REJECTED",
                    "P2_PERSISTENCE_FAILED",
                    observation_id,
                    current.timestamp,
                    waiting.id,
                    waiting.direction,
                    False,
                    {"oi": asdict(current)},
                )

            record_event(
                session,
                signal_id=waiting.id,
                session_date=current.session_date,
                observation_id=current.observation_id,
                event_type="P2_CONFIRMED_RUNTIME",
                stage="P2",
                status="PASS",
                output_data={"oi": asdict(current)},
            )
            return RuntimeDecision(
                "P2_CONFIRMED",
                None,
                observation_id,
                current.timestamp,
                waiting.id,
                waiting.direction,
                True,
                {"oi": asdict(current)},
            )

        previous = _previous_checkpoint_feature(
            session,
            config_id=config_id,
            current=current,
        )
        direction, p1_reason = _directional_p1(current, previous)
        if direction is None:
            record_event(
                session,
                event_type="P1_NOT_DETECTED",
                stage="P1",
                status="SKIPPED",
                reason_code=p1_reason,
                observation_id=current.observation_id,
                session_date=current.session_date,
                output_data={
                    "oi": asdict(current),
                    "previous_oi": None if previous is None else asdict(previous),
                },
            )
            return RuntimeDecision(
                "NO_SIGNAL",
                p1_reason,
                observation_id,
                current.timestamp,
                None,
                None,
                False,
                {"oi": asdict(current)},
            )

        try:
            _, vwap = futures_gateway.latest_completed_vwap(available_at=now)
        except Exception as exc:
            record_event(
                session,
                event_type="FUTURES_VWAP_FAILED",
                stage="VWAP",
                status="FAIL",
                reason_code="FUTURES_VWAP_FETCH_FAILED",
                observation_id=current.observation_id,
                session_date=current.session_date,
                output_data={"detail": str(exc)},
            )
            return RuntimeDecision(
                "BLOCKED",
                "FUTURES_VWAP_FETCH_FAILED",
                observation_id,
                current.timestamp,
                None,
                direction,
                False,
                {"oi": asdict(current), "detail": str(exc)},
            )

        health = validate_futures_vwap_health(vwap, now=now)
        if not health.ok:
            record_event(
                session,
                event_type="FUTURES_DATA_INVALID",
                stage="VWAP",
                status="FAIL",
                reason_code=health.reason_code,
                observation_id=current.observation_id,
                session_date=current.session_date,
                output_data={"health": asdict(health), "vwap": asdict(vwap)},
            )
            return RuntimeDecision(
                "BLOCKED",
                health.reason_code,
                observation_id,
                current.timestamp,
                None,
                direction,
                False,
                {"oi": asdict(current), "vwap": asdict(vwap)},
            )

        if not _vwap_aligned(direction, vwap.side):
            record_event(
                session,
                event_type="VWAP_NOT_ALIGNED",
                stage="VWAP",
                status="FAIL",
                reason_code="VWAP_NOT_ALIGNED",
                observation_id=current.observation_id,
                session_date=current.session_date,
                output_data={"direction": direction, "vwap": asdict(vwap)},
            )
            return RuntimeDecision(
                "REJECTED",
                "VWAP_NOT_ALIGNED",
                observation_id,
                current.timestamp,
                None,
                direction,
                False,
                {"oi": asdict(current), "vwap": asdict(vwap)},
            )

        signal = get_or_create_waiting_signal(
            session,
            strategy_version=STRATEGY_VERSION,
            session_date=current.session_date,
            direction=direction,
            option_type="CE" if direction == "BULLISH" else "PE",
            p1_observation_id=current.observation_id,
            p1_time=current.timestamp,
            evidence={
                "runtime_version": RUNTIME_VERSION,
                "p1": asdict(current),
                "vwap": asdict(vwap),
                "futures_health": asdict(health),
            },
        )

        record_event(
            session,
            signal_id=signal.id,
            session_date=current.session_date,
            observation_id=current.observation_id,
            event_type="WAIT_P2",
            stage="STATE",
            status="WAITING",
            output_data={"direction": direction},
        )

        return RuntimeDecision(
            "WAIT_P2",
            None,
            observation_id,
            current.timestamp,
            signal.id,
            direction,
            False,
            {"oi": asdict(current), "vwap": asdict(vwap)},
        )


def publish_runtime_health(engine, decision: RuntimeDecision) -> None:
    update_paper_health(
        engine,
        runtime_version=RUNTIME_VERSION,
        strategy_runtime_state=decision.status,
        strategy_runtime_reason=decision.reason_code,
        strategy_runtime_observation_id=decision.observation_id,
        strategy_runtime_checkpoint_time=decision.checkpoint_time,
        strategy_runtime_signal_id=decision.signal_id,
        strategy_runtime_direction=decision.direction,
        paper_entry_allowed=decision.paper_entry_allowed,
    )
