
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from market_lab.domain import PCRConfig
from market_lab.paper_market_guard_v1 import validate_option_expiry
from market_lab.oi_vwap_live_futures_v1 import FuturesVWAPFeature
from market_lab.paper_futures_health_v1 import validate_futures_vwap_health
from market_lab.upstox_live_futures_v1 import UpstoxLiveFuturesGatewayV1

IST = ZoneInfo("Asia/Kolkata")


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


def response(payload, status=200):
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("GET", "https://api.upstox.com/test"),
    )


def test_resolve_front_nifty_future_filters_exact_underlying():
    current = response({
        "status":"success",
        "data":[
            {
                "instrument_type":"FUT","segment":"NSE_FO",
                "underlying_symbol":"BANKNIFTY",
                "underlying_key":"NSE_INDEX|Nifty Bank",
                "instrument_key":"NSE_FO|BANK","expiry":"2026-09-29",
                "trading_symbol":"BANKNIFTY FUT","lot_size":30
            },
            {
                "instrument_type":"FUT","segment":"NSE_FO",
                "underlying_symbol":"NIFTY",
                "underlying_key":"NSE_INDEX|Nifty 50",
                "instrument_key":"NSE_FO|N1","expiry":"2026-09-29",
                "trading_symbol":"NIFTY FUT 29 SEP 26","lot_size":65
            }
        ]
    })
    nxt = response({"status":"success","data":[]})
    g = UpstoxLiveFuturesGatewayV1("x", client=FakeClient([current,nxt]))
    i = g.resolve_nifty_front_future(today=date(2026,9,16))
    assert i.instrument_key == "NSE_FO|N1"
    assert i.expiry == date(2026,9,29)


def test_fetch_intraday_5m_schema_sorted():
    payload = response({
        "status":"success",
        "data":{"candles":[
            ["2026-09-16T09:20:00+05:30",101,103,100,102,200,999],
            ["2026-09-16T09:15:00+05:30",100,102,99,101,100,888],
        ]}
    })
    g = UpstoxLiveFuturesGatewayV1("x", client=FakeClient([payload]))
    candles = g.fetch_intraday_5m("NSE_FO|N1")
    assert len(candles) == 2
    assert candles[0].timestamp.minute == 15
    assert candles[1].volume == 200


def test_expired_option_expiry_blocks_new_entries():
    cfg = PCRConfig(
        name="x", provider="upstox", underlying="NSE_INDEX|Nifty 50",
        expiry=date(2026,9,15), wings=5, anchor_time="09:20",
        anchor_tolerance_seconds=120, interval_seconds=15,
        max_quote_age_seconds=30, max_collection_seconds=20,
        trend_flat_threshold=0.01, trend_timestamp_tolerance_seconds=60,
    )
    g = validate_option_expiry(cfg, today=date(2026,9,16))
    assert g.ok is False
    assert g.reason_code == "EXPIRED_OPTION_EXPIRY"
    assert g.new_entries_allowed is False


def test_current_option_expiry_passes():
    cfg = PCRConfig(
        name="x", provider="upstox", underlying="NSE_INDEX|Nifty 50",
        expiry=date(2026,9,22), wings=5, anchor_time="09:20",
        anchor_tolerance_seconds=120, interval_seconds=15,
        max_quote_age_seconds=30, max_collection_seconds=20,
        trend_flat_threshold=0.01, trend_timestamp_tolerance_seconds=60,
    )
    assert validate_option_expiry(cfg, today=date(2026,9,16)).ok is True


def test_stale_completed_futures_vwap_blocks_entry():
    f = FuturesVWAPFeature(
        candle_time="2026-09-16T09:20:00+05:30",
        available_at="2026-09-16T09:25:00+05:30",
        open=100, high=110, low=90, close=105, volume=100,
        cumulative_vwap=101, distance=4, side="ABOVE",
    )
    h = validate_futures_vwap_health(
        f,
        now=datetime(2026,9,16,9,40,tzinfo=IST),
        max_completed_candle_age_seconds=480,
    )
    assert h.ok is False
    assert h.reason_code == "FUTURES_VWAP_STALE"


def test_recent_completed_futures_vwap_passes():
    f = FuturesVWAPFeature(
        candle_time="2026-09-16T09:30:00+05:30",
        available_at="2026-09-16T09:35:00+05:30",
        open=100, high=110, low=90, close=105, volume=100,
        cumulative_vwap=101, distance=4, side="ABOVE",
    )
    h = validate_futures_vwap_health(
        f,
        now=datetime(2026,9,16,9,36,tzinfo=IST),
        max_completed_candle_age_seconds=480,
    )
    assert h.ok is True
