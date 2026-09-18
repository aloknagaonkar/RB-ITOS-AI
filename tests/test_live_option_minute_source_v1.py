from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.live_option_minute_source_v1 import (
    CompletedOptionMinute,
    LiveOptionMinuteSourceV1,
)

IST = ZoneInfo("Asia/Kolkata")


def b(ts):
    return CompletedOptionMinute(
        instrument_key="NSE_FO|CE25000",
        timestamp=ts,
        open=100,
        high=105,
        low=99,
        close=104,
    )


def test_contiguous_option_minutes():
    s = LiveOptionMinuteSourceV1("NSE_FO|CE25000")
    t = datetime(2026,9,18,10,6,tzinfo=IST)
    assert s.process(b(t)).allowed is True
    assert s.process(b(t+timedelta(minutes=1))).allowed is True


def test_option_gap_fails_closed():
    s = LiveOptionMinuteSourceV1("NSE_FO|CE25000")
    t = datetime(2026,9,18,10,6,tzinfo=IST)
    assert s.process(b(t)).allowed is True
    r = s.process(b(t+timedelta(minutes=2)))
    assert r.allowed is False
    assert r.reason == "OPTION_1M_GAP"


def test_wrong_instrument_rejected():
    s = LiveOptionMinuteSourceV1("NSE_FO|CE25000")
    t = datetime(2026,9,18,10,6,tzinfo=IST)
    wrong = CompletedOptionMinute(
        instrument_key="NSE_FO|PE25000",
        timestamp=t,
        open=100,
        high=101,
        low=99,
        close=100,
    )
    r = s.process(wrong)
    assert r.allowed is False
    assert r.reason == "OPTION_INSTRUMENT_MISMATCH"
