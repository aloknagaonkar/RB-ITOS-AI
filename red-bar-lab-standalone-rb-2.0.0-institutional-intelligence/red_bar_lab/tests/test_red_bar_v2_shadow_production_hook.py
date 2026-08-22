from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from red_bar_lab.services.red_bar_v2_futures_replay_service import (
    run_monitored_red_bar_v2_futures_replay,
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


def test_disabled_production_hook_does_not_construct_shadow_runtime(tmp_path, monkeypatch):
    import red_bar_lab.services.red_bar_v2_futures_replay_service as module

    monkeypatch.delenv("RED_BAR_V2_CANONICAL_SHADOW_ENABLED", raising=False)
    monkeypatch.setattr(
        module,
        "get_red_bar_v2_shadow_runtime",
        lambda **kwargs: None if kwargs["enabled"] is False else (_ for _ in ()).throw(AssertionError()),
    )
    index_candles, futures_candles = _frames()
    result = run_monitored_red_bar_v2_futures_replay(
        index_candles,
        futures_candles,
        instrument_key=UNDERLYING,
        vwap_instrument_key=FUTURES,
        artifacts_root=tmp_path,
        futures_expiry="2026-08-27",
    )
    assert result.replay.instrument_key == UNDERLYING


def test_enabled_production_hook_submits_without_mutating_legacy_result(tmp_path, monkeypatch):
    import red_bar_lab.services.red_bar_v2_futures_replay_service as module

    submitted = []

    class Runtime:
        def submit(self, task):
            submitted.append(task)
            return True

    monkeypatch.setenv("RED_BAR_V2_CANONICAL_SHADOW_ENABLED", "true")
    monkeypatch.setattr(module, "get_red_bar_v2_shadow_runtime", lambda **kwargs: Runtime())
    index_candles, futures_candles = _frames()
    result = run_monitored_red_bar_v2_futures_replay(
        index_candles,
        futures_candles,
        instrument_key=UNDERLYING,
        vwap_instrument_key=FUTURES,
        artifacts_root=tmp_path,
        futures_expiry="2026-08-27",
    )
    allowed = [
        event for event in result.replay.events
        if event.event_type == "CANDIDATE_ADMISSION" and event.candidate_allowed is True
    ]
    assert allowed
    assert submitted
    assert submitted[0].replay_event in result.replay.events
    assert submitted[0].event_timestamp == submitted[0].replay_event.timestamp
    assert result.replay.admitted_candidates >= 1


def test_shadow_submission_failure_does_not_interrupt_monitored_replay(tmp_path, monkeypatch):
    import red_bar_lab.services.red_bar_v2_futures_replay_service as module

    class Runtime:
        def submit(self, task):
            raise RuntimeError("shadow unavailable")

    monkeypatch.setenv("RED_BAR_V2_CANONICAL_SHADOW_ENABLED", "true")
    monkeypatch.setattr(module, "get_red_bar_v2_shadow_runtime", lambda **kwargs: Runtime())
    index_candles, futures_candles = _frames()
    result = run_monitored_red_bar_v2_futures_replay(
        index_candles,
        futures_candles,
        instrument_key=UNDERLYING,
        vwap_instrument_key=FUTURES,
        artifacts_root=tmp_path,
        futures_expiry="2026-08-27",
    )
    assert result.replay.admitted_candidates >= 1
