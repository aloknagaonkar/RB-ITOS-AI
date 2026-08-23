from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from red_bar_lab.services.red_bar_v2_futures_replay_service import (
    run_monitored_red_bar_v2_futures_replay,
)
from red_bar_lab.services.red_bar_v2_live_shadow import (
    submit_latest_live_canonical_shadow,
)

IST = timezone(timedelta(hours=5, minutes=30))
UNDERLYING = "NSE_INDEX|Nifty 50"
FUTURES = "NSE_FO|NIFTY-FUT"


def _candles(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    timestamps = pd.date_range(
        datetime(2026, 8, 24, 9, 15, tzinfo=IST),
        periods=len(closes),
        freq="1min",
    )
    opens = [closes[0] - 0.2, *closes[:-1]]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) + 0.4 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 0.4 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": volumes,
        },
        index=timestamps,
    )


def _frames():
    index_closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    index_closes += [103.0, 101.0, 99.0, 97.0, 95.0]
    index_closes += [96.0 + index * 0.9 for index in range(40)]
    futures_closes = [200.0 + index * 0.6 for index in range(50)]
    return (
        _candles(index_closes, [10.0 + index for index in range(50)]),
        _candles(futures_closes, [1000.0 + index * 10.0 for index in range(50)]),
    )


def _monitored(tmp_path):
    index_candles, futures_candles = _frames()
    return run_monitored_red_bar_v2_futures_replay(
        index_candles,
        futures_candles,
        instrument_key=UNDERLYING,
        vwap_instrument_key=FUTURES,
        artifacts_root=tmp_path,
        futures_expiry="2026-08-27",
    )


def test_shared_monitored_replay_never_creates_canonical_shadow_database(tmp_path, monkeypatch):
    monkeypatch.setenv("RED_BAR_V2_CANONICAL_SHADOW_ENABLED", "true")
    result = _monitored(tmp_path)
    assert result.replay.instrument_key == UNDERLYING
    assert not (tmp_path / "database" / "red_bar_strategy.db").exists()


def test_live_submission_sends_only_newest_candidate_event(tmp_path, monkeypatch):
    import red_bar_lab.services.red_bar_v2_live_shadow as module

    submitted = []

    class Runtime:
        def submit(self, task):
            submitted.append(task)
            return True

    monkeypatch.setattr(module, "get_red_bar_v2_shadow_runtime", lambda **kwargs: Runtime())
    monitored = _monitored(tmp_path)
    settings = SimpleNamespace(
        red_bar_v2_canonical_shadow_enabled=True,
        database_path=tmp_path / "database" / "red_bar_strategy.db",
    )

    assert submit_latest_live_canonical_shadow(
        monitored=monitored,
        settings=settings,
        instrument_key=UNDERLYING,
        futures_instrument_key=FUTURES,
        futures_expiry="2026-08-27",
    ) is True

    candidates = [
        event for event in monitored.replay.events
        if event.event_type == "CANDIDATE_ADMISSION"
    ]
    assert candidates
    assert len(submitted) == 1
    assert submitted[0].replay_event.timestamp == max(event.timestamp for event in candidates)
    assert submitted[0].event_timestamp == submitted[0].replay_event.timestamp


def test_disabled_live_submission_does_not_construct_runtime(tmp_path, monkeypatch):
    import red_bar_lab.services.red_bar_v2_live_shadow as module

    monkeypatch.setattr(
        module,
        "get_red_bar_v2_shadow_runtime",
        lambda **kwargs: None if kwargs["enabled"] is False else (_ for _ in ()).throw(AssertionError()),
    )
    monitored = _monitored(tmp_path)
    settings = SimpleNamespace(
        red_bar_v2_canonical_shadow_enabled=False,
        database_path=tmp_path / "database" / "red_bar_strategy.db",
    )
    assert submit_latest_live_canonical_shadow(
        monitored=monitored,
        settings=settings,
        instrument_key=UNDERLYING,
        futures_instrument_key=FUTURES,
        futures_expiry="2026-08-27",
    ) is False
    assert not settings.database_path.exists()


def test_live_shadow_failure_is_isolated(tmp_path, monkeypatch):
    import red_bar_lab.services.red_bar_v2_live_shadow as module

    class Runtime:
        def submit(self, task):
            raise RuntimeError("shadow unavailable")

    monkeypatch.setattr(module, "get_red_bar_v2_shadow_runtime", lambda **kwargs: Runtime())
    monitored = _monitored(tmp_path)
    settings = SimpleNamespace(
        red_bar_v2_canonical_shadow_enabled=True,
        database_path=tmp_path / "database" / "red_bar_strategy.db",
    )
    assert submit_latest_live_canonical_shadow(
        monitored=monitored,
        settings=settings,
        instrument_key=UNDERLYING,
        futures_instrument_key=FUTURES,
        futures_expiry="2026-08-27",
    ) is False
    assert monitored.replay.admitted_candidates >= 1
