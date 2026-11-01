from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.domain import Contract, Quote, Snapshot
from market_lab.live_normalized_feature_producer_v1 import (
    LiveNormalizedFeatureProducerV1,
)

IST = ZoneInfo("Asia/Kolkata")


def make_snapshot(ts, ce_base, pe_base, spot=25000.0):
    strikes = [24750 + i * 50 for i in range(11)]
    catalog = []
    quotes = []
    for i, strike in enumerate(strikes):
        for side in ("CE", "PE"):
            key = f"{side}-{int(strike)}"
            catalog.append(Contract(key=key, strike=strike, side=side))
            oi = (ce_base + i * 10) if side == "CE" else (pe_base + i * 10)
            quotes.append(Quote(
                key=key,
                oi=oi,
                prev_oi=oi - 1,
                ltp=100.0,
                quote_timestamp=ts - timedelta(milliseconds=100),
            ))
    return Snapshot(
        provider="upstox",
        underlying="NSE_INDEX|Nifty 50",
        expiry=date(2026, 9, 24),
        started_at=ts - timedelta(milliseconds=200),
        received_at=ts,
        spot=spot,
        spot_feed_at=ts - timedelta(milliseconds=100),
        oi_source_at=ts - timedelta(milliseconds=100),
        catalog=catalog,
        quotes=quotes,
    )


def test_exact_same_strike_all3_bullish():
    p = LiveNormalizedFeatureProducerV1()
    t = datetime(2026,9,18,10,0,tzinfo=IST)

    # Prior baskets: CE grows +100 total per strike; PE grows +300 total per strike,
    # making imbalance and PCR change positive.
    p.add_snapshot(make_snapshot(t - timedelta(minutes=15), 1000, 1000))
    p.add_snapshot(make_snapshot(t - timedelta(minutes=10), 1100, 1300))
    p.add_snapshot(make_snapshot(t - timedelta(minutes=5), 1200, 1600))
    p.add_snapshot(make_snapshot(t, 1300, 1900))

    r = p.build_current()
    assert r.health_allowed is True
    assert r.state_5m == "BULLISH"
    assert r.state_10m == "BULLISH"
    assert r.state_15m == "BULLISH"
    assert r.all3_state == "BULLISH_ALL_3"
    assert r.moving_atm == 25000
    assert r.ce_instrument_key == "CE-25000"
    assert r.pe_instrument_key == "PE-25000"


def test_missing_exact_horizon_makes_incomplete():
    p = LiveNormalizedFeatureProducerV1()
    t = datetime(2026,9,18,10,0,tzinfo=IST)
    p.add_snapshot(make_snapshot(t - timedelta(minutes=15), 1000, 1000))
    p.add_snapshot(make_snapshot(t - timedelta(minutes=5), 1200, 1600))
    p.add_snapshot(make_snapshot(t, 1300, 1900))
    r = p.build_current()
    assert r.state_10m == "NA"
    assert r.all3_state == "INCOMPLETE"


def test_previous_directional_all3_is_preserved():
    p = LiveNormalizedFeatureProducerV1()
    t = datetime(2026,9,18,10,0,tzinfo=IST)
    for mins, ce, pe in ((15,1000,1000),(10,1100,1300),(5,1200,1600),(0,1300,1900)):
        p.add_snapshot(make_snapshot(t - timedelta(minutes=mins), ce, pe))
    first = p.build_current()
    assert first.all3_state == "BULLISH_ALL_3"

    # Add one later snapshot; previous directional ALL3 should be exposed before update.
    p.add_snapshot(make_snapshot(t + timedelta(minutes=5), 1400, 2200))
    second = p.build_current()
    assert second.previous_directional_all3 == "BULLISH_ALL_3"
