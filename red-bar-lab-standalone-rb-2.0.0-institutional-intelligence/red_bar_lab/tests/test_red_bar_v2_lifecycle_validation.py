from datetime import datetime, timedelta, timezone

from red_bar_lab.services.red_bar_v2_historical_replay import (
    ReplayEvent,
    RedBarV2ReplayResult,
)
from red_bar_lab.services.red_bar_v2_lifecycle_validation import (
    summarize_replay_event_episodes,
)


def _event(minute: int, code: str, *, allowed: bool = False) -> ReplayEvent:
    return ReplayEvent(
        timestamp=datetime(2026, 8, 18, 9, minute, tzinfo=timezone.utc),
        event_type="CANDIDATE_ADMISSION",
        direction="BEARISH",
        option_side="PE",
        admission_code=code,
        candidate_allowed=allowed,
        trade_id=None,
        details={},
    )


def test_repeated_active_trade_blocks_form_one_episode():
    replay = RedBarV2ReplayResult(
        instrument_key="NIFTY",
        trading_date="2026-08-18",
        reference_timestamp=None,
        reference_midpoint=None,
        events=(
            _event(45, "ACTIVE_TRADE_BLOCK"),
            _event(46, "ACTIVE_TRADE_BLOCK"),
            _event(47, "ACTIVE_TRADE_BLOCK"),
            ReplayEvent(
                timestamp=datetime(2026, 8, 18, 9, 48, tzinfo=timezone.utc),
                event_type="TRADE_CLOSED",
                direction="BULLISH",
                option_side="CE",
                admission_code=None,
                candidate_allowed=None,
                trade_id="RBV2-0001",
                details={},
            ),
            _event(49, "REVERSAL_CONTEXT_ALIGNED_FLAT", allowed=True),
        ),
        admitted_candidates=2,
        blocked_candidates=3,
        closed_trades=1,
        final_trade_state="ACTIVE",
    )

    episodes = summarize_replay_event_episodes(replay)

    assert len(episodes) == 3
    assert episodes[0].admission_code == "ACTIVE_TRADE_BLOCK"
    assert episodes[0].occurrences == 3
    assert episodes[0].first_timestamp.minute == 45
    assert episodes[0].last_timestamp.minute == 47
    assert episodes[1].event_type == "TRADE_CLOSED"
    assert episodes[2].candidate_allowed is True
