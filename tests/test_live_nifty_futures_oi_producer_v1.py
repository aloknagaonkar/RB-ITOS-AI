from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.live_nifty_futures_oi_producer_v1 import (
    CompletedFuturesCandle,
    LiveNiftyFuturesOIProducerV1,
)

IST = ZoneInfo("Asia/Kolkata")


def c(ts, close, oi):
    return CompletedFuturesCandle(
        instrument_key="NSE_FO|NIFTY-FUT",
        timestamp=ts,
        open=close-5,
        high=close+5,
        low=close-10,
        close=close,
        oi=oi,
    )


def test_long_buildup():
    p = LiveNiftyFuturesOIProducerV1()
    t = datetime(2026,9,18,10,0,tzinfo=IST)
    assert p.process(c(t, 25000, 100000)) is None
    r = p.process(c(t+timedelta(minutes=5), 25020, 101000))
    assert r.state == "LONG_BUILDUP"
    assert r.health_allowed is True


def test_short_buildup():
    p = LiveNiftyFuturesOIProducerV1()
    t = datetime(2026,9,18,10,0,tzinfo=IST)
    p.process(c(t, 25000, 100000))
    r = p.process(c(t+timedelta(minutes=5), 24980, 101000))
    assert r.state == "SHORT_BUILDUP"


def test_gap_fails_closed():
    p = LiveNiftyFuturesOIProducerV1()
    t = datetime(2026,9,18,10,0,tzinfo=IST)
    p.process(c(t, 25000, 100000))
    r = p.process(c(t+timedelta(minutes=10), 25020, 101000))
    assert r.health_allowed is False
    assert r.health_reason == "FUTURES_5M_GAP"
