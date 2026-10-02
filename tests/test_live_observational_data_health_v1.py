from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.domain import Contract, Quote, Snapshot
from market_lab.live_observational_data_health_v1 import (
    DataHealthConfig,
    evaluate_snapshot_health,
    strategy_dependency_gate,
)

IST = ZoneInfo("Asia/Kolkata")


def snapshot_at(now, *, spot_age_ms=500, oi_age_ms=500, quote_age_ms=500):
    return Snapshot(
        provider="upstox",
        underlying="NSE_INDEX|Nifty 50",
        expiry=date(2026,9,24),
        started_at=now - timedelta(milliseconds=250),
        received_at=now,
        spot=25000.0,
        spot_feed_at=now - timedelta(milliseconds=spot_age_ms),
        oi_source_at=now - timedelta(milliseconds=oi_age_ms),
        catalog=[
            Contract(key="CE", strike=25000, side="CE"),
            Contract(key="PE", strike=25000, side="PE"),
        ],
        quotes=[
            Quote(
                key="CE", oi=1000, ltp=100,
                quote_timestamp=now - timedelta(milliseconds=quote_age_ms),
            ),
            Quote(
                key="PE", oi=1200, ltp=110,
                quote_timestamp=now - timedelta(milliseconds=quote_age_ms),
            ),
        ],
    )


def test_healthy_snapshot():
    now = datetime(2026,9,18,10,0,tzinfo=IST)
    r = evaluate_snapshot_health(snapshot_at(now))
    assert r.state == "HEALTHY"
    allowed, reason = strategy_dependency_gate(r, dependency="C1")
    assert allowed is True and reason is None


def test_stale_spot_fails_closed():
    now = datetime(2026,9,18,10,0,tzinfo=IST)
    r = evaluate_snapshot_health(snapshot_at(now, spot_age_ms=20000))
    assert r.state == "STALE"
    allowed, reason = strategy_dependency_gate(r, dependency="C1")
    assert allowed is False
    assert reason == "DATA_HEALTH_C1_STALE"


def test_missing_oi_can_be_unhealthy():
    now = datetime(2026,9,18,10,0,tzinfo=IST)
    s = snapshot_at(now)

    missing_oi_quotes = [
        q.model_copy(update={"oi": None})
        for q in s.quotes
    ]
    s = s.model_copy(update={"quotes": missing_oi_quotes})

    r = evaluate_snapshot_health(s)
    assert r.state == "UNHEALTHY"
