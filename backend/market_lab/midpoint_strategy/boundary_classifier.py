from __future__ import annotations

from dataclasses import dataclass

from .family_b_detector import (
    FamilyBDelayedDetector,
    FamilyBObservation,
)
from .models import MidpointFamily
from .structure import ReferenceStructure, boundary_broken


OTHER_FRESH_A = "OTHER_FRESH_A"


@dataclass(frozen=True)
class BoundaryOwnershipDecision:
    owner: str
    reason: str
    candidate_a_at_boundary: bool
    prior_window_crossed_threshold: bool
    raw_futures_vwap_diff: float
    directional_vwap_diff: float


class MidpointBoundaryClassifierV55:
    """Pure, side-effect-free B/E boundary owner classifier.

    V55 is intentionally not wired into the live coordinator yet.
    It freezes the selection logic so replay parity can be proven first.
    """

    def __init__(self) -> None:
        self.detector = FamilyBDelayedDetector()

    def classify(
        self,
        *,
        reference: ReferenceStructure,
        boundary_observation: FamilyBObservation,
        history: list[FamilyBObservation],
    ) -> BoundaryOwnershipDecision:
        if not boundary_broken(reference, boundary_observation.close):
            raise ValueError("boundary ownership requires a confirmed boundary break")

        full_a, prior_cross = self.detector.full_candidate_a(
            reference,
            boundary_observation,
            history,
        )
        raw = boundary_observation.raw_futures_vwap_diff
        directional = self.detector.directional_vwap_diff(
            reference,
            boundary_observation,
        )

        if full_a:
            return BoundaryOwnershipDecision(
                owner=OTHER_FRESH_A,
                reason="FRESH_CANDIDATE_A_AT_BOUNDARY",
                candidate_a_at_boundary=True,
                prior_window_crossed_threshold=prior_cross,
                raw_futures_vwap_diff=raw,
                directional_vwap_diff=directional,
            )

        mature = directional > self.detector.VWAP_THRESHOLD
        if mature:
            return BoundaryOwnershipDecision(
                owner=MidpointFamily.E.value,
                reason="MATURE_DIRECTIONAL_VWAP_AT_BOUNDARY",
                candidate_a_at_boundary=False,
                prior_window_crossed_threshold=prior_cross,
                raw_futures_vwap_diff=raw,
                directional_vwap_diff=directional,
            )

        return BoundaryOwnershipDecision(
            owner=MidpointFamily.B.value,
            reason="DELAYED_CONFIRMATION_WATCH",
            candidate_a_at_boundary=False,
            prior_window_crossed_threshold=prior_cross,
            raw_futures_vwap_diff=raw,
            directional_vwap_diff=directional,
        )
