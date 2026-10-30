
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from filelock import FileLock
from sqlalchemy import Boolean, Float, Integer, JSON, String, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .storage import Base

PAPER_ENGINE_VERSION = "paper-prod-foundation-1.0.0"
PAPER_STRATEGY_NAME = "OI_VWAP_PERSISTENCE_OPTION_BUYING_V1"
MAX_OPEN_POSITIONS = 4
MAX_HOLDING_MINUTES = None
LIVE_TRADING_ENABLED = False

PAPER_EXECUTOR_LOCK = Path("data/paper-executor.lock")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaperControl(Base):
    __tablename__ = "paper_control"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    live_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=MAX_OPEN_POSITIONS)
    updated_at: Mapped[str] = mapped_column(String)


class PaperSignal(Base):
    __tablename__ = "paper_signals"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_paper_signal_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), index=True)
    strategy_name: Mapped[str] = mapped_column(String(100), index=True)
    strategy_version: Mapped[str] = mapped_column(String(64))
    session_date: Mapped[str] = mapped_column(String(10), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    option_type: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(32), index=True)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    p1_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    p2_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    p1_time: Mapped[str | None] = mapped_column(String, nullable=True)
    p2_time: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint("signal_id", name="uq_paper_position_signal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(Integer, index=True)
    strategy_name: Mapped[str] = mapped_column(String(100), index=True)
    session_date: Mapped[str] = mapped_column(String(10), index=True)

    direction: Mapped[str] = mapped_column(String(16))
    option_type: Mapped[str] = mapped_column(String(4))
    instrument_key: Mapped[str] = mapped_column(String(160), index=True)
    expiry: Mapped[str] = mapped_column(String(10), index=True)
    strike: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer)

    entry_time: Mapped[str] = mapped_column(String)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_fill_basis: Mapped[str] = mapped_column(String(16), default="ASK")
    entry_quote_timestamp: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String(16), index=True, default="OPEN")

    hard_stop_pct: Mapped[float] = mapped_column(Float, default=5.0)
    breakeven_activation_pct: Mapped[float] = mapped_column(Float, default=5.0)
    trail_activation_pct: Mapped[float] = mapped_column(Float, default=10.0)
    trail_distance_pct: Mapped[float] = mapped_column(Float, default=3.0)

    breakeven_active: Mapped[bool] = mapped_column(Boolean, default=False)
    trailing_active: Mapped[bool] = mapped_column(Boolean, default=False)
    best_price: Mapped[float] = mapped_column(Float)
    current_stop: Mapped[float] = mapped_column(Float)

    last_mark_time: Mapped[str | None] = mapped_column(String, nullable=True)
    last_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_ltp: Mapped[float | None] = mapped_column(Float, nullable=True)

    exit_time: Mapped[str | None] = mapped_column(String, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_fill_basis: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)


class PaperEvent(Base):
    __tablename__ = "paper_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    session_date: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    event_time: Mapped[str] = mapped_column(String, index=True)

    event_type: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

    observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    input_data: Mapped[dict] = mapped_column(JSON, default=dict)
    output_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String)


class PaperHealth(Base):
    __tablename__ = "paper_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


def ensure_paper_schema(engine) -> None:
    Base.metadata.create_all(
        engine,
        tables=[
            PaperControl.__table__,
            PaperSignal.__table__,
            PaperPosition.__table__,
            PaperEvent.__table__,
            PaperHealth.__table__,
        ],
    )
    with Session(engine) as session, session.begin():
        row = session.get(PaperControl, 1)
        if row is None:
            session.add(
                PaperControl(
                    id=1,
                    enabled=False,
                    live_enabled=False,
                    max_open_positions=MAX_OPEN_POSITIONS,
                    updated_at=utc_now(),
                )
            )
        else:
            # Production invariant: V1 can never turn on real broker execution.
            if row.live_enabled:
                row.live_enabled = False
                row.updated_at = utc_now()
            if row.max_open_positions != MAX_OPEN_POSITIONS:
                row.max_open_positions = MAX_OPEN_POSITIONS
                row.updated_at = utc_now()


def set_paper_enabled(engine, enabled: bool) -> dict:
    ensure_paper_schema(engine)
    with Session(engine) as session, session.begin():
        control = session.get(PaperControl, 1)
        control.enabled = bool(enabled)
        control.live_enabled = False
        control.max_open_positions = MAX_OPEN_POSITIONS
        control.updated_at = utc_now()
        record_event(
            session,
            event_type="PAPER_CONTROL_CHANGED",
            stage="CONTROL",
            status="PASS",
            reason_code="PAPER_ENABLED" if enabled else "PAPER_DISABLED",
            output_data={"enabled": bool(enabled), "live_enabled": False},
        )
        return paper_control_dict(control)


def paper_control_dict(control: PaperControl) -> dict:
    return {
        "enabled": bool(control.enabled),
        "live_enabled": False,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "max_holding_minutes": None,
        "updated_at": control.updated_at,
    }


def get_paper_control(session: Session) -> dict:
    control = session.get(PaperControl, 1)
    if control is None:
        raise RuntimeError("paper schema is not initialized")
    return paper_control_dict(control)


def record_event(
    session: Session,
    *,
    event_type: str,
    stage: str,
    status: str,
    reason_code: str | None = None,
    signal_id: int | None = None,
    position_id: int | None = None,
    session_date: str | None = None,
    observation_id: int | None = None,
    input_data: dict | None = None,
    output_data: dict | None = None,
    event_time: str | None = None,
) -> PaperEvent:
    event = PaperEvent(
        signal_id=signal_id,
        position_id=position_id,
        session_date=session_date,
        event_time=event_time or utc_now(),
        event_type=event_type,
        stage=stage,
        status=status,
        reason_code=reason_code,
        observation_id=observation_id,
        input_data=input_data or {},
        output_data=output_data or {},
        created_at=utc_now(),
    )
    session.add(event)
    session.flush()
    return event


def make_signal_dedupe_key(
    *,
    strategy_version: str,
    session_date: str,
    direction: str,
    p1_observation_id: int,
    p2_observation_id: int | None,
) -> str:
    return (
        f"{strategy_version}|{session_date}|{direction}|"
        f"p1={p1_observation_id}|p2={p2_observation_id if p2_observation_id is not None else 'WAIT'}"
    )


def get_or_create_waiting_signal(
    session: Session,
    *,
    strategy_version: str,
    session_date: str,
    direction: str,
    option_type: str,
    p1_observation_id: int,
    p1_time: str,
    evidence: dict,
) -> PaperSignal:
    key = make_signal_dedupe_key(
        strategy_version=strategy_version,
        session_date=session_date,
        direction=direction,
        p1_observation_id=p1_observation_id,
        p2_observation_id=None,
    )
    existing = session.scalar(select(PaperSignal).where(PaperSignal.dedupe_key == key).limit(1))
    if existing is not None:
        return existing

    now = utc_now()
    signal = PaperSignal(
        dedupe_key=key,
        strategy_name=PAPER_STRATEGY_NAME,
        strategy_version=strategy_version,
        session_date=session_date,
        direction=direction,
        option_type=option_type,
        status="WAIT_P2",
        reason_code=None,
        p1_observation_id=p1_observation_id,
        p2_observation_id=None,
        p1_time=p1_time,
        p2_time=None,
        evidence=evidence,
        created_at=now,
        updated_at=now,
    )
    session.add(signal)
    session.flush()
    record_event(
        session,
        signal_id=signal.id,
        session_date=session_date,
        observation_id=p1_observation_id,
        event_type="P1_VWAP_ALIGNED",
        stage="P1",
        status="PASS",
        output_data={"next": "WAIT_P2"},
    )
    return signal


def reject_waiting_signal(
    session: Session,
    signal: PaperSignal,
    *,
    p2_observation_id: int | None,
    p2_time: str | None,
    reason_code: str,
    evidence_update: dict | None = None,
) -> None:
    merged = dict(signal.evidence or {})
    if evidence_update:
        merged.update(evidence_update)
    signal.evidence = merged
    signal.status = "REJECTED"
    signal.reason_code = reason_code
    signal.p2_observation_id = p2_observation_id
    signal.p2_time = p2_time
    signal.updated_at = utc_now()
    record_event(
        session,
        signal_id=signal.id,
        session_date=signal.session_date,
        observation_id=p2_observation_id,
        event_type="SIGNAL_REJECTED",
        stage="P2",
        status="FAIL",
        reason_code=reason_code,
    )


def count_open_positions(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(PaperPosition).where(PaperPosition.status == "OPEN")
        )
        or 0
    )


@dataclass(frozen=True)
class PaperEntryRequest:
    waiting_signal_id: int
    p2_observation_id: int
    p2_time: str
    instrument_key: str
    expiry: str
    strike: float
    quantity: int
    entry_price: float
    entry_quote_timestamp: str | None
    evidence_update: dict


@dataclass(frozen=True)
class PaperEntryResult:
    accepted: bool
    status: str
    reason_code: str | None
    signal_id: int
    position_id: int | None
    open_positions: int


def confirm_signal_and_open_position(engine, request: PaperEntryRequest) -> PaperEntryResult:
    """
    DB-authoritative capacity + idempotency boundary.

    A file lock guarantees one production paper executor per VM. The DB unique
    constraints independently protect against replaying a confirmed signal.
    """
    ensure_paper_schema(engine)
    PAPER_EXECUTOR_LOCK.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(str(PAPER_EXECUTOR_LOCK), timeout=5):
        with Session(engine) as session, session.begin():
            control = session.get(PaperControl, 1)
            signal = session.get(PaperSignal, request.waiting_signal_id)
            if signal is None:
                raise LookupError("paper signal not found")

            existing_position = session.scalar(
                select(PaperPosition).where(PaperPosition.signal_id == signal.id).limit(1)
            )
            if existing_position is not None:
                return PaperEntryResult(
                    accepted=True,
                    status="IDEMPOTENT_REPLAY",
                    reason_code=None,
                    signal_id=signal.id,
                    position_id=existing_position.id,
                    open_positions=count_open_positions(session),
                )

            if not control.enabled:
                reject_waiting_signal(
                    session,
                    signal,
                    p2_observation_id=request.p2_observation_id,
                    p2_time=request.p2_time,
                    reason_code="PAPER_DISABLED",
                    evidence_update=request.evidence_update,
                )
                return PaperEntryResult(False, "REJECTED", "PAPER_DISABLED", signal.id, None, count_open_positions(session))

            if control.live_enabled or LIVE_TRADING_ENABLED:
                # Never permit the paper foundation to bridge to live execution.
                control.live_enabled = False
                reject_waiting_signal(
                    session,
                    signal,
                    p2_observation_id=request.p2_observation_id,
                    p2_time=request.p2_time,
                    reason_code="LIVE_EXECUTION_FORBIDDEN",
                    evidence_update=request.evidence_update,
                )
                return PaperEntryResult(False, "REJECTED", "LIVE_EXECUTION_FORBIDDEN", signal.id, None, count_open_positions(session))

            if signal.status != "WAIT_P2":
                return PaperEntryResult(
                    False,
                    "REJECTED",
                    f"SIGNAL_NOT_WAITING:{signal.status}",
                    signal.id,
                    None,
                    count_open_positions(session),
                )

            open_count = count_open_positions(session)
            if open_count >= MAX_OPEN_POSITIONS:
                reject_waiting_signal(
                    session,
                    signal,
                    p2_observation_id=request.p2_observation_id,
                    p2_time=request.p2_time,
                    reason_code="MAX_OPEN_POSITIONS",
                    evidence_update=request.evidence_update,
                )
                record_event(
                    session,
                    signal_id=signal.id,
                    session_date=signal.session_date,
                    observation_id=request.p2_observation_id,
                    event_type="CAPACITY_REJECTED",
                    stage="CAPACITY",
                    status="FAIL",
                    reason_code="MAX_OPEN_POSITIONS",
                    output_data={"open_positions": open_count, "limit": MAX_OPEN_POSITIONS},
                )
                return PaperEntryResult(False, "REJECTED", "MAX_OPEN_POSITIONS", signal.id, None, open_count)

            if request.quantity <= 0:
                raise ValueError("quantity must be > 0")
            if request.entry_price <= 0:
                raise ValueError("entry_price must be > 0")
            if request.strike <= 0:
                raise ValueError("strike must be > 0")
            if not request.instrument_key:
                raise ValueError("instrument_key is required")

            evidence = dict(signal.evidence or {})
            evidence.update(request.evidence_update or {})
            signal.evidence = evidence
            signal.p2_observation_id = request.p2_observation_id
            signal.p2_time = request.p2_time
            signal.status = "CONFIRMED"
            signal.reason_code = None
            signal.updated_at = utc_now()

            hard_stop = request.entry_price * 0.95
            position = PaperPosition(
                signal_id=signal.id,
                strategy_name=signal.strategy_name,
                session_date=signal.session_date,
                direction=signal.direction,
                option_type=signal.option_type,
                instrument_key=request.instrument_key,
                expiry=request.expiry,
                strike=request.strike,
                quantity=request.quantity,
                entry_time=request.p2_time,
                entry_price=request.entry_price,
                entry_fill_basis="ASK",
                entry_quote_timestamp=request.entry_quote_timestamp,
                status="OPEN",
                hard_stop_pct=5.0,
                breakeven_activation_pct=5.0,
                trail_activation_pct=10.0,
                trail_distance_pct=3.0,
                breakeven_active=False,
                trailing_active=False,
                best_price=request.entry_price,
                current_stop=hard_stop,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(position)
            session.flush()

            record_event(
                session,
                signal_id=signal.id,
                position_id=position.id,
                session_date=signal.session_date,
                observation_id=request.p2_observation_id,
                event_type="P2_CONFIRMED",
                stage="P2",
                status="PASS",
            )
            record_event(
                session,
                signal_id=signal.id,
                position_id=position.id,
                session_date=signal.session_date,
                observation_id=request.p2_observation_id,
                event_type="CAPACITY_PASS",
                stage="CAPACITY",
                status="PASS",
                output_data={"open_positions_before": open_count, "limit": MAX_OPEN_POSITIONS},
            )
            record_event(
                session,
                signal_id=signal.id,
                position_id=position.id,
                session_date=signal.session_date,
                observation_id=request.p2_observation_id,
                event_type="PAPER_ORDER_FILLED",
                stage="ENTRY",
                status="PASS",
                output_data={
                    "instrument_key": request.instrument_key,
                    "expiry": request.expiry,
                    "strike": request.strike,
                    "option_type": signal.option_type,
                    "quantity": request.quantity,
                    "fill_price": request.entry_price,
                    "fill_basis": "ASK",
                    "max_holding_minutes": None,
                },
            )

            return PaperEntryResult(
                True,
                "OPENED",
                None,
                signal.id,
                position.id,
                open_count + 1,
            )


def list_open_positions(session: Session) -> list[PaperPosition]:
    return list(
        session.scalars(
            select(PaperPosition)
            .where(PaperPosition.status == "OPEN")
            .order_by(PaperPosition.id)
        ).all()
    )


def update_position_mark(
    session: Session,
    position: PaperPosition,
    *,
    bid: float,
    ltp: float | None,
    quote_time: str,
) -> str:
    """
    Risk evaluation uses executable BID for a long-option paper exit.
    No time-based exit exists.
    """
    if position.status != "OPEN":
        return "IGNORED_CLOSED"
    if bid <= 0:
        raise ValueError("bid must be > 0")

    position.last_bid = bid
    position.last_ltp = ltp
    position.last_mark_time = quote_time
    position.best_price = max(position.best_price, bid)

    pnl_pct = (bid / position.entry_price - 1.0) * 100.0

    if pnl_pct >= position.breakeven_activation_pct and not position.breakeven_active:
        position.breakeven_active = True
        position.current_stop = max(position.current_stop, position.entry_price)
        record_event(
            session,
            signal_id=position.signal_id,
            position_id=position.id,
            session_date=position.session_date,
            event_type="BREAKEVEN_ARMED",
            stage="RISK",
            status="PASS",
            output_data={"bid": bid, "current_stop": position.current_stop},
            event_time=quote_time,
        )

    if pnl_pct >= position.trail_activation_pct and not position.trailing_active:
        position.trailing_active = True
        record_event(
            session,
            signal_id=position.signal_id,
            position_id=position.id,
            session_date=position.session_date,
            event_type="TRAILING_ARMED",
            stage="RISK",
            status="PASS",
            output_data={"bid": bid},
            event_time=quote_time,
        )

    if position.trailing_active:
        trailing_stop = position.best_price * (1.0 - position.trail_distance_pct / 100.0)
        if trailing_stop > position.current_stop:
            position.current_stop = trailing_stop
            record_event(
                session,
                signal_id=position.signal_id,
                position_id=position.id,
                session_date=position.session_date,
                event_type="TRAIL_UPDATED",
                stage="RISK",
                status="PASS",
                output_data={"best_price": position.best_price, "current_stop": position.current_stop},
                event_time=quote_time,
            )

    exit_reason = None
    if bid <= position.current_stop:
        if position.trailing_active:
            exit_reason = "TRAILING_STOP"
        elif position.breakeven_active and position.current_stop >= position.entry_price:
            exit_reason = "BREAKEVEN_STOP"
        else:
            exit_reason = "HARD_STOP"

    position.updated_at = utc_now()

    if exit_reason is None:
        return "HOLD"

    close_position(
        session,
        position,
        exit_price=bid,
        exit_time=quote_time,
        exit_reason=exit_reason,
        fill_basis="BID",
    )
    return exit_reason


def close_position(
    session: Session,
    position: PaperPosition,
    *,
    exit_price: float,
    exit_time: str,
    exit_reason: str,
    fill_basis: str = "BID",
) -> None:
    if position.status != "OPEN":
        return
    if exit_price <= 0:
        raise ValueError("exit_price must be > 0")

    position.status = "CLOSED"
    position.exit_time = exit_time
    position.exit_price = exit_price
    position.exit_fill_basis = fill_basis
    position.exit_reason = exit_reason
    position.realized_pnl = (exit_price - position.entry_price) * position.quantity
    position.updated_at = utc_now()

    record_event(
        session,
        signal_id=position.signal_id,
        position_id=position.id,
        session_date=position.session_date,
        event_type="POSITION_CLOSED",
        stage="EXIT",
        status="PASS",
        reason_code=exit_reason,
        output_data={
            "exit_price": exit_price,
            "fill_basis": fill_basis,
            "realized_pnl": position.realized_pnl,
        },
        event_time=exit_time,
    )


def update_paper_health(engine, **payload: Any) -> None:
    ensure_paper_schema(engine)
    with Session(engine) as session, session.begin():
        row = session.get(PaperHealth, 1)
        merged = {
            **(row.payload if row else {}),
            **payload,
            "heartbeat_at": utc_now(),
            "engine_version": PAPER_ENGINE_VERSION,
            "live_execution_enabled": False,
        }
        if row:
            row.payload = merged
        else:
            session.add(PaperHealth(id=1, payload=merged))


def paper_quick_view(session: Session) -> dict:
    control = get_paper_control(session)
    open_positions = list_open_positions(session)
    health = session.get(PaperHealth, 1)
    latest_event = session.scalar(select(PaperEvent).order_by(PaperEvent.id.desc()).limit(1))

    return {
        "control": control,
        "health": dict(health.payload) if health else {"state": "not_started"},
        "open_position_count": len(open_positions),
        "capacity": MAX_OPEN_POSITIONS,
        "open_positions": [
            {
                "id": p.id,
                "signal_id": p.signal_id,
                "direction": p.direction,
                "option_type": p.option_type,
                "instrument_key": p.instrument_key,
                "expiry": p.expiry,
                "strike": p.strike,
                "quantity": p.quantity,
                "entry_time": p.entry_time,
                "entry_price": p.entry_price,
                "best_price": p.best_price,
                "current_stop": p.current_stop,
                "breakeven_active": p.breakeven_active,
                "trailing_active": p.trailing_active,
                "last_bid": p.last_bid,
                "last_mark_time": p.last_mark_time,
            }
            for p in open_positions
        ],
        "latest_event": (
            {
                "id": latest_event.id,
                "event_time": latest_event.event_time,
                "event_type": latest_event.event_type,
                "stage": latest_event.stage,
                "status": latest_event.status,
                "reason_code": latest_event.reason_code,
            }
            if latest_event
            else None
        ),
    }


def paper_detail_view(session: Session, limit: int = 250) -> dict:
    if limit < 1 or limit > 2000:
        raise ValueError("limit must be between 1 and 2000")

    signals = list(
        session.scalars(select(PaperSignal).order_by(PaperSignal.id.desc()).limit(limit)).all()
    )
    events = list(
        session.scalars(select(PaperEvent).order_by(PaperEvent.id.desc()).limit(limit)).all()
    )

    return {
        "signals": [
            {
                "id": s.id,
                "strategy_name": s.strategy_name,
                "strategy_version": s.strategy_version,
                "session_date": s.session_date,
                "direction": s.direction,
                "option_type": s.option_type,
                "status": s.status,
                "reason_code": s.reason_code,
                "p1_observation_id": s.p1_observation_id,
                "p2_observation_id": s.p2_observation_id,
                "p1_time": s.p1_time,
                "p2_time": s.p2_time,
                "evidence": s.evidence,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in signals
        ],
        "events": [
            {
                "id": e.id,
                "signal_id": e.signal_id,
                "position_id": e.position_id,
                "session_date": e.session_date,
                "event_time": e.event_time,
                "event_type": e.event_type,
                "stage": e.stage,
                "status": e.status,
                "reason_code": e.reason_code,
                "observation_id": e.observation_id,
                "input_data": e.input_data,
                "output_data": e.output_data,
            }
            for e in events
        ],
    }
