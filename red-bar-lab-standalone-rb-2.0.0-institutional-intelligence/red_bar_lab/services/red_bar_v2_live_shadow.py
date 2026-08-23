from __future__ import annotations

import logging

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.red_bar_v2_canonical.shadow_runtime import (
    ReplayEventLike,
    build_runtime_market_metadata,
    build_runtime_source_replay_id,
    build_shadow_task,
    get_red_bar_v2_shadow_runtime,
)
from red_bar_lab.services.red_bar_v2_futures_replay_service import MonitoredRedBarV2FuturesReplayResult

_LOGGER = logging.getLogger(__name__)


def _latest_admission_event(monitored: MonitoredRedBarV2FuturesReplayResult) -> ReplayEventLike | None:
    candidates = tuple(event for event in monitored.replay.events if event.event_type == "CANDIDATE_ADMISSION")
    return max(candidates, key=lambda item: item.timestamp) if candidates else None


def submit_latest_live_canonical_shadow(
    *,
    monitored: MonitoredRedBarV2FuturesReplayResult,
    settings: RedBarSettings,
    instrument_key: str,
    futures_instrument_key: str,
    futures_expiry: str | None,
) -> bool:
    try:
        runtime = get_red_bar_v2_shadow_runtime(
            enabled=settings.red_bar_v2_canonical_shadow_enabled,
            database_path=settings.database_path,
        )
        if runtime is None:
            return False
        event = _latest_admission_event(monitored)
        if event is None:
            return False
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
            build_shadow_task(
                replay=monitored.replay,
                health=monitored.health,
                replay_event=event,
                market_metadata=metadata,
                source_replay_id=source_replay_id,
            )
        )
    except Exception:
        _LOGGER.exception("red_bar_v2_live_shadow_submission_failed")
        return False
