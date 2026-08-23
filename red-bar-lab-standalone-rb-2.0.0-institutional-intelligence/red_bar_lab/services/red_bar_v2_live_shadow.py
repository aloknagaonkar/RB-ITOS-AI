from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from red_bar_lab.services.red_bar_v2_canonical.shadow_runtime import (
    RedBarV2ShadowTask,
    build_runtime_market_metadata,
    build_runtime_source_replay_id,
    get_red_bar_v2_shadow_runtime,
)

_LOGGER = logging.getLogger(__name__)


def submit_latest_live_canonical_shadow(
    *,
    monitored: Any,
    settings: Any,
    instrument_key: str,
    futures_instrument_key: str,
    futures_expiry: str | None,
) -> bool:
    """Submit only the newest live admission event; research callers never invoke this."""
    try:
        runtime = get_red_bar_v2_shadow_runtime(
            enabled=bool(settings.red_bar_v2_canonical_shadow_enabled),
            database_path=Path(settings.database_path),
        )
        if runtime is None:
            return False

        candidates = tuple(
            event
            for event in monitored.replay.events
            if str(getattr(event, "event_type", "")) == "CANDIDATE_ADMISSION"
        )
        if not candidates:
            return False
        event = max(candidates, key=lambda item: item.timestamp)
        metadata = build_runtime_market_metadata(
            replay=monitored.replay,
            health=monitored.health,
            event=event,
            instrument_key=instrument_key,
            futures_instrument_key=futures_instrument_key,
            futures_expiry=futures_expiry,
        )
        source_replay_id = build_runtime_source_replay_id(
            instrument_key=instrument_key,
            trading_date=monitored.replay.trading_date,
            event=event,
        )
        return runtime.submit(
            RedBarV2ShadowTask(
                replay=monitored.replay,
                health=monitored.health,
                replay_event=event,
                market_metadata=metadata,
                source_replay_id=source_replay_id,
                event_timestamp=event.timestamp,
            )
        )
    except Exception:
        _LOGGER.exception("red_bar_v2_live_shadow_submission_failed")
        return False
