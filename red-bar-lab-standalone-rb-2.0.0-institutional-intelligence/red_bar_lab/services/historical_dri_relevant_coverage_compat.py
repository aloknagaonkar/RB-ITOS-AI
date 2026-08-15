from __future__ import annotations

import pandas as pd

from red_bar_lab.services.historical_dri_relevant_coverage import (
    analyze_historical_dri_relevant_coverage as _analyze,
)


def analyze_historical_dri_relevant_coverage(
    coverage: object,
    underlying: pd.DataFrame,
    **kwargs,
):
    """Normalize historical price-column variants before running the audit.

    Older cached datasets may expose title-case/upper-case OHLC names or aliases
    such as LTP/last_price. The core audit expects lower-case OHLC columns. This
    adapter is diagnostic-only and does not change replay readiness or strategy
    decisions.
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

    return _analyze(coverage, frame, **kwargs)
