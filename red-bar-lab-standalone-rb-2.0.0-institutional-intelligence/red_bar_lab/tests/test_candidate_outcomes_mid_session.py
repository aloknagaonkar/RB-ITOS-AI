import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

os.environ.setdefault("RED_BAR_LEGACY_V1_ENABLED", "1")

import pandas as pd

from red_bar_lab.execution.candidate_lifecycle import CandidateLifecycleManager
from red_bar_lab.strategy.level_engine import build_mid_session_level
from red_bar_lab.strategy.signal_engine import scan_level_signals

IST = ZoneInfo("Asia/Kolkata")


def _candidate(*, vwap=0.0, ema=0.0, momentum=0.0):
    contract = SimpleNamespace(tradingsymbol="NIFTY26AUG25000CE", instrument_token=123)
    return SimpleNamespace(
        contract=contract,
        total_score=80.0,
        vwap_score=vwap,
        ema_score=ema,
        momentum_score=momentum,
    )


def _minute_frame(end: str) -> pd.DataFrame:
    stamps = pd.date_range("2026-08-13 09:15", end, freq="1min", tz="Asia/Kolkata")
    rows = []
    for i, stamp in enumerate(stamps):
        price = 100.0 + i * 0.01
        rows.append({
            "timestamp": stamp.tz_convert("UTC"),
            "open": price,
            "high": price + 0.20,
            "low": price - 0.20,
            "close": price + 0.05,
            "volume": 1,
        })
    return pd.DataFrame(rows)


def test_confirmed_market_drift_is_not_eligible_not_expired():
    manager = CandidateLifecycleManager(freshness_seconds=180)
    now = datetime(2026, 8, 13, 12, 0, tzinfo=IST)
    result = manager.evaluate(
        signal_id="SIG-1",
        confirmation_timestamp=(now - timedelta(minutes=5)).isoformat(),
        now=now,
        candidate=_candidate(),
    )
    assert result.state == "NOT_ELIGIBLE"
    assert result.action == "REJECT_CANDIDATE"
    assert result.replacement_required is False
    assert result.replacement_signal_id is None
    assert result.active is False


def test_duplicate_is_not_eligible():
    now = datetime(2026, 8, 13, 12, 0, tzinfo=IST)
    result = CandidateLifecycleManager().evaluate(
        signal_id="SIG-2",
        confirmation_timestamp=now.isoformat(),
        now=now,
        candidate=_candidate(vwap=10, ema=10, momentum=10),
        duplicate=True,
    )
    assert result.state == "NOT_ELIGIBLE"
    assert result.active is False


def test_mid_session_is_unavailable_until_all_30_minutes_exist():
    partial = _minute_frame("2026-08-13 13:13")
    assert build_mid_session_level(partial) is None

    complete = _minute_frame("2026-08-13 13:14")
    level = build_mid_session_level(complete)
    assert level is not None
    assert level.level_type == "MID_SESSION_1245"
    assert level.interval_minutes == 30
    assert level.source_timestamp.hour == 12
    assert level.source_timestamp.minute == 45


def test_mid_session_retries_after_delayed_minute_arrives():
    complete = _minute_frame("2026-08-13 13:19")
    missing = complete[
        complete["timestamp"].dt.tz_convert("Asia/Kolkata").dt.strftime("%H:%M") != "13:00"
    ].reset_index(drop=True)
    assert build_mid_session_level(missing) is None

    level = build_mid_session_level(complete)
    assert level is not None
    attempts = scan_level_signals(complete, level)
    # The important regression guarantee is that the level is rebuilt and
    # reaches signal scanning once delayed source data becomes complete.
    assert isinstance(attempts, tuple)
