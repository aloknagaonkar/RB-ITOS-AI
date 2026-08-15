from __future__ import annotations

from dataclasses import replace

import pandas as pd

from red_bar_lab.services.historical_dri_relevant_coverage import (
    analyze_historical_dri_relevant_coverage as _analyze,
)


def analyze_historical_dri_relevant_coverage(
    coverage: object,
    underlying: pd.DataFrame,
    **kwargs,
):
    """Normalize cached data variants before running the diagnostic audit.

    Older cached datasets may expose title-case/upper-case OHLC names or aliases
    such as LTP/last_price. Live-capture coverage can also be authoritative for
    replay readiness without exposing per-contract strike rows. Neither condition
    should change strategy decisions; this adapter only prevents a false
    ``INSUFFICIENT_AUDIT_DATA`` diagnostic.
    """

    frame = underlying.copy() if underlying is not None else pd.DataFrame()
    if not frame.empty:
        normalized = {
            str(column).strip().lower().replace(" ", "_"): column
            for column in frame.columns
        }
        aliases = {
            "open": ("open", "opening_price"),
            "high": ("high", "day_high", "high_price"),
            "low": ("low", "day_low", "low_price"),
            "close": (
                "close",
                "closing_price",
                "price",
                "ltp",
                "last_price",
                "last_traded_price",
                "underlying_price",
                "spot",
                "spot_price",
            ),
        }
        for target, candidates in aliases.items():
            if target in frame.columns:
                continue
            source = next(
                (normalized[name] for name in candidates if name in normalized),
                None,
            )
            if source is not None:
                frame[target] = frame[source]

    result = _analyze(coverage, frame, **kwargs)

    # The normal replay-readiness service remains authoritative. A date that is
    # already replay-ready through same-day live capture must not be labelled
    # insufficient merely because that aggregate coverage object has no strike
    # rows for this optional diagnostic table.
    if (
        bool(getattr(coverage, "replay_ready", False))
        and result.status == "INSUFFICIENT_AUDIT_DATA"
    ):
        return replace(
            result,
            status="FULL_REPLAY_READY",
            reason=(
                "The authoritative global replay-readiness gate already passes. "
                "Per-contract strike detail is unavailable for this coverage source, "
                "so the contract table is informationally empty."
            ),
        )

    return result
