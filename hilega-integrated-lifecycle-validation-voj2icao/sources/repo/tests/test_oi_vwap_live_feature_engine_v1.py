
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_lab.domain import Contract, Quote, Snapshot
from market_lab.storage import Base, Configuration, Observation
from market_lab.oi_vwap_live_feature_engine_v1 import build_oi_checkpoint_feature
from market_lab.oi_vwap_live_futures_v1 import FuturesCandle, completed_futures_vwap

IST = ZoneInfo("Asia/Kolkata")


def snap(at, spot, rows):
    catalog = []
    quotes = []
    for strike, ce_oi, pe_oi in rows:
        ce_key = f"CE-{strike}"
        pe_key = f"PE-{strike}"
        catalog.extend([
            Contract(key=ce_key, strike=strike, side="CE"),
            Contract(key=pe_key, strike=strike, side="PE"),
        ])
        quotes.extend([
            Quote(key=ce_key, oi=ce_oi, prev_oi=ce_oi, ltp=100),
            Quote(key=pe_key, oi=pe_oi, prev_oi=pe_oi, ltp=100),
        ])
    return Snapshot(
        provider="upstox",
        underlying="NSE_INDEX|Nifty 50",
        expiry="2026-09-22",
        started_at=at,
        received_at=at,
        spot=spot,
        spot_feed_at=at,
        catalog=catalog,
        quotes=quotes,
        raw={},
    )


def add_obs(session, config_id, idx, at, spot, rows):
    s = snap(at, spot, rows)
    o = Observation(
        id=idx,
        config_id=config_id,
        recorded_at=at.isoformat(),
        session_date=at.date().isoformat(),
        snapshot=s.model_dump(mode="json"),
        evaluation={"results": [{"mode":"moving","contract_keys":[]}], "anchor_status":"missed"},
    )
    session.add(o)
    return o


def test_oi_checkpoint_uses_current_atm_pm2_for_recent_and_fixed_0920_for_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'x.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s, s.begin():
        c = Configuration(id=1, created_at="x", payload={})
        s.add(c)
        rows920 = [(24900,100,100),(24950,100,100),(25000,100,100),(25050,100,100),(25100,100,100)]
        rows925 = [(24900,110,105),(24950,110,105),(25000,110,105),(25050,110,105),(25100,110,105)]
        rows930 = [(24900,120,130),(24950,120,130),(25000,120,130),(25050,120,130),(25100,120,130)]
        add_obs(s,1,1,datetime(2026,9,16,9,20,tzinfo=IST),25000,rows920)
        add_obs(s,1,2,datetime(2026,9,16,9,25,tzinfo=IST),25000,rows925)
        add_obs(s,1,3,datetime(2026,9,16,9,30,tzinfo=IST),25000,rows930)

    with Session(engine) as s:
        f = build_oi_checkpoint_feature(s, config_id=1, observation_id=3)
        assert f.ce_delta_5m == 50
        assert f.pe_delta_5m == 125
        assert f.imbalance_5m == 75
        assert f.ce_session_delta == 100
        assert f.pe_session_delta == 150
        assert f.session_imbalance == 50
        assert f.previous_session_imbalance == -25


def test_completed_futures_vwap_excludes_same_label_incomplete_bar():
    candles = [
        FuturesCandle(datetime(2026,9,16,9,15,tzinfo=IST),100,110,90,100,10),
        FuturesCandle(datetime(2026,9,16,9,20,tzinfo=IST),100,120,100,110,20),
        FuturesCandle(datetime(2026,9,16,9,25,tzinfo=IST),110,140,110,130,30),
    ]
    # At 09:25, 09:25 bar has just started and must NOT be used.
    f = completed_futures_vwap(candles, available_at=datetime(2026,9,16,9,25,tzinfo=IST))
    assert f.candle_time.startswith("2026-09-16T09:20")
    assert f.close == 110


def test_completed_futures_vwap_uses_typical_price_proxy():
    candles = [
        FuturesCandle(datetime(2026,9,16,9,15,tzinfo=IST),100,110,90,100,10),
        FuturesCandle(datetime(2026,9,16,9,20,tzinfo=IST),100,120,100,110,20),
    ]
    f = completed_futures_vwap(candles, available_at=datetime(2026,9,16,9,25,tzinfo=IST))
    expected = (((110+90+100)/3)*10 + ((120+100+110)/3)*20) / 30
    assert abs(f.cumulative_vwap - expected) < 1e-9
