from __future__ import annotations

from datetime import datetime
from time import perf_counter
from zoneinfo import ZoneInfo

import pandas as pd


IST = ZoneInfo("Asia/Kolkata")


def section_timer() -> float:
    return perf_counter()


def elapsed_ms(started_at: float) -> float:
    return max(0.0, (perf_counter() - started_at) * 1000.0)


def latest_frame_timestamp(frame: pd.DataFrame) -> object | None:
    if frame.empty or "timestamp" not in frame.columns:
        return None
    values = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True).dropna()
    return values.max() if not values.empty else None


def latest_timestamp(*values: object) -> object | None:
    timestamps: list[pd.Timestamp] = []
    for value in values:
        if value in (None, ""):
            continue
        try:
            ts = pd.Timestamp(value)
            if ts.tzinfo is None:
                ts = ts.tz_localize(IST)
            else:
                ts = ts.tz_convert(IST)
            timestamps.append(ts)
        except (TypeError, ValueError):
            continue
    return max(timestamps) if timestamps else None


def format_timestamp(value: object | None) -> str:
    if value in (None, ""):
        return "Not recorded"
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        return ts.strftime("%d-%b-%Y %H:%M:%S IST")
    except (TypeError, ValueError):
        return "Not recorded"


def display_timestamp() -> str:
    return datetime.now(IST).strftime("%d-%b-%Y %H:%M:%S IST")


def render_timing_caption(st, *, refreshed_at: object | None, prepared_ms: float) -> None:
    st.caption(
        f"Data refreshed: {format_timestamp(refreshed_at)} · "
        f"Prepared in: {prepared_ms:.1f} ms · "
        f"Displayed: {display_timestamp()}"
    )


def render_option_positioning_summary(st, directional_bias: object) -> None:
    st.markdown("#### Option Positioning Interpretation")
    bullish, bearish = st.columns(2)
    with bullish:
        st.markdown("**Bullish evidence**")
        st.caption("Put OI addition → bullish evidence")
        st.caption("Call OI unwinding → bullish evidence")
    with bearish:
        st.markdown("**Bearish evidence**")
        st.caption("Call OI addition → bearish evidence")
        st.caption("Put OI unwinding → bearish evidence")
    st.caption(f"Current option conclusion: {directional_bias or 'UNAVAILABLE'}")


def timing_rows(
    *,
    section_name: str,
    refreshed_at: object | None,
    prepared_ms: float,
    collector_duration: object | None = None,
) -> list[dict[str, str]]:
    return [
        {
            "measurement": section_name,
            "value": f"{prepared_ms:.1f} ms",
            "detail": "Time spent reading, preparing and building this section",
        },
        {
            "measurement": "Latest source refresh",
            "value": format_timestamp(refreshed_at),
            "detail": "Newest timestamp among the data sources used by this section",
        },
        {
            "measurement": "Collector duration",
            "value": str(collector_duration) if collector_duration not in (None, "") else "Not recorded",
            "detail": "Displayed only when persisted collector timing is available",
        },
        {
            "measurement": "Displayed",
            "value": display_timestamp(),
            "detail": "Time this Streamlit section was rendered",
        },
    ]
