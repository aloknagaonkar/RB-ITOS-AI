from datetime import date, datetime, timedelta
from types import SimpleNamespace
import pytest
from market_lab.domain import IST
from market_lab import hilega_milega_historical_replay_v1 as replay
from market_lab.live_shadow_worker_v1 import process_isolated_tick
from market_lab.midpoint_strategy import live_shadow_ui as ui


def candles(day):
    start = datetime.combine(day, datetime.min.time(), IST).replace(hour=9, minute=15)
    return [SimpleNamespace(timestamp=start + timedelta(minutes=i),
                            open=100, high=101, low=99, close=100, volume=1)
            for i in range(375)]


def test_failure_does_not_starve_midpoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen = []
    def broken(now):
        raise ValueError("credential must not appear in logs")
    result = process_isolated_tick(datetime.now(IST),
                                   [("hilega", broken), ("midpoint", lambda now: seen.append(now))])
    assert len(seen) == 1 and result == {"hilega": "ValueError", "midpoint": "OK"}


def test_incomplete_cache_refetched_before_write(tmp_path, monkeypatch):
    day = date(2026, 10, 6)
    complete = candles(day)
    monkeypatch.setattr(replay, "load_or_fetch_1m", lambda *a, **k: complete[:-1])
    written = []
    monkeypatch.setattr(replay, "_write_cache", lambda *a: written.append(a))
    gateway = SimpleNamespace(historical_candles=lambda *a: complete)
    assert len(replay.load_validated_warmup_1m(gateway, underlying=replay.UNDERLYING,
               session_date=day, cache_root=tmp_path)) == 375
    assert len(written) == 1
    gateway.historical_candles = lambda *a: complete[:-1]
    with pytest.raises(ValueError):
        replay.load_validated_warmup_1m(gateway, underlying=replay.UNDERLYING,
                                       session_date=day, cache_root=tmp_path)
    assert len(written) == 1


def test_event_timeline_has_no_synthetic_minutes(monkeypatch):
    events = [{"event_id": "two"}, {"event_id": "one"}]
    monkeypatch.setattr(ui, "_all_rows", lambda *a: [])
    monkeypatch.setattr(ui, "_decision_timeline_projection", lambda *a: events)
    monkeypatch.setattr(ui, "_market_health_timeline", lambda *a: pytest.fail("synthetic health rows requested"))
    assert ui._combined_live_timeline() == events
