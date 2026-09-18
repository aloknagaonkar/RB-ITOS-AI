from datetime import date, datetime, timedelta

from market_lab.domain import IST
from market_lab.historical_replay_sources_v1 import (
    HistoricalReplayMarketSourcesV1,
    _futures_state,
)


def test_futures_state_mapping_is_frozen():
    assert _futures_state(1, 1) == "LONG_BUILDUP"
    assert _futures_state(-1, 1) == "SHORT_BUILDUP"
    assert _futures_state(1, -1) == "SHORT_COVERING"
    assert _futures_state(-1, -1) == "LONG_UNWINDING"
    assert _futures_state(0, 1) is None


def test_futures_checkpoint_uses_two_exact_completed_5m_windows(tmp_path):
    session = date(2026, 9, 18)
    cache = tmp_path / session.isoformat()
    cache.mkdir(parents=True)

    start = datetime(2026, 9, 18, 9, 20, tzinfo=IST)
    rows = []
    for i in range(10):
        ts = start + timedelta(minutes=i)
        rows.append({
            "timestamp": ts.isoformat(),
            "open": 100 + i,
            "high": 101 + i,
            "low": 99 + i,
            "close": 100 + i,
            "volume": 10,
            "open_interest": 1000 + i * 10,
        })

    (cache / "futures-1m.json").write_text(
        __import__("json").dumps({"candles": rows})
    )

    source = HistoricalReplayMarketSourcesV1(
        session,
        cache_root=tmp_path,
    )
    result = source.futures_oi_at_checkpoint(
        datetime(2026, 9, 18, 9, 30, tzinfo=IST)
    )
    assert result.health_allowed is True
    assert result.price_change == 5
    assert result.oi_change == 50
    assert result.state == "LONG_BUILDUP"


def test_futures_checkpoint_fails_closed_on_missing_minute(tmp_path):
    session = date(2026, 9, 18)
    cache = tmp_path / session.isoformat()
    cache.mkdir(parents=True)

    start = datetime(2026, 9, 18, 9, 20, tzinfo=IST)
    rows = []
    for i in range(10):
        if i == 7:
            continue
        ts = start + timedelta(minutes=i)
        rows.append({
            "timestamp": ts.isoformat(),
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100 + i,
            "volume": 10,
            "open_interest": 1000 + i,
        })

    (cache / "futures-1m.json").write_text(
        __import__("json").dumps({"candles": rows})
    )
    source = HistoricalReplayMarketSourcesV1(
        session,
        cache_root=tmp_path,
    )
    result = source.futures_oi_at_checkpoint(
        datetime(2026, 9, 18, 9, 30, tzinfo=IST)
    )
    assert result.health_allowed is False
    assert result.health_state == "INCOMPLETE"


def test_replay_output_path_is_date_scoped():
    from market_lab.historical_replay_day_v1 import replay_dir
    path = replay_dir(date(2026, 9, 18), "/tmp/replay")
    assert str(path).endswith("/2026-09-18")
