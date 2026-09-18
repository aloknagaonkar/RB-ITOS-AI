from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from market_lab.domain import Contract, Quote, Snapshot
from market_lab.full_shadow_integration_replay_v1 import FullShadowIntegrationReplayV1
from market_lab.live_nifty_futures_oi_producer_v1 import CompletedFuturesCandle
from market_lab.live_option_minute_source_v1 import CompletedOptionMinute

IST = ZoneInfo("Asia/Kolkata")


def snap(ts, ce_base, pe_base, spot=25000.0):
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
                prev_oi=oi-1,
                ltp=100.0,
                quote_timestamp=ts - timedelta(milliseconds=100),
            ))
    return Snapshot(
        provider="upstox",
        underlying="NSE_INDEX|Nifty 50",
        expiry=date(2026,9,24),
        started_at=ts - timedelta(milliseconds=200),
        received_at=ts,
        spot=spot,
        spot_feed_at=ts - timedelta(milliseconds=100),
        oi_source_at=ts - timedelta(milliseconds=100),
        catalog=catalog,
        quotes=quotes,
    )


def fut(ts, close, oi):
    return CompletedFuturesCandle(
        instrument_key="NSE_FO|NIFTY-FUT",
        timestamp=ts,
        open=close-5,
        high=close+5,
        low=close-10,
        close=close,
        oi=oi,
    )


def option_bar(ts, o, h, l, c):
    return CompletedOptionMinute(
        instrument_key="CE-25000",
        timestamp=ts,
        open=o, high=h, low=l, close=c,
    )


def test_full_detect_to_closed_replay(tmp_path: Path):
    r = FullShadowIntegrationReplayV1(tmp_path / "events.jsonl")

    # Establish a prior BEARISH directional state.
    t0 = datetime(2026,9,18,9,45,tzinfo=IST)
    for mins, ce, pe in ((15,1000,1000),(10,1200,1100),(5,1500,1200),(0,1900,1300)):
        cp = r.add_market_snapshot(snap(t0 - timedelta(minutes=mins), ce, pe))
    assert cp.all3_state == "BEARISH_ALL_3"

    # The first actual bullish ALL_3 transition occurs at 09:50.
    t1 = datetime(2026,9,18,9,50,tzinfo=IST)

    cp1 = r.add_market_snapshot(
        snap(t1, 1100,1300, spot=25000)
    )
    assert cp1.all3_state == "BULLISH_ALL_3"
    assert cp1.previous_directional_all3 == "BEARISH_ALL_3"

    oid = r.detect_from_checkpoint(cp1)
    assert oid

    # C2 remains bullish at 09:55.
    cp2 = r.add_market_snapshot(
        snap(t1 + timedelta(minutes=5), 1200,1600, spot=24995)
    )
    assert cp2.all3_state == "BULLISH_ALL_3"

    # Futures 09:50 -> 09:55 = long buildup.
    assert r.process_futures_candle(fut(t1, 25000, 100000)) is None
    f2 = r.process_futures_candle(
        fut(t1 + timedelta(minutes=5), 25020, 101000)
    )
    assert f2.state == "LONG_BUILDUP"

    assert r.confirm_c2(oid, cp2, f2) == "CLASSIFIED"
    assert r.adapter.states()[oid].price_lag_class == "SPOT_LAG"

    assert r.resolve_option(oid, cp2) == "OPTION_RESOLVED"

    assert r.open_exact_next_minute(
        oid,
        timestamp=t1 + timedelta(minutes=6),
        price=100.0,
    ) == "OPEN"

    result = r.replay_option_minutes(
        oid,
        [
            option_bar(t1+timedelta(minutes=7), 100,106,99,105),
            option_bar(t1+timedelta(minutes=8), 104,105,99,100),
        ],
    )

    assert result.final_status == "CLOSED"
    assert result.exit_reason == "STOP_TOUCH"
    assert result.entry_price == 100.0
    assert result.exit_price == 100.0
    assert round(result.net_return_pct, 6) == -0.5

    ok, issue = r.adapter.store.verify_chain()
    assert ok and issue is None


def test_option_gap_becomes_incomplete(tmp_path: Path):
    r = FullShadowIntegrationReplayV1(tmp_path / "events.jsonl")

    t0 = datetime(2026,9,18,9,45,tzinfo=IST)
    for mins, ce, pe in ((15,1000,1000),(10,1200,1100),(5,1500,1200),(0,1900,1300)):
        r.add_market_snapshot(snap(t0 - timedelta(minutes=mins), ce, pe))

    t1 = datetime(2026,9,18,9,50,tzinfo=IST)

    cp1 = r.add_market_snapshot(
        snap(t1, 1100,1300, spot=25000)
    )
    assert cp1.all3_state == "BULLISH_ALL_3"
    assert cp1.previous_directional_all3 == "BEARISH_ALL_3"

    oid = r.detect_from_checkpoint(cp1)
    assert oid

    cp2 = r.add_market_snapshot(
        snap(t1+timedelta(minutes=5), 1200,1600, spot=24995)
    )

    r.process_futures_candle(fut(t1, 25000,100000))
    f2 = r.process_futures_candle(
        fut(t1+timedelta(minutes=5),25020,101000)
    )
    assert r.confirm_c2(oid, cp2, f2) == "CLASSIFIED"
    r.resolve_option(oid, cp2)
    r.open_exact_next_minute(
        oid,
        timestamp=t1+timedelta(minutes=6),
        price=100.0,
    )

    result = r.replay_option_minutes(
        oid,
        [
            option_bar(t1+timedelta(minutes=7), 100,103,99,102),
            option_bar(t1+timedelta(minutes=9), 102,104,101,103),
        ],
    )
    assert result.final_status == "INCOMPLETE"
    assert r.adapter.states()[oid].rejection_reason == "OPTION_1M_GAP"
