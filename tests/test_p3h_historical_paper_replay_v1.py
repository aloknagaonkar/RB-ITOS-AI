from datetime import datetime
from zoneinfo import ZoneInfo

from market_lab.paper_historical_replay_v1 import (
    ReplaySessionResult,
    _norm5,
    summarize,
)

IST = ZoneInfo("Asia/Kolkata")


def test_norm5_floors_to_checkpoint():
    ts = datetime(2026, 9, 16, 10, 34, 59, tzinfo=IST)
    got = _norm5(ts)
    assert got.hour == 10
    assert got.minute == 30
    assert got.second == 0


def test_summary_counts_sessions_and_states():
    a = ReplaySessionResult(
        session_date="2026-08-25",
        p1_count=2,
        wait_p2_count=1,
        p2_confirmed_count=1,
        p2_failed_count=0,
        vwap_reject_count=1,
        feature_block_count=0,
    )
    b = ReplaySessionResult(
        session_date="2026-09-08",
        p1_count=3,
        wait_p2_count=2,
        p2_confirmed_count=1,
        p2_failed_count=1,
        vwap_reject_count=1,
        feature_block_count=1,
    )
    assert summarize([a, b]) == {
        "sessions": 2,
        "p1_count": 5,
        "wait_p2_count": 3,
        "p2_confirmed_count": 2,
        "p2_failed_count": 1,
        "vwap_reject_count": 2,
        "feature_block_count": 1,
    }
