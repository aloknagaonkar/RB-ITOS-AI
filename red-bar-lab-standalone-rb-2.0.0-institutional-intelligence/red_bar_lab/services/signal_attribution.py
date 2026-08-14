from __future__ import annotations

from typing import Mapping


def attach_signal_to_attribution(
    attribution: Mapping[str, object],
    signal: Mapping[str, object],
) -> dict[str, object]:
    payload = dict(attribution)
    payload.update(
        {
            "signal_id": signal.get("signal_id"),
            "primary_trigger": signal.get("setup_type"),
            "supporting_signals": signal.get("supporting_evidence") or [],
            "execution_allowed": False,
        }
    )
    return payload
