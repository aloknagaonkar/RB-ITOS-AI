from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

import pandas as pd


def compare_shadow_to_current_engine(
    shadow_rows: Iterable[Mapping[str, object]],
    current_signal_rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Compare nearest same-direction current-engine confirmation after shadow."""
    signals = list(current_signal_rows)
    results = []
    for shadow in shadow_rows:
        shadow_ts = pd.Timestamp(
            shadow.get("candle_timestamp") or shadow.get("timestamp")
        )
        direction = str(shadow.get("direction") or "")
        eligible = []
        for signal in signals:
            signal_direction = str(signal.get("direction") or "")
            raw_ts = signal.get("confirmation_timestamp")
            if signal_direction != direction or not raw_ts:
                continue
            signal_ts = pd.Timestamp(raw_ts)
            if signal_ts >= shadow_ts:
                eligible.append((signal_ts, signal))
        eligible.sort(key=lambda item: item[0])

        current_ts = eligible[0][0] if eligible else None
        lead = None
        if current_ts is not None:
            lead = round((current_ts - shadow_ts).total_seconds() / 60.0, 2)

        results.append(
            {
                **dict(shadow),
                "current_engine_direction": direction if current_ts is not None else None,
                "current_engine_confirmation_timestamp": (
                    current_ts.isoformat() if current_ts is not None else None
                ),
                "shadow_lead_minutes": lead,
                "shadow_was_earlier": lead is not None and lead > 0,
                "execution_allowed": False,
            }
        )
    return results
