from __future__ import annotations

from typing import Iterable, Mapping


DRI_SOURCES = {
    "DIRECTIONAL_REGIME_INTELLIGENCE",
    "EARLY_1M_DIRECTIONAL_REGIME",
}

EXPLICIT_OPPOSITE = {
    "OPPOSITE",
    "CONFLICT",
    "OPPOSITE_RED_BAR",
}

NON_BLOCKING = {
    "",
    "NA",
    "N/A",
    "NONE",
    "NOT_AVAILABLE",
    "UNAVAILABLE",
    "NEUTRAL",
    "ALIGNED",
    "SUPPORTING",
}


def is_dri_signal(signal: Mapping[str, object]) -> bool:
    source = str(
        signal.get("signal_source")
        or signal.get("source")
        or ""
    ).upper().strip()
    signal_id = str(signal.get("signal_id") or "").upper()
    return (
        source in DRI_SOURCES
        or signal_id.startswith("DRI-")
        or signal_id.startswith("DRI-EARLY-")
    )


def explicit_dri_red_bar_opposition(
    signal: Mapping[str, object],
) -> bool:
    alignment = str(
        signal.get("red_bar_alignment") or ""
    ).upper().strip()

    if alignment in NON_BLOCKING:
        return False
    if alignment in EXPLICIT_OPPOSITE:
        return True

    direction = str(signal.get("direction") or "").upper().strip()
    if direction == "BULLISH" and alignment == "BEARISH":
        return True
    if direction == "BEARISH" and alignment == "BULLISH":
        return True
    return False


def resolve_opposite_red_bar(
    *,
    signal: Mapping[str, object],
    signals: Iterable[Mapping[str, object]],
) -> bool:
    if is_dri_signal(signal):
        return explicit_dri_red_bar_opposition(signal)

    signal_id = str(signal.get("signal_id") or "")
    direction = str(signal.get("direction") or "").upper()
    confirmation_timestamp = str(
        signal.get("confirmation_timestamp") or ""
    )
    opposite_direction = (
        "BEARISH" if direction == "BULLISH" else "BULLISH"
    )

    return any(
        not is_dri_signal(item)
        and str(item.get("signal_id") or "") != signal_id
        and str(item.get("direction") or "").upper()
        == opposite_direction
        and bool(item.get("confirmation_timestamp"))
        and str(item.get("confirmation_timestamp") or "")
        > confirmation_timestamp
        for item in signals
    )
