from __future__ import annotations

import hashlib


def canonical_signal_id(
    instrument_key: str,
    trading_date: str,
    level_type: str,
    direction: str | None,
    cross_timestamp: str | None,
    confirmation_timestamp: str | None,
) -> str:
    identity = "|".join(
        (
            instrument_key,
            trading_date,
            level_type,
            direction or "NONE",
            cross_timestamp or "NONE",
            confirmation_timestamp or "NONE",
        )
    )
    digest = hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()[:20].upper()
    return f"RB-{digest}"
