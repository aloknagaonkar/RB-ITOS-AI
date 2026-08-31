import pandas as pd

from red_bar_lab.services.upstox_service import (
    RedBarUpstoxService,
    _default_intraday_cache_ttl,
)


class _FakeClient:
    def __init__(self, frame):
        self.frame = frame
        self.calls = 0

    def get_intraday_candles(self, instrument_key, interval=1, unit="minutes"):
        self.calls += 1
        return self.frame


def _frame(rows=3):
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-08-31 09:15", periods=rows, freq="1min"),
            "open": [1.0] * rows,
            "high": [2.0] * rows,
            "low": [0.5] * rows,
            "close": [1.5] * rows,
            "volume": [10] * rows,
            "oi": [None] * rows,
        }
    )


def _service(frame, ttl):
    client = _FakeClient(frame)
    service = RedBarUpstoxService(
        "token",
        client_factory=lambda token: client,
        intraday_cache_ttl_seconds=ttl,
    )
    return service, client


def test_intraday_cache_dedupes_within_ttl():
    service, client = _service(_frame(), ttl=60.0)
    first = service.intraday_candles("NSE_INDEX|Nifty 50")
    second = service.intraday_candles("NSE_INDEX|Nifty 50")
    assert client.calls == 1
    assert list(first["close"]) == list(second["close"])


def test_intraday_cache_keyed_by_instrument_and_interval():
    service, client = _service(_frame(), ttl=60.0)
    service.intraday_candles("NSE_INDEX|Nifty 50")
    service.intraday_candles("NSE_INDEX|Nifty 50", interval_minutes=5)
    service.intraday_candles("NSE_INDEX|Nifty Bank")
    assert client.calls == 3


def test_empty_frame_is_not_cached():
    service, client = _service(pd.DataFrame(), ttl=60.0)
    service.intraday_candles("NSE_INDEX|Nifty 50")
    service.intraday_candles("NSE_INDEX|Nifty 50")
    assert client.calls == 2


def test_cache_disabled_when_ttl_zero():
    service, client = _service(_frame(), ttl=0.0)
    service.intraday_candles("NSE_INDEX|Nifty 50")
    service.intraday_candles("NSE_INDEX|Nifty 50")
    assert client.calls == 2


def test_cached_hit_returns_a_copy():
    service, client = _service(_frame(), ttl=60.0)
    first = service.intraday_candles("NSE_INDEX|Nifty 50")
    first.loc[0, "close"] = 999.0
    second = service.intraday_candles("NSE_INDEX|Nifty 50")
    assert client.calls == 1
    assert second.loc[0, "close"] == 1.5


def test_default_ttl_reads_env(monkeypatch):
    monkeypatch.setenv("UPSTOX_INTRADAY_CACHE_TTL_SECONDS", "7.5")
    assert _default_intraday_cache_ttl() == 7.5
    monkeypatch.setenv("UPSTOX_INTRADAY_CACHE_TTL_SECONDS", "not-a-number")
    assert _default_intraday_cache_ttl() == 15.0
    monkeypatch.delenv("UPSTOX_INTRADAY_CACHE_TTL_SECONDS", raising=False)
    assert _default_intraday_cache_ttl() == 15.0
