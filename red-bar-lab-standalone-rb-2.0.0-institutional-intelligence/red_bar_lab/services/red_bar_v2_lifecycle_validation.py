from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from red_bar_lab.services.red_bar_v2_historical_replay import ReplayEvent, RedBarV2ReplayResult


@dataclass(frozen=True)
class ReplayEventEpisode:
    first_timestamp: datetime
    last_timestamp: datetime
    event_type: str
    direction: str | None
    option_side: str | None
    admission_code: str | None
    candidate_allowed: bool | None
    occurrences: int


def summarize_replay_event_episodes(
    replay: RedBarV2ReplayResult,
) -> tuple[ReplayEventEpisode, ...]:
    """Collapse consecutive duplicate admission outcomes for validation reports.

    Raw replay events remain unchanged. Only consecutive events with the same
    lifecycle meaning are summarized, primarily repeated ACTIVE_TRADE_BLOCK
    observations while an opposite reversal remains pending.
    """
    episodes: list[ReplayEventEpisode] = []

    def key(event: ReplayEvent) -> tuple[object, ...]:
        return (
            event.event_type,
            event.direction,
            event.option_side,
            event.admission_code,
            event.candidate_allowed,
            event.trade_id,
        )

    for event in replay.events:
        if episodes:
            previous = episodes[-1]
            previous_key = (
                previous.event_type,
                previous.direction,
                previous.option_side,
                previous.admission_code,
                previous.candidate_allowed,
                None,
            )
            event_key = key(event)
            can_collapse = (
                event.admission_code == "ACTIVE_TRADE_BLOCK"
                and previous.admission_code == "ACTIVE_TRADE_BLOCK"
                and event_key[:-1] == previous_key[:-1]
            )
            if can_collapse:
                episodes[-1] = ReplayEventEpisode(
                    first_timestamp=previous.first_timestamp,
                    last_timestamp=event.timestamp,
                    event_type=previous.event_type,
                    direction=previous.direction,
                    option_side=previous.option_side,
                    admission_code=previous.admission_code,
                    candidate_allowed=previous.candidate_allowed,
                    occurrences=previous.occurrences + 1,
                )
                continue

        episodes.append(
            ReplayEventEpisode(
                first_timestamp=event.timestamp,
                last_timestamp=event.timestamp,
                event_type=event.event_type,
                direction=event.direction,
                option_side=event.option_side,
                admission_code=event.admission_code,
                candidate_allowed=event.candidate_allowed,
                occurrences=1,
            )
        )

    return tuple(episodes)
