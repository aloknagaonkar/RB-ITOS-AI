from __future__ import annotations

import hashlib
import re

import pandas as pd


def _token(value: object) -> str:
    text = re.sub(r"[^A-Z0-9]+", "-", str(value or "").upper()).strip("-")
    return text or "UNKNOWN"


def _time_token(value: object) -> str:
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("Asia/Kolkata")
        return ts.strftime("%Y%m%dT%H%M%S")
    except Exception:
        return _token(value)


def _bounded(prefix: str, canonical: str, readable: str) -> str:
    if len(readable) <= 120:
        return readable
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}-{digest}"


def red_bar_bundle_identity(
    *, instrument_key: str, direction: str, reference_timestamp: object, cross_timestamp: object
) -> tuple[str, str]:
    canonical = "|".join(
        ["RED_BAR", instrument_key, direction, str(reference_timestamp), str(cross_timestamp)]
    )
    readable = "-".join(
        ["RB-BND", _token(instrument_key), _token(direction), _time_token(reference_timestamp), _time_token(cross_timestamp)]
    )
    return _bounded("RB-BND", canonical, readable), canonical


def rsi_bundle_identity(
    *, instrument_key: str, direction: str, extreme_timestamp: object, confirmation_timestamp: object
) -> tuple[str, str]:
    canonical = "|".join(
        ["RSI_EXTREME_REVERSAL", instrument_key, direction, str(extreme_timestamp), str(confirmation_timestamp)]
    )
    readable = "-".join(
        ["RSI-BND", _token(instrument_key), _token(direction), _time_token(extreme_timestamp), _time_token(confirmation_timestamp)]
    )
    return _bounded("RSI-BND", canonical, readable), canonical


def directional_regime_bundle_identity(
    *, instrument_key: str, transition_id: object, detected_at: object, direction: str
) -> tuple[str, str]:
    canonical = "|".join(
        ["DIRECTIONAL_REGIME", instrument_key, str(transition_id), str(detected_at), direction]
    )
    readable = "-".join(
        ["DRI-BND", _token(instrument_key), _token(transition_id), _time_token(detected_at), _token(direction)]
    )
    return _bounded("DRI-BND", canonical, readable), canonical
