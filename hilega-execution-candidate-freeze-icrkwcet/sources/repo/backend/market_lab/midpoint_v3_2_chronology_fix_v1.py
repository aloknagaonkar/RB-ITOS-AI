"""Chronology-correct frozen-exit validation helper.

Drop-in replacement chronology functions for
midpoint_v3_2_frozen_exit_validation_v1.py.

Why
---
The original V1 validation sorted cumulative results by:
    (session_date, direction)

That is deterministic but is not guaranteed to be the true intraday order when
more than one confirmed trade occurs on the same session date.

This patch requires exact `entry_timestamp` in the exit-research rows and uses
it for cumulative P&L, max-consecutive-loss, and max-drawdown ordering.

No trading logic changes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

def chronology_key(row: dict[str, Any]) -> tuple[str, str, str]:
    entry_ts = str(row.get("entry_timestamp") or "")
    if not entry_ts:
        raise ValueError(
            "entry_timestamp missing; rerun exit-management research with "
            "chronology patch before computing drawdown/streak metrics"
        )
    return (
        entry_ts,
        str(row.get("direction") or ""),
        str(row.get("session_date") or ""),
    )

def validate_chronology_rows(rows: list[dict[str, Any]]) -> None:
    missing = [r for r in rows if not r.get("entry_timestamp")]
    if missing:
        raise ValueError(
            f"{len(missing)} row(s) missing entry_timestamp; chronology metrics "
            "would be ambiguous"
        )

    for r in rows:
        # Validate parseability without normalizing or changing timezone.
        datetime.fromisoformat(str(r["entry_timestamp"]).replace("Z", "+00:00"))
