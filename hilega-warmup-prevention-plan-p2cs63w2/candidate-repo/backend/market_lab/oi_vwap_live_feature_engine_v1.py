
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, time, timedelta
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import IST, Snapshot
from .storage import Observation, Configuration


FEATURE_VERSION = "OI_VWAP_LIVE_FEATURE_ENGINE_V1"
CHECKPOINT_MINUTES = 5
SESSION_BASELINE_TIME = time(9, 20)
SESSION_END_TIME = time(15, 30)
WINGS = 2


@dataclass(frozen=True)
class OIWindow:
    center_strike: float
    strikes: tuple[float, ...]
    ce_oi: int
    pe_oi: int


@dataclass(frozen=True)
class OICheckpointFeature:
    observation_id: int
    timestamp: str
    session_date: str
    spot: float
    atm: float
    ce_oi: int
    pe_oi: int
    ce_delta_5m: int
    pe_delta_5m: int
    imbalance_5m: int
    pcr_current_5m: float | None
    pcr_previous_5m: float | None
    pcr_change_5m: float | None
    ce_session_delta: int
    pe_session_delta: int
    session_imbalance: int
    previous_session_imbalance: int | None


@dataclass(frozen=True)
class FuturesVWAPFeature:
    candle_time: str
    available_at: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    cumulative_vwap: float
    distance: float
    side: str


@dataclass(frozen=True)
class LiveStrategyFeature:
    version: str
    oi: OICheckpointFeature
    vwap: FuturesVWAPFeature | None


def _nearest_atm(spot: float, strikes: Iterable[float]) -> float:
    values = sorted(set(float(s) for s in strikes))
    if not values:
        raise ValueError("no strikes available")
    return min(values, key=lambda s: (abs(s - spot), s))


def _quote_map(snapshot: Snapshot):
    contracts = {(c.strike, c.side): c for c in snapshot.catalog}
    quotes = {q.key: q for q in snapshot.quotes}
    return contracts, quotes


def _window(snapshot: Snapshot, wings: int = WINGS) -> OIWindow:
    strikes = sorted({c.strike for c in snapshot.catalog})
    atm = _nearest_atm(snapshot.spot, strikes)
    try:
        idx = strikes.index(atm)
    except ValueError:
        raise ValueError("ATM strike missing from catalog")
    lo = idx - wings
    hi = idx + wings
    if lo < 0 or hi >= len(strikes):
        raise ValueError("ATM ±2 strike window unavailable")
    selected = tuple(strikes[lo:hi+1])
    contracts, quotes = _quote_map(snapshot)
    ce_oi = 0
    pe_oi = 0
    for strike in selected:
        ce_c = contracts.get((strike, "CE"))
        pe_c = contracts.get((strike, "PE"))
        if ce_c is None or pe_c is None:
            raise ValueError("ATM ±2 contract window incomplete")
        ce_q = quotes.get(ce_c.key)
        pe_q = quotes.get(pe_c.key)
        if ce_q is None or pe_q is None or ce_q.oi is None or pe_q.oi is None:
            raise ValueError("ATM ±2 OI unavailable")
        ce_oi += ce_q.oi
        pe_oi += pe_q.oi
    return OIWindow(atm, selected, ce_oi, pe_oi)


def _pcr(pe: int, ce: int) -> float | None:
    return pe / ce if ce else None


def _dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _completed_checkpoint(ts: datetime) -> datetime:
    local = ts.astimezone(IST)
    minute = local.minute - (local.minute % CHECKPOINT_MINUTES)
    checkpoint = local.replace(minute=minute, second=0, microsecond=0)
    return checkpoint


def _load_session_observations(session: Session, config_id: int, session_date: str) -> list[Observation]:
    return list(
        session.scalars(
            select(Observation)
            .where(
                Observation.config_id == config_id,
                Observation.session_date == session_date,
            )
            .order_by(Observation.id)
        ).all()
    )


def _snapshot(row: Observation) -> Snapshot:
    return Snapshot.model_validate(row.snapshot)


def _latest_at_or_before(rows: list[Observation], at: datetime) -> Observation | None:
    candidates = []
    for row in rows:
        ts = _snapshot(row).received_at.astimezone(IST)
        if ts <= at:
            candidates.append((ts, row.id, row))
    return max(candidates, default=(None, None, None), key=lambda x: (x[0], x[1]))[2]


def _first_at_or_after(rows: list[Observation], at: datetime, tolerance_seconds: int = 120) -> Observation | None:
    best = None
    for row in rows:
        ts = _snapshot(row).received_at.astimezone(IST)
        delta = (ts - at).total_seconds()
        if 0 <= delta <= tolerance_seconds:
            candidate = (delta, row.id, row)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
    return None if best is None else best[2]


def build_oi_checkpoint_feature(
    session: Session,
    *,
    config_id: int,
    observation_id: int,
) -> OICheckpointFeature:
    current_row = session.get(Observation, observation_id)
    if current_row is None or current_row.config_id != config_id:
        raise LookupError("observation not found for config")
    current = _snapshot(current_row)
    local = current.received_at.astimezone(IST)
    if not (SESSION_BASELINE_TIME <= local.time() < SESSION_END_TIME):
        raise ValueError("observation outside active session")

    rows = _load_session_observations(session, config_id, current_row.session_date)
    checkpoint = _completed_checkpoint(local)
    if local < checkpoint:
        raise ValueError("invalid checkpoint chronology")

    # Need a row at/after exact checkpoint so the completed 5m interval is available.
    checkpoint_row = _first_at_or_after(rows, checkpoint, tolerance_seconds=120)
    if checkpoint_row is None:
        raise ValueError("no observation close enough to current checkpoint")
    checkpoint_snapshot = _snapshot(checkpoint_row)

    previous_checkpoint = checkpoint - timedelta(minutes=5)
    previous_row = _first_at_or_after(rows, previous_checkpoint, tolerance_seconds=120)
    if previous_row is None:
        raise ValueError("previous 5m checkpoint unavailable")
    previous_snapshot = _snapshot(previous_row)

    session_start = datetime.combine(local.date(), SESSION_BASELINE_TIME, IST)
    baseline_row = _first_at_or_after(rows, session_start, tolerance_seconds=120)
    if baseline_row is None:
        raise ValueError("09:20 session baseline unavailable")
    baseline_snapshot = _snapshot(baseline_row)

    previous_previous_checkpoint = previous_checkpoint - timedelta(minutes=5)
    previous_previous_row = _first_at_or_after(rows, previous_previous_checkpoint, tolerance_seconds=120)

    curr_w = _window(checkpoint_snapshot)
    prev_w = _window(previous_snapshot)
    base_w = _window(baseline_snapshot)

    # Recent 5m comparison must use the same physical current ATM±2 strikes.
    contracts_prev, quotes_prev = _quote_map(previous_snapshot)
    ce_prev_same = 0
    pe_prev_same = 0
    for strike in curr_w.strikes:
        ce_c = contracts_prev.get((strike, "CE"))
        pe_c = contracts_prev.get((strike, "PE"))
        if ce_c is None or pe_c is None:
            raise ValueError("previous checkpoint missing current ATM±2 strikes")
        ce_q = quotes_prev.get(ce_c.key)
        pe_q = quotes_prev.get(pe_c.key)
        if ce_q is None or pe_q is None or ce_q.oi is None or pe_q.oi is None:
            raise ValueError("previous checkpoint OI unavailable for current ATM±2 strikes")
        ce_prev_same += ce_q.oi
        pe_prev_same += pe_q.oi

    ce_delta = curr_w.ce_oi - ce_prev_same
    pe_delta = curr_w.pe_oi - pe_prev_same
    imbalance = pe_delta - ce_delta

    pcr_current = _pcr(curr_w.pe_oi, curr_w.ce_oi)
    pcr_previous = _pcr(pe_prev_same, ce_prev_same)
    pcr_change = None if pcr_current is None or pcr_previous is None else pcr_current - pcr_previous

    # Session context uses the fixed 09:20 ATM±2 strike basket.
    contracts_curr, quotes_curr = _quote_map(checkpoint_snapshot)
    contracts_base, quotes_base = _quote_map(baseline_snapshot)
    ce_session = 0
    pe_session = 0
    for strike in base_w.strikes:
        ce_now = contracts_curr.get((strike, "CE"))
        pe_now = contracts_curr.get((strike, "PE"))
        ce_base = contracts_base.get((strike, "CE"))
        pe_base = contracts_base.get((strike, "PE"))
        if None in (ce_now, pe_now, ce_base, pe_base):
            raise ValueError("fixed 09:20 ATM±2 strikes unavailable")
        ce_now_q = quotes_curr.get(ce_now.key)
        pe_now_q = quotes_curr.get(pe_now.key)
        ce_base_q = quotes_base.get(ce_base.key)
        pe_base_q = quotes_base.get(pe_base.key)
        if any(q is None or q.oi is None for q in (ce_now_q, pe_now_q, ce_base_q, pe_base_q)):
            raise ValueError("fixed 09:20 ATM±2 OI unavailable")
        ce_session += ce_now_q.oi - ce_base_q.oi
        pe_session += pe_now_q.oi - pe_base_q.oi
    session_imbalance = pe_session - ce_session

    previous_session_imbalance = None
    if previous_previous_row is not None:
        prev_curr = _snapshot(previous_row)
        contracts_prev2, quotes_prev2 = _quote_map(prev_curr)
        ce_s = 0
        pe_s = 0
        for strike in base_w.strikes:
            ce_now = contracts_prev2.get((strike, "CE"))
            pe_now = contracts_prev2.get((strike, "PE"))
            ce_base = contracts_base.get((strike, "CE"))
            pe_base = contracts_base.get((strike, "PE"))
            if None in (ce_now, pe_now, ce_base, pe_base):
                raise ValueError("previous session-context strikes unavailable")
            ce_now_q = quotes_prev2.get(ce_now.key)
            pe_now_q = quotes_prev2.get(pe_now.key)
            ce_base_q = quotes_base.get(ce_base.key)
            pe_base_q = quotes_base.get(pe_base.key)
            if any(q is None or q.oi is None for q in (ce_now_q, pe_now_q, ce_base_q, pe_base_q)):
                raise ValueError("previous session-context OI unavailable")
            ce_s += ce_now_q.oi - ce_base_q.oi
            pe_s += pe_now_q.oi - pe_base_q.oi
        previous_session_imbalance = pe_s - ce_s

    return OICheckpointFeature(
        observation_id=checkpoint_row.id,
        timestamp=checkpoint_snapshot.received_at.astimezone(IST).isoformat(),
        session_date=current_row.session_date,
        spot=checkpoint_snapshot.spot,
        atm=curr_w.center_strike,
        ce_oi=curr_w.ce_oi,
        pe_oi=curr_w.pe_oi,
        ce_delta_5m=ce_delta,
        pe_delta_5m=pe_delta,
        imbalance_5m=imbalance,
        pcr_current_5m=pcr_current,
        pcr_previous_5m=pcr_previous,
        pcr_change_5m=pcr_change,
        ce_session_delta=ce_session,
        pe_session_delta=pe_session,
        session_imbalance=session_imbalance,
        previous_session_imbalance=previous_session_imbalance,
    )


def feature_to_dict(feature: LiveStrategyFeature) -> dict:
    return {
        "version": feature.version,
        "oi": asdict(feature.oi),
        "vwap": None if feature.vwap is None else asdict(feature.vwap),
    }
