from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from red_bar_lab.domain.red_bar_v2 import AdmissionOutcome, BundleLifecycleStatus, RedBarV2SignalBundle

from .reservation_models import ReservationEligibility

INDIA_MARKET_TZ = ZoneInfo("Asia/Kolkata")
CLOCK_SKEW_SECONDS = 5.0
DEFAULT_MAX_BUNDLE_AGE_SECONDS = 120.0


def evaluate_reservation_eligibility(
    *,
    bundle: RedBarV2SignalBundle,
    evaluated_at: datetime,
    feature_enabled: bool,
    maximum_age_seconds: float = DEFAULT_MAX_BUNDLE_AGE_SECONDS,
    has_bundle_available_event: bool = True,
    terminally_rejected: bool = False,
) -> ReservationEligibility:
    if not feature_enabled:
        return ReservationEligibility(False, "FEATURE_DISABLED", "Canonical reservation is disabled.")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        return ReservationEligibility(False, "INTEGRITY_FAILED", "Evaluation time must be timezone-aware.")
    if bundle.strategy_id != "RED_BAR_V2":
        return ReservationEligibility(False, "IDENTITY_MISMATCH", "Bundle strategy is not RED_BAR_V2.")
    if bundle.lifecycle_status is not BundleLifecycleStatus.AVAILABLE:
        return ReservationEligibility(False, "BUNDLE_NOT_AVAILABLE", "Bundle lifecycle is not AVAILABLE.")
    if bundle.decision.admission_outcome is not AdmissionOutcome.ALLOWED:
        return ReservationEligibility(False, "ADMISSION_NOT_ALLOWED", "Canonical admission is not ALLOWED.")
    if terminally_rejected:
        return ReservationEligibility(False, "TERMINAL_REJECTION", "Bundle was terminally rejected.")
    if not has_bundle_available_event:
        return ReservationEligibility(False, "INTEGRITY_FAILED", "BUNDLE_AVAILABLE evidence is missing.")
    now = evaluated_at.astimezone(INDIA_MARKET_TZ)
    created = bundle.created_at.astimezone(INDIA_MARKET_TZ)
    age = (now - created).total_seconds()
    if age < -CLOCK_SKEW_SECONDS:
        return ReservationEligibility(False, "BUNDLE_IN_FUTURE", "Bundle is materially in the future.")
    if age > maximum_age_seconds:
        return ReservationEligibility(False, "BUNDLE_TOO_OLD", "Bundle is outside the reservation-age threshold.")
    return ReservationEligibility(True, "ELIGIBLE", "Verified AVAILABLE bundle is eligible for an ownership lease.")
