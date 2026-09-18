from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Literal

from .domain import Snapshot
from .live_observational_data_health_v1 import (
    SnapshotHealthReport,
    evaluate_snapshot_health,
    strategy_dependency_gate,
)

MODEL = "LIVE_NORMALIZED_FEATURE_PRODUCER_V1"

HORIZONS_MINUTES = (5, 10, 15)
All3State = Literal["BULLISH_ALL_3", "BEARISH_ALL_3", "MIXED", "INCOMPLETE"]


@dataclass(frozen=True)
class HorizonFeature:
    horizon_minutes: int
    current_ce_oi: float | None
    current_pe_oi: float | None
    prior_ce_oi: float | None
    prior_pe_oi: float | None
    ce_delta: float | None
    pe_delta: float | None
    imbalance: float | None
    prior_pcr: float | None
    current_pcr: float | None
    pcr_change: float | None
    state: str


@dataclass(frozen=True)
class LiveNormalizedCheckpoint:
    model: str
    session_date: str
    timestamp: datetime
    spot: float
    moving_atm: float
    strike_interval: float
    moving_strikes: tuple[float, ...]
    state_5m: str
    state_10m: str
    state_15m: str
    all3_state: All3State
    previous_directional_all3: str | None
    ce_instrument_key: str | None
    pe_instrument_key: str | None
    health_state: str
    health_allowed: bool
    health_reason: str | None
    features: tuple[HorizonFeature, ...]


def _round_atm(spot: float, strike_interval: float) -> float:
    # Mirrors existing research convention: nearest strike interval.
    return round(spot / strike_interval) * strike_interval


def _infer_strike_interval(snapshot: Snapshot) -> float:
    strikes = sorted({float(c.strike) for c in snapshot.catalog})
    diffs = sorted({round(b - a, 10) for a, b in zip(strikes, strikes[1:]) if b > a})
    if not diffs:
        raise ValueError("Cannot infer strike interval from snapshot catalog")
    return diffs[0]


def _quote_index(snapshot: Snapshot):
    contracts = {c.key: c for c in snapshot.catalog}
    quotes = {q.key: q for q in snapshot.quotes}
    out = {}
    for key, c in contracts.items():
        q = quotes.get(key)
        out[(float(c.strike), c.side)] = q
    return out


def _sum_side(snapshot: Snapshot, strikes: Iterable[float], side: str) -> float | None:
    idx = _quote_index(snapshot)
    total = 0.0
    for strike in strikes:
        q = idx.get((float(strike), side))
        if q is None or q.oi is None:
            return None
        total += float(q.oi)
    return total


def _pcr(pe: float | None, ce: float | None) -> float | None:
    if pe is None or ce in (None, 0):
        return None
    return pe / ce


def _state(imbalance: float | None, pcr_change: float | None) -> str:
    if imbalance is None or pcr_change is None:
        return "NA"
    if imbalance > 0 and pcr_change > 0:
        return "BULLISH"
    if imbalance < 0 and pcr_change < 0:
        return "BEARISH"
    return "MIXED"


def _all3(states: tuple[str, str, str]) -> All3State:
    if "NA" in states:
        return "INCOMPLETE"
    if all(x == "BULLISH" for x in states):
        return "BULLISH_ALL_3"
    if all(x == "BEARISH" for x in states):
        return "BEARISH_ALL_3"
    return "MIXED"


def _exact_snapshot(
    history: list[Snapshot],
    target: datetime,
) -> Snapshot | None:
    matches = [s for s in history if s.received_at == target]
    if len(matches) > 1:
        raise ValueError(f"Duplicate exact snapshot at {target.isoformat()}")
    return matches[0] if matches else None


def _atm_instrument_keys(
    snapshot: Snapshot,
    atm: float,
) -> tuple[str | None, str | None]:
    ce = [c.key for c in snapshot.catalog if float(c.strike) == atm and c.side == "CE"]
    pe = [c.key for c in snapshot.catalog if float(c.strike) == atm and c.side == "PE"]
    if len(ce) > 1 or len(pe) > 1:
        raise ValueError("Ambiguous exact ATM contract")
    return (ce[0] if ce else None, pe[0] if pe else None)


class LiveNormalizedFeatureProducerV1:
    """
    Produces the live 5/10/15 ALL_3 feature checkpoint from exact Snapshot history.

    Important:
    - uses the CURRENT moving ATM +/- wings physical strikes
    - compares those SAME physical strikes at T-5/T-10/T-15
    - exact timestamp only
    - no nearest timestamp
    - no nearest strike
    - futures OI is deliberately not calculated here
    """

    def __init__(self, wings: int = 5):
        if wings != 5:
            raise ValueError("V1 is frozen to moving ATM +/-5")
        self.wings = wings
        self.history: list[Snapshot] = []
        self.last_directional_all3: str | None = None

    def add_snapshot(self, snapshot: Snapshot) -> None:
        if self.history and snapshot.received_at <= self.history[-1].received_at:
            raise ValueError("Out-of-order or duplicate snapshot")
        self.history.append(snapshot)

    def build_current(self) -> LiveNormalizedCheckpoint:
        if not self.history:
            raise ValueError("No snapshots available")
        current = self.history[-1]

        health = evaluate_snapshot_health(current)
        allowed, reason = strategy_dependency_gate(health, dependency="ALL3")

        interval = _infer_strike_interval(current)
        atm = _round_atm(current.spot, interval)
        strikes = tuple(
            atm + offset * interval
            for offset in range(-self.wings, self.wings + 1)
        )

        available_catalog_strikes = {float(c.strike) for c in current.catalog}
        if any(s not in available_catalog_strikes for s in strikes):
            allowed = False
            reason = "DATA_HEALTH_ALL3_MISSING_CURRENT_STRIKE_BASKET"

        features = []
        for minutes in HORIZONS_MINUTES:
            current_ce = _sum_side(current, strikes, "CE")
            current_pe = _sum_side(current, strikes, "PE")

            prior = _exact_snapshot(
                self.history,
                current.received_at - timedelta(minutes=minutes),
            )

            if prior is None:
                prior_ce = prior_pe = None
            else:
                prior_ce = _sum_side(prior, strikes, "CE")
                prior_pe = _sum_side(prior, strikes, "PE")

            ce_delta = (
                current_ce - prior_ce
                if current_ce is not None and prior_ce is not None
                else None
            )
            pe_delta = (
                current_pe - prior_pe
                if current_pe is not None and prior_pe is not None
                else None
            )
            imbalance = (
                pe_delta - ce_delta
                if pe_delta is not None and ce_delta is not None
                else None
            )
            prior_pcr = _pcr(prior_pe, prior_ce)
            current_pcr = _pcr(current_pe, current_ce)
            pcr_change = (
                current_pcr - prior_pcr
                if current_pcr is not None and prior_pcr is not None
                else None
            )

            features.append(HorizonFeature(
                horizon_minutes=minutes,
                current_ce_oi=current_ce,
                current_pe_oi=current_pe,
                prior_ce_oi=prior_ce,
                prior_pe_oi=prior_pe,
                ce_delta=ce_delta,
                pe_delta=pe_delta,
                imbalance=imbalance,
                prior_pcr=prior_pcr,
                current_pcr=current_pcr,
                pcr_change=pcr_change,
                state=_state(imbalance, pcr_change),
            ))

        states = tuple(x.state for x in features)
        all3 = _all3(states)  # type: ignore[arg-type]
        previous = self.last_directional_all3
        if all3 in {"BULLISH_ALL_3", "BEARISH_ALL_3"}:
            self.last_directional_all3 = all3

        ce_key, pe_key = _atm_instrument_keys(current, atm)

        if not allowed:
            all3 = "INCOMPLETE"

        return LiveNormalizedCheckpoint(
            model=MODEL,
            session_date=current.received_at.astimezone().date().isoformat(),
            timestamp=current.received_at,
            spot=float(current.spot),
            moving_atm=atm,
            strike_interval=interval,
            moving_strikes=strikes,
            state_5m=features[0].state,
            state_10m=features[1].state,
            state_15m=features[2].state,
            all3_state=all3,
            previous_directional_all3=previous,
            ce_instrument_key=ce_key,
            pe_instrument_key=pe_key,
            health_state=health.state,
            health_allowed=allowed,
            health_reason=reason,
            features=tuple(features),
        )
