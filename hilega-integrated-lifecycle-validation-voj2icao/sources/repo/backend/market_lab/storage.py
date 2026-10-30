import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import JSON, Boolean, Float, Integer, String, UniqueConstraint, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .domain import Anchor, ENGINE_VERSION, Evaluation, ForwardLookupConfig, IST, PCRHistoryRecord, PCRTrendConfig, PCRConfig, Snapshot, StrikePositioningConfig, evaluate
from .positioning import (
    POSITIONING_HORIZONS_SECONDS,
    PositioningBaselineCandidate,
    calculate_strike_positioning,
    positioning_baseline_window,
    select_positioning_baseline,
    select_strike_window,
)
from .session_analysis import build_session_analysis
from .trends import TREND_HORIZONS_SECONDS, calculate_trend

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


class PCRHistorySnapshot(Base):
    __tablename__ = "pcr_history_snapshots"
    __table_args__ = (UniqueConstraint("observation_id", "record_kind", "mode", "strike"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[int] = mapped_column(Integer, index=True)
    configuration_version: Mapped[int] = mapped_column(Integer, index=True)
    record_kind: Mapped[str] = mapped_column(String(12), index=True)
    mode: Mapped[str] = mapped_column(String(12), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    provider_timestamp: Mapped[str | None] = mapped_column(String, nullable=True)
    received_at: Mapped[str] = mapped_column(String, index=True)
    processed_at: Mapped[str] = mapped_column(String)
    underlying_spot: Mapped[float] = mapped_column(Float)
    atm_reference: Mapped[float | None] = mapped_column(Float, nullable=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    call_oi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    put_oi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_call_oi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_put_oi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_oi_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    put_oi_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_oi_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    put_oi_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    strike_pcr: Mapped[float | None] = mapped_column(Float, nullable=True)
    panel_pcr: Mapped[float | None] = mapped_column(Float, nullable=True)
    panel_pcr_by_mode: Mapped[dict] = mapped_column(JSON)
    data_status: Mapped[str] = mapped_column(String(16))
    data_issues: Mapped[list] = mapped_column(JSON)
    freshness_warnings: Mapped[list] = mapped_column(JSON)
    engine_version: Mapped[str] = mapped_column(String(32))


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


def _anchor_matches(anchor, snapshot, config):
    local_date = snapshot.received_at.astimezone(IST).date()
    if (anchor.session, anchor.provider, anchor.underlying, anchor.expiry) != (
        local_date, config.provider, config.underlying, config.expiry
    ):
        return False
    scheduled = datetime.combine(local_date, datetime.strptime(config.anchor_time, "%H:%M").time(), IST)
    capture_delay = (anchor.captured_at - scheduled).total_seconds()
    if not 0 <= capture_delay <= config.anchor_tolerance_seconds:
        return False
    identities = {(contract.strike, contract.side) for contract in anchor.contracts}
    strikes = sorted({contract.strike for contract in anchor.contracts})
    expected_strikes = 2 * config.wings + 1
    return (
        len(strikes) == expected_strikes
        and len(identities) == expected_strikes * 2
        and anchor.atm in strikes
        and strikes.index(anchor.atm) == config.wings
        and all((strike, side) in identities for strike in strikes for side in ("CE", "PE"))
    )


def find_compatible_fixed_anchor(session, config, snapshot):
    """Find an exact earlier captured basket; never mutates historical observations."""
    session_date = snapshot.received_at.astimezone(IST).date().isoformat()
    fingerprint = config.fixed_anchor_compatibility_fingerprint()
    rows = session.scalars(
        select(Observation).where(Observation.session_date == session_date).order_by(Observation.id.desc())
    ).all()
    config_cache = {}
    candidates = []
    for row in rows:
        value = row.evaluation.get("anchor")
        if row.evaluation.get("anchor_status") != "captured" or not value:
            continue
        received_at = datetime.fromisoformat(row.snapshot["received_at"].replace("Z", "+00:00"))
        if received_at >= snapshot.received_at:
            continue
        candidate_config = config_cache.get(row.config_id)
        if candidate_config is None:
            config_row = session.get(Configuration, row.config_id)
            if config_row is None:
                continue
            candidate_config = PCRConfig.model_validate(config_row.payload)
            config_cache[row.config_id] = candidate_config
        if candidate_config.fixed_anchor_compatibility_fingerprint() != fingerprint:
            continue
        if row.evaluation.get("engine_version") != ENGINE_VERSION:
            continue
        anchor = Anchor.model_validate(value)
        if _anchor_matches(anchor, snapshot, config):
            candidates.append((received_at, row.id, anchor))
    return max(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None


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
            propagated = Anchor.model_validate(value) if value else None
            anchor = propagated if propagated and _anchor_matches(propagated, snapshot, config) else None
        if anchor is None:
            anchor = find_compatible_fixed_anchor(session, config, snapshot)
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
        persist_pcr_history(session, row.id, config_id, snapshot, result, row.recorded_at)
        return row.id


def _change(current, previous):
    return current - previous if current is not None and previous is not None else None


def _change_pct(current, previous):
    return (current - previous) / previous * 100 if current is not None and previous not in (None, 0) else None


def _as_history_record(row):
    return PCRHistoryRecord(
        id=row.id, observation_id=row.observation_id, configuration_version=row.configuration_version,
        record_kind=row.record_kind, mode=row.mode, fingerprint=row.fingerprint,
        provider_timestamp=row.provider_timestamp, received_at=row.received_at, processed_at=row.processed_at,
        underlying_spot=row.underlying_spot, atm_reference=row.atm_reference, strike=row.strike,
        call_oi=row.call_oi, put_oi=row.put_oi, previous_call_oi=row.previous_call_oi,
        previous_put_oi=row.previous_put_oi, call_oi_change=row.call_oi_change,
        put_oi_change=row.put_oi_change, call_oi_change_pct=row.call_oi_change_pct,
        put_oi_change_pct=row.put_oi_change_pct, strike_pcr=row.strike_pcr, panel_pcr=row.panel_pcr,
        panel_pcr_by_mode=row.panel_pcr_by_mode, data_status=row.data_status, data_issues=row.data_issues,
        freshness_warnings=row.freshness_warnings, engine_version=row.engine_version,
    )


def persist_pcr_history(session, observation_id, config_id, snapshot, evaluation, processed_at):
    """Write mode totals once and one canonical raw PCR row for each strike."""
    config = PCRConfig.model_validate(session.get(Configuration, config_id).payload)
    provider_timestamp = snapshot.oi_source_at or snapshot.spot_feed_at
    panels = {result.mode: result for result in evaluation.results}
    created = 0

    def add_if_missing(record_kind, mode, strike, values):
        nonlocal created
        query = select(PCRHistorySnapshot.id).where(
            PCRHistorySnapshot.observation_id == observation_id,
            PCRHistorySnapshot.record_kind == record_kind,
            PCRHistorySnapshot.mode == mode,
        )
        query = query.where(PCRHistorySnapshot.strike.is_(None) if strike is None else PCRHistorySnapshot.strike == strike)
        if session.scalar(query.limit(1)) is None:
            session.add(PCRHistorySnapshot(**values))
            created += 1

    for result in evaluation.results:
        add_if_missing("panel", result.mode, None, dict(
            observation_id=observation_id, configuration_version=config_id, record_kind="panel", mode=result.mode,
            fingerprint=config.trend_fingerprint(result.mode, fixed_atm=result.atm if result.mode == "fixed" else None),
            provider_timestamp=provider_timestamp.isoformat() if provider_timestamp else None,
            received_at=snapshot.received_at.isoformat(), processed_at=processed_at, underlying_spot=snapshot.spot,
            atm_reference=result.atm, strike=None, call_oi=result.call_oi, put_oi=result.put_oi,
            previous_call_oi=result.call_prev_oi, previous_put_oi=result.put_prev_oi,
            call_oi_change=result.call_change_oi, put_oi_change=result.put_change_oi,
            call_oi_change_pct=result.call_change_pct, put_oi_change_pct=result.put_change_pct,
            strike_pcr=None, panel_pcr=result.pcr, panel_pcr_by_mode={result.mode: result.pcr},
            data_status="AVAILABLE" if result.pcr is not None else "UNAVAILABLE", data_issues=result.issues,
            freshness_warnings=evaluation.warnings, engine_version=evaluation.engine_version,
        ))
    contracts = {(contract.strike, contract.side): contract for contract in snapshot.catalog}
    quotes = {quote.key: quote for quote in snapshot.quotes}
    for strike in sorted({contract.strike for contract in snapshot.catalog}):
        call = quotes.get(contracts[(strike, "CE")].key) if (strike, "CE") in contracts else None
        put = quotes.get(contracts[(strike, "PE")].key) if (strike, "PE") in contracts else None
        call_oi, put_oi = (call.oi if call else None), (put.oi if put else None)
        issues = (["missing_or_invalid_oi"] if call_oi is None or put_oi is None else [])
        if call_oi == 0: issues.append("zero_call_oi")
        strike_pcr = put_oi / call_oi if call_oi not in (None, 0) and put_oi is not None else None
        add_if_missing("strike", "strike", strike, dict(
            observation_id=observation_id, configuration_version=config_id, record_kind="strike", mode="strike",
            fingerprint=config.trend_fingerprint("strike", strike=strike),
            provider_timestamp=provider_timestamp.isoformat() if provider_timestamp else None,
            received_at=snapshot.received_at.isoformat(), processed_at=processed_at, underlying_spot=snapshot.spot,
            atm_reference=None, strike=strike, call_oi=call_oi, put_oi=put_oi,
            previous_call_oi=call.prev_oi if call else None, previous_put_oi=put.prev_oi if put else None,
            call_oi_change=_change(call_oi, call.prev_oi if call else None),
            put_oi_change=_change(put_oi, put.prev_oi if put else None),
            call_oi_change_pct=_change_pct(call_oi, call.prev_oi if call else None),
            put_oi_change_pct=_change_pct(put_oi, put.prev_oi if put else None),
            strike_pcr=strike_pcr, panel_pcr=None,
            panel_pcr_by_mode={mode: result.pcr if strike in result.strikes else None for mode, result in panels.items()},
            data_status="AVAILABLE" if strike_pcr is not None else "UNAVAILABLE", data_issues=issues,
            freshness_warnings=evaluation.warnings, engine_version=evaluation.engine_version,
        ))
    return created


def backfill_pcr_history(session, config_id):
    """Explicit, idempotent reconstruction of normalized PCR history from stored observations."""
    if session.get(Configuration, config_id) is None:
        raise ValueError("Configuration not found")
    observations = session.scalars(
        select(Observation).where(Observation.config_id == config_id).order_by(Observation.session_date, Observation.id)
    ).all()
    report = {
        "config_id": config_id, "observations_scanned": len(observations), "observations_backfilled": 0,
        "observations_skipped": 0, "history_rows_created": 0, "errors": [],
    }
    for observation in observations:
        try:
            snapshot = Snapshot.model_validate(observation.snapshot)
            evaluation = Evaluation.model_validate(observation.evaluation)
            created = persist_pcr_history(
                session, observation.id, config_id, snapshot, evaluation, observation.recorded_at
            )
            if created:
                report["observations_backfilled"] += 1
                report["history_rows_created"] += created
            else:
                report["observations_skipped"] += 1
        except Exception as error:
            report["errors"].append({"observation_id": observation.id, "error": str(error)})
    return report


def trend_results(session, config_id, mode=None, strike=None, latest_only=False, limit=240, panels_only=False):
    config_row = session.get(Configuration, config_id)
    if config_row is None:
        raise ValueError("Configuration not found")
    config = PCRConfig.model_validate(config_row.payload)
    query = select(PCRHistorySnapshot)
    if panels_only: query = query.where(PCRHistorySnapshot.record_kind == "panel")
    if mode is not None: query = query.where(PCRHistorySnapshot.mode == mode)
    if strike is not None: query = query.where(PCRHistorySnapshot.strike == strike)
    if latest_only:
        observation_id = session.scalar(select(Observation.id).where(Observation.config_id == config_id).order_by(Observation.id.desc()).limit(1))
        query = query.where(PCRHistorySnapshot.observation_id == observation_id)
    rows = session.scalars(query.order_by(PCRHistorySnapshot.received_at.desc(), PCRHistorySnapshot.id.desc()).limit(limit)).all()
    trend_config = PCRTrendConfig(flat_threshold=config.trend_flat_threshold, timestamp_tolerance_seconds=config.trend_timestamp_tolerance_seconds)
    results = []
    if panels_only:
        currents = [_as_history_record(row) for row in rows]
        if not currents:
            return results
        earliest = min(
            current.received_at - timedelta(
                seconds=max(TREND_HORIZONS_SECONDS) + trend_config.timestamp_tolerance_seconds
            )
            for current in currents
        )
        latest = max(
            current.received_at - timedelta(seconds=min(TREND_HORIZONS_SECONDS))
            for current in currents
        )
        fingerprints = {current.fingerprint for current in currents}
        history_rows = session.scalars(
            select(PCRHistorySnapshot).where(
                PCRHistorySnapshot.record_kind == "panel",
                PCRHistorySnapshot.fingerprint.in_(fingerprints),
                PCRHistorySnapshot.received_at >= earliest.isoformat(),
                PCRHistorySnapshot.received_at <= latest.isoformat(),
            ).order_by(PCRHistorySnapshot.received_at, PCRHistorySnapshot.id)
        ).all()
        history_by_fingerprint = {fingerprint: [] for fingerprint in fingerprints}
        for history_row in history_rows:
            history = _as_history_record(history_row)
            history_by_fingerprint[history.fingerprint].append(history)
        for current in currents:
            history = history_by_fingerprint[current.fingerprint]
            results.extend(
                calculate_trend(current, history, horizon, trend_config).model_dump(mode="json")
                for horizon in TREND_HORIZONS_SECONDS
            )
        return results
    for row in rows:
        current = _as_history_record(row)
        history = [_as_history_record(item) for item in session.scalars(select(PCRHistorySnapshot).where(PCRHistorySnapshot.fingerprint == row.fingerprint).order_by(PCRHistorySnapshot.received_at, PCRHistorySnapshot.id)).all()]
        results.extend(calculate_trend(current, history, horizon, trend_config).model_dump(mode="json") for horizon in TREND_HORIZONS_SECONDS)
    return results

def strike_positioning_results(
    session, config_id, horizon_seconds=None, observation_id=None, center_strike=None, wings=None
):
    if session.get(Configuration, config_id) is None:
        raise ValueError("Configuration not found")
    horizons = POSITIONING_HORIZONS_SECONDS if horizon_seconds is None else (horizon_seconds,)
    if any(value not in POSITIONING_HORIZONS_SECONDS for value in horizons):
        raise ValueError("horizon_seconds must be 300, 900 or 1800")
    query = select(Observation).where(Observation.config_id == config_id)
    if observation_id is not None:
        query = query.where(Observation.id == observation_id)
    else:
        query = query.order_by(Observation.id.desc()).limit(1)
    current_row = session.scalar(query)
    if current_row is None:
        raise LookupError("Observation not found")
    current = Snapshot.model_validate(current_row.snapshot)
    if (center_strike is None) != (wings is None):
        raise ValueError("center_strike and wings must be supplied together")
    selected_strikes = None if center_strike is None else set(select_strike_window(current.catalog, center_strike, wings))
    config = StrikePositioningConfig()
    windows = [positioning_baseline_window(current, horizon, config) for horizon in horizons]
    received_at = Observation.snapshot["received_at"].as_string()
    candidate_rows = session.scalars(
        select(Observation).where(
            Observation.config_id == config_id,
            Observation.session_date == current_row.session_date,
            received_at >= min(window[0] for window in windows).isoformat(),
            received_at <= max(window[1] for window in windows).isoformat(),
        ).order_by(Observation.id)
    ).all()

    def metadata(row):
        value = row.snapshot
        return PositioningBaselineCandidate(
            observation_id=row.id,
            received_at=datetime.fromisoformat(value["received_at"].replace("Z", "+00:00")),
            provider=value["provider"],
            underlying=value["underlying"],
            expiry=date.fromisoformat(value["expiry"]),
        )

    candidates = [(metadata(row), row) for row in candidate_rows]
    selected = [select_positioning_baseline(current, (item[0] for item in candidates), horizon, config) for horizon in horizons]
    selected_ids = {item.observation_id for item in selected if item is not None}
    parsed = {row.id: Snapshot.model_validate(row.snapshot) for _, row in candidates if row.id in selected_ids}
    return [
        result.model_dump(mode="json")
        for horizon, baseline in zip(horizons, selected)
        for result in calculate_strike_positioning(
            current_row.id,
            config_id,
            current,
            [] if baseline is None else [(baseline.observation_id, parsed[baseline.observation_id])],
            horizon,
            config,
            selected_strikes,
        )
    ]


def session_analysis_results(session, config_id, forward_config=None):
    """Derived projection only; analysis facts are never persisted separately."""
    config_row = session.get(Configuration, config_id)
    if config_row is None:
        raise ValueError("Configuration not found")
    config = PCRConfig.model_validate(config_row.payload)
    rows = session.scalars(
        select(PCRHistorySnapshot)
        .where(PCRHistorySnapshot.configuration_version == config_id, PCRHistorySnapshot.record_kind == "panel")
        .order_by(PCRHistorySnapshot.received_at, PCRHistorySnapshot.id)
    ).all()
    analyses = build_session_analysis(
        (_as_history_record(row) for row in rows), underlying=config.underlying, expiry=config.expiry,
        trend_config=PCRTrendConfig(
            flat_threshold=config.trend_flat_threshold,
            timestamp_tolerance_seconds=config.trend_timestamp_tolerance_seconds,
        ),
        forward_config=forward_config or ForwardLookupConfig(),
    )
    return [analysis.model_dump(mode="json") for analysis in analyses]


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
            snapshot = Snapshot.model_validate(row.snapshot)

            # Replay preserves the historical operational boundary.  A config may
            # have recorded ``anchor_missed`` rows before cross-version recovery
            # was deployed, so applying today's recovery rule to every old row
            # would rewrite history.  When a stored row first records a captured
            # anchor, however, verify that it is the exact compatible earlier
            # anchor available in storage and inject that external state before
            # re-evaluating the snapshot.
            if anchor is None and row.evaluation.get("anchor_status") == "captured":
                stored_value = row.evaluation.get("anchor")
                stored_anchor = Anchor.model_validate(stored_value) if stored_value else None
                compatible = find_compatible_fixed_anchor(session, config, snapshot)
                if stored_anchor is not None and compatible is not None and stored_anchor == compatible:
                    anchor = compatible

            result = evaluate(snapshot, config, anchor)
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
