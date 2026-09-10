import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import JSON, Boolean, Integer, String, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .domain import Anchor, PCRConfig, Snapshot, evaluate

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class Base(DeclarativeBase):
    pass


class Configuration(Base):
    __tablename__ = "configurations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_id: Mapped[int] = mapped_column(index=True)
    recorded_at: Mapped[str] = mapped_column(String)
    session_date: Mapped[str] = mapped_column(String, index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    evaluation: Mapped[dict] = mapped_column(JSON)


class Control(Base):
    __tablename__ = "control"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active_config_id: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class Health(Base):
    __tablename__ = "worker_health"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def make_engine(url=None):
    url = url or os.getenv("DATABASE_URL", "sqlite:///./data/lab.db")
    Path("data").mkdir(exist_ok=True)
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {},
        pool_pre_ping=True,
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def sqlite_setup(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    Base.metadata.create_all(engine)
    return engine


def initialize(engine):
    from datetime import timedelta
    from .domain import IST

    with Session(engine) as session, session.begin():
        if session.get(Control, 1):
            return
        config = PCRConfig(expiry=datetime.now(IST).date() + timedelta(days=7))
        row = Configuration(created_at=utc_now(), payload=config.model_dump(mode="json"))
        session.add(row)
        session.flush()
        session.add(Control(id=1, active_config_id=row.id, enabled=False))


def active_config(session):
    control = session.get(Control, 1)
    row = session.get(Configuration, control.active_config_id)
    return row.id, PCRConfig.model_validate(row.payload), control.enabled


def record(engine, config_id, snapshot):
    # Single writer (worker file lock). Snapshot, computed result and anchor commit together.
    with Session(engine) as session, session.begin():
        config = PCRConfig.model_validate(session.get(Configuration, config_id).payload)
        previous = session.scalar(
            select(Observation)
            .where(Observation.config_id == config_id)
            .order_by(Observation.id.desc())
            .limit(1)
        )
        anchor = None
        if previous:
            previous_time = Snapshot.model_validate(previous.snapshot).received_at
            if snapshot.received_at <= previous_time:
                raise ValueError("Out-of-order or duplicate observation")
            value = previous.evaluation.get("anchor")
            anchor = Anchor.model_validate(value) if value else None
        result = evaluate(snapshot, config, anchor)
        from .domain import IST

        row = Observation(
            config_id=config_id,
            recorded_at=utc_now(),
            session_date=snapshot.received_at.astimezone(IST).date().isoformat(),
            snapshot=snapshot.model_dump(mode="json"),
            evaluation=result.model_dump(mode="json"),
        )
        session.add(row)
        session.flush()
        return row.id


def update_health(engine, **payload):
    with Session(engine) as session, session.begin():
        row = session.get(Health, 1)
        merged = {**(row.payload if row else {}), **payload, "heartbeat_at": utc_now()}
        if row:
            row.payload = merged
        else:
            session.add(Health(id=1, payload=merged))


def replay(engine, config_id):
    with Session(engine) as session:
        config_row = session.get(Configuration, config_id)
        if config_row is None:
            raise ValueError("Configuration not found")
        config = PCRConfig.model_validate(config_row.payload)
        rows = session.scalars(
            select(Observation).where(Observation.config_id == config_id).order_by(Observation.id)
        ).all()
        anchor = None
        mismatches = []
        for row in rows:
            result = evaluate(Snapshot.model_validate(row.snapshot), config, anchor)
            anchor = result.anchor
            if result.model_dump(mode="json") != row.evaluation:
                mismatches.append(row.id)
        return {
            "config_id": config_id,
            "observations": len(rows),
            "mismatches": mismatches,
            "matched": bool(rows) and not mismatches,
            "message": "No observations to replay" if not rows else "Recorded inputs replayed",
            "scope": "Calculation reproducibility only; not a strategy backtest",
        }
