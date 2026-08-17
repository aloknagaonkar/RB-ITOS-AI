from __future__ import annotations

from functools import wraps
from typing import Mapping

import pandas as pd


def confirmation_candle_index(
    frame: pd.DataFrame,
    latest_signal: Mapping[str, object],
) -> int:
    """Resolve a signal close-time timestamp to its one-minute candle-open row.

    RSI signals are confirmed at the end of the completed one-minute candle,
    while stored candle timestamps represent the candle open. The primary
    lookup therefore subtracts one minute. Exact open-time matching is retained
    as a compatibility fallback for older signal records.

    A confirmed signal that cannot be aligned returns ``-1`` rather than
    silently falling back to the latest candle and mixing two evaluations.
    """
    if not latest_signal:
        return len(frame) - 1

    raw_timestamp = latest_signal.get("confirmation_timestamp")
    if raw_timestamp in (None, ""):
        return -1

    try:
        signal_ts = pd.Timestamp(raw_timestamp)
        if signal_ts.tzinfo is None:
            signal_ts = signal_ts.tz_localize("UTC")
        else:
            signal_ts = signal_ts.tz_convert("UTC")
    except (TypeError, ValueError):
        return -1

    candidates = (
        signal_ts - pd.Timedelta(minutes=1),
        signal_ts,
    )
    for candidate in candidates:
        matches = frame.index[frame["timestamp"] == candidate].tolist()
        if matches:
            return int(matches[-1])
    return -1


def build_aligned_rsi_setup_state(original_builder):
    """Keep RSI confirmation explanation tied to the selected signal event."""

    @wraps(original_builder)
    def wrapped(*args, **kwargs):
        result = dict(original_builder(*args, **kwargs) or {})
        trace = dict(result.get("decision_trace") or {})
        if result.get("status") == "CONFIRMED" and trace:
            trace["trace_scope"] = "CONFIRMED_SIGNAL_EVENT"
            trace["next_step"] = (
                "This trace explains the confirmed RSI signal event. "
                "Use Sections 3 and 4 for current bundle lifecycle and eligibility."
            )
            result["waiting_for"] = (
                "Current bundle lifecycle and execution-source gate evaluation"
            )
            result["blocker"] = (
                "None at signal-confirmation time; current lifecycle is shown "
                "in Sections 3 and 4"
            )
            result["decision_trace"] = trace
        return result

    return wrapped


def install_rsi_decision_trace_alignment(page_module) -> None:
    """Install the alignment without rewriting the stable detector module."""
    import red_bar_lab.ui.strategy_setup_detection as setup_detection

    setup_detection._evaluation_index = confirmation_candle_index
    page_module.build_rsi_setup_state = build_aligned_rsi_setup_state(
        page_module.build_rsi_setup_state
    )
