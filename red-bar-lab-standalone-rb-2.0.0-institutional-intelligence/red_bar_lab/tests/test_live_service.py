from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.live_service import (
    RedBarLiveService,
    completed_signal_source,
)
from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.storage.database import RedBarDatabase


IST = ZoneInfo("Asia/Kolkata")


def candles(day: str, end_minute: int = 35) -> pd.DataFrame:
    start = pd.Timestamp(f"{day} 09:15:00", tz=IST)
    rows = []
    for i in range(end_minute - 15):
        ts = start + pd.Timedelta(minutes=i)
        price = 100 + i
        rows.append({
            "timestamp": ts,
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price + 0.5,
            "volume": 0,
            "oi": 0,
        })
    return pd.DataFrame(rows)


class Provider:
    def __init__(self, frame):
        self.frame = frame
        self.intraday_calls = 0

    def intraday_candles(self, instrument_key, interval_minutes=1):
        self.intraday_calls += 1
        return self.frame.copy()

    def historical_candles(self, *args, **kwargs):
        raise AssertionError("today must use intraday candles")


def test_completed_signal_source_excludes_current_five_minute_bucket():
    frame = candles("2026-08-06", 28)  # through 09:27
    now = datetime(2026, 8, 6, 9, 27, tzinfo=IST)
    result = completed_signal_source(frame, now=now)
    local = result["timestamp"].dt.tz_convert(IST)
    assert local.max().time().isoformat() == "09:26:00"


def test_live_refresh_stores_current_session_and_is_idempotent(tmp_path, monkeypatch):
    frame = candles("2026-08-06", 35)
    provider = Provider(frame)
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    layout = ArtifactLayout(settings)
    layout.ensure()
    database = RedBarDatabase(settings.database_path)
    historical = RedBarHistoricalService(provider, layout)

    monkeypatch.setattr(
        "red_bar_lab.services.historical_service.india_today",
        lambda: date(2026, 8, 6),
    )
    service = RedBarLiveService(historical, layout, database)
    now = datetime(2026, 8, 6, 9, 35, tzinfo=IST)

    first = service.refresh("NSE_INDEX|Nifty 50", now=now)
    count1 = len(database.read_signal_attempts(
        "NSE_INDEX|Nifty 50", "2026-08-06"
    ))
    second = service.refresh("NSE_INDEX|Nifty 50", now=now)
    count2 = len(database.read_signal_attempts(
        "NSE_INDEX|Nifty 50", "2026-08-06"
    ))

    assert first.connected and second.connected
    assert provider.intraday_calls == 2
    assert count1 == count2
    assert layout.live_session_path(
        "upstox", "NSE_INDEX|Nifty 50", 1
    ).exists()
    assert layout.candle_path(
        "upstox", "NSE_INDEX|Nifty 50", 1, "2026-08-06"
    ).exists()


def test_live_visibility_explains_timeout():
    from red_bar_lab.services.live_service import _attempt_visibility

    rows = []
    start = pd.Timestamp("2026-08-07 09:25", tz=IST)
    for i in range(5):
        rows.append({
            "timestamp": start + pd.Timedelta(minutes=i),
            "open": 100,
            "high": 104,
            "low": 99,
            "close": 103,
            "volume": 0,
            "oi": 0,
        })
    frame = pd.DataFrame(rows)
    attempt = {
        "level_type": "FIRST_CANDLE",
        "level_value": 100.0,
        "direction": "BULLISH",
        "state": "TIMEOUT",
        "cross_timestamp": "2026-08-07T09:20:00+05:30",
        "cross_high": 105.0,
        "cross_low": 98.0,
        "cross_close": 101.0,
        "confirmation_timestamp": None,
    }
    detail = _attempt_visibility(frame, attempt)
    assert detail["confirmation_candles_checked"] == 5
    assert detail["confirmation_candles_remaining"] == 0
    assert detail["required_price"] == 105.0
    assert detail["reason"] == "TIMEOUT_NO_1M_CLOSE_ABOVE_SETUP_HIGH"


def test_live_visibility_explains_waiting():
    from red_bar_lab.services.live_service import _attempt_visibility

    rows = []
    start = pd.Timestamp("2026-08-07 09:25", tz=IST)
    for i in range(2):
        rows.append({
            "timestamp": start + pd.Timedelta(minutes=i),
            "open": 100,
            "high": 104,
            "low": 99,
            "close": 103,
            "volume": 0,
            "oi": 0,
        })
    frame = pd.DataFrame(rows)
    attempt = {
        "level_type": "NEXT_RED_CANDLE",
        "level_value": 100.0,
        "direction": "BULLISH",
        "state": "AWAITING_CONFIRMATION",
        "cross_timestamp": "2026-08-07T09:20:00+05:30",
        "cross_high": 105.0,
        "cross_low": 98.0,
        "cross_close": 101.0,
        "confirmation_timestamp": None,
    }
    detail = _attempt_visibility(frame, attempt)
    assert detail["confirmation_candles_checked"] == 2
    assert detail["confirmation_candles_remaining"] == 3
    assert detail["reason"] == "WAITING_FOR_1M_CLOSE_ABOVE_SETUP_HIGH"


def test_live_points_directional():
    from red_bar_lab.services.live_service import _live_points
    assert _live_points("BULLISH", 100, 112) == 12
    assert _live_points("BEARISH", 100, 88) == 12
    assert _live_points("BEARISH", 100, 105) == -5



def test_target_progress_uses_best_favorable_move():
    from red_bar_lab.services.live_service import _target_progress

    result = _target_progress(35, 47)
    assert result["targets_hit"] == "20,30,40"
    assert result["next_target"] == 50
    assert result["points_to_next_target"] == 15
