from __future__ import annotations

from datetime import date
from typing import Iterable


EXPECTED_PD_LEVELS = tuple(f"PD{rank}_315" for rank in range(1, 11))


def build_pd_startup_readiness(
    available_dates: Iterable[date],
    reference_levels: Iterable[dict[str, object]],
    trading_date: date,
) -> dict[str, object]:
    """Return read-only readiness for live PD signal scanning.

    This does not create levels or change signal behavior. It only explains
    whether the live session currently has enough cached prior sessions and all
    PD1_315..PD10_315 reference levels required by the signal scanner.
    """
    prior_dates = sorted({day for day in available_dates if day < trading_date})
    prior_count = min(10, len(prior_dates))

    present = {
        str(row.get("level_type") or "")
        for row in reference_levels
        if str(row.get("level_type") or "").startswith("PD")
    }
    present_expected = [name for name in EXPECTED_PD_LEVELS if name in present]
    missing = [name for name in EXPECTED_PD_LEVELS if name not in present]

    if prior_count >= 10 and not missing:
        status = "READY"
        detail = (
            "10 prior sessions and all PD1_315..PD10_315 levels are available. "
            "Live PD signal scanning is ready."
        )
    elif prior_count < 10:
        status = "BACKFILLING"
        detail = (
            f"Only {prior_count}/10 prior sessions are cached. Historical context "
            "must finish backfilling before PD live coverage is complete."
        )
    else:
        status = "PARTIAL"
        detail = (
            f"Prior-session cache is sufficient, but only {len(present_expected)}/10 "
            "PD levels are persisted for the live session."
        )

    return {
        "status": status,
        "prior_sessions": prior_count,
        "required_prior_sessions": 10,
        "pd_levels": len(present_expected),
        "required_pd_levels": 10,
        "missing_pd_levels": tuple(missing),
        "detail": detail,
        "signal_scanning_ready": status == "READY",
    }
