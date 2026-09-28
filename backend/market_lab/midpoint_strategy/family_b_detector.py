from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .structure import ReferenceStructure, boundary_broken, structure_still_valid


@dataclass(frozen=True)
class FamilyBObservation:
    timestamp: str
    close: float
    futures_price: float
    futures_vwap: float

    @property
    def raw_futures_vwap_diff(self) -> float:
        return self.futures_price - self.futures_vwap


@dataclass
class FamilyBWatch:
    reference: ReferenceStructure
    boundary_break_timestamp: str
    original_boundary: float
    original_full_candidate_a: bool
    active: bool = True
    confirmed_timestamp: Optional[str] = None


@dataclass(frozen=True)
class FamilyBDecision:
    result: str
    reason: str
    full_candidate_a: bool
    directional_vwap_diff: float
    prior_window_crossed_threshold: bool
    still_beyond_original_boundary: bool
    structure_valid: bool
    minutes_since_boundary_break: float


class FamilyBDelayedDetector:
    """Frozen B_DELAYED_FULL_CANDIDATE_A detector.

    Family B exists only when the original structural boundary event did NOT
    already have full Candidate A.

    Within max 10 minutes:
    - same directional structure remains valid,
    - close remains beyond the ORIGINAL boundary,
    - full Candidate A appears later.

    Candidate A directional VWAP condition:
    BEARISH:
        current raw futures-VWAP diff < -5
        and some prior observation from T-5..T had diff >= -5
    BULLISH:
        current raw futures-VWAP diff > +5
        and some prior observation from T-5..T had diff <= +5
    """

    MAX_DELAY_MINUTES = 10
    LOOKBACK_MINUTES = 5
    VWAP_THRESHOLD = 5.0

    @staticmethod
    def _dt(ts: str) -> datetime:
        return datetime.fromisoformat(ts)

    def directional_vwap_diff(
        self, reference: ReferenceStructure, obs: FamilyBObservation
    ) -> float:
        raw = obs.raw_futures_vwap_diff
        return raw if reference.direction == "BULLISH" else -raw

    def full_candidate_a(
        self,
        reference: ReferenceStructure,
        current: FamilyBObservation,
        history: list[FamilyBObservation],
    ) -> tuple[bool, bool]:
        now = self._dt(current.timestamp)
        start = now - timedelta(minutes=self.LOOKBACK_MINUTES)
        prior = [
            h for h in history
            if start <= self._dt(h.timestamp) <= now
        ]

        raw_now = current.raw_futures_vwap_diff

        if reference.direction == "BEARISH":
            prior_cross = any(h.raw_futures_vwap_diff >= -self.VWAP_THRESHOLD for h in prior)
            full = raw_now < -self.VWAP_THRESHOLD and prior_cross
        else:
            prior_cross = any(h.raw_futures_vwap_diff <= self.VWAP_THRESHOLD for h in prior)
            full = raw_now > self.VWAP_THRESHOLD and prior_cross

        return full, prior_cross

    def start_watch(
        self,
        reference: ReferenceStructure,
        boundary_break_observation: FamilyBObservation,
        history: list[FamilyBObservation],
    ) -> FamilyBWatch:
        if not boundary_broken(reference, boundary_break_observation.close):
            raise ValueError("cannot start Family B watch without boundary break")

        original_a, _ = self.full_candidate_a(
            reference, boundary_break_observation, history
        )

        return FamilyBWatch(
            reference=reference,
            boundary_break_timestamp=boundary_break_observation.timestamp,
            original_boundary=reference.boundary,
            original_full_candidate_a=original_a,
            active=not original_a,
        )

    def evaluate(
        self,
        watch: FamilyBWatch,
        current: FamilyBObservation,
        history: list[FamilyBObservation],
    ) -> FamilyBDecision:
        ref = watch.reference
        delta = (
            self._dt(current.timestamp)
            - self._dt(watch.boundary_break_timestamp)
        ).total_seconds() / 60.0

        if watch.original_full_candidate_a:
            return FamilyBDecision(
                result="NO_B",
                reason="ORIGINAL_EVENT_ALREADY_FULL_CANDIDATE_A",
                full_candidate_a=True,
                directional_vwap_diff=self.directional_vwap_diff(ref, current),
                prior_window_crossed_threshold=False,
                still_beyond_original_boundary=boundary_broken(ref, current.close),
                structure_valid=structure_still_valid(ref, current.close),
                minutes_since_boundary_break=delta,
            )

        if delta < 0 or delta > self.MAX_DELAY_MINUTES:
            watch.active = False
            return FamilyBDecision(
                result="EXPIRED",
                reason="B_DELAY_WINDOW_EXPIRED",
                full_candidate_a=False,
                directional_vwap_diff=self.directional_vwap_diff(ref, current),
                prior_window_crossed_threshold=False,
                still_beyond_original_boundary=boundary_broken(ref, current.close),
                structure_valid=structure_still_valid(ref, current.close),
                minutes_since_boundary_break=delta,
            )

        valid = structure_still_valid(ref, current.close)
        beyond = boundary_broken(ref, current.close)

        if not valid:
            watch.active = False
            return FamilyBDecision(
                result="INVALIDATED",
                reason="DIRECTIONAL_STRUCTURE_INVALIDATED",
                full_candidate_a=False,
                directional_vwap_diff=self.directional_vwap_diff(ref, current),
                prior_window_crossed_threshold=False,
                still_beyond_original_boundary=beyond,
                structure_valid=False,
                minutes_since_boundary_break=delta,
            )

        full_a, prior_cross = self.full_candidate_a(ref, current, history)

        if beyond and full_a:
            watch.active = False
            watch.confirmed_timestamp = current.timestamp
            return FamilyBDecision(
                result="ENTRY",
                reason="B_DELAYED_FULL_CANDIDATE_A",
                full_candidate_a=True,
                directional_vwap_diff=self.directional_vwap_diff(ref, current),
                prior_window_crossed_threshold=prior_cross,
                still_beyond_original_boundary=True,
                structure_valid=True,
                minutes_since_boundary_break=delta,
            )

        reason = (
            "WAITING_FOR_FULL_CANDIDATE_A"
            if beyond else
            "NO_LONGER_BEYOND_ORIGINAL_BOUNDARY"
        )
        return FamilyBDecision(
            result="WAIT",
            reason=reason,
            full_candidate_a=full_a,
            directional_vwap_diff=self.directional_vwap_diff(ref, current),
            prior_window_crossed_threshold=prior_cross,
            still_beyond_original_boundary=beyond,
            structure_valid=valid,
            minutes_since_boundary_break=delta,
        )
