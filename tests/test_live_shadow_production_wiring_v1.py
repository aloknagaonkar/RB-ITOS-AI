from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
import pytest
from market_lab.domain import Contract,Quote,Snapshot
from market_lab.live_normalized_feature_producer_v1 import LiveNormalizedFeatureProducerV1
from market_lab.live_option_minute_source_v1 import LiveOptionMinuteSourceV1,CompletedOptionMinute
IST=ZoneInfo('Asia/Kolkata')
def snap(checkpoint,delay=3):
    received=checkpoint+timedelta(seconds=delay);catalog=[];quotes=[]
    for strike in range(24750,25251,50):
        for side in ('CE','PE'):
            key=f'{side}-{strike}';catalog.append(Contract(key=key,strike=strike,side=side));quotes.append(Quote(key=key,oi=1000+(100 if side=='PE' else 0),ltp=100,quote_timestamp=received-timedelta(seconds=1)))
    return Snapshot(provider='upstox',underlying='NSE_INDEX|Nifty 50',expiry=date(2026,9,24),started_at=received-timedelta(milliseconds=200),received_at=received,spot=25000,spot_feed_at=received-timedelta(seconds=1),oi_source_at=received-timedelta(seconds=1),catalog=catalog,quotes=quotes)
def test_checkpoint_label_preserves_real_receipt_latency():
    p=LiveNormalizedFeatureProducerV1();cp=datetime(2026,9,18,10,0,tzinfo=IST);p.add_snapshot(snap(cp,3),checkpoint_timestamp=cp);r=p.build_current();assert r.timestamp==cp;assert r.source_received_at==cp+timedelta(seconds=3);assert r.source_delay_ms==3000
def test_snapshot_before_boundary_rejected():
    p=LiveNormalizedFeatureProducerV1();cp=datetime(2026,9,18,10,0,tzinfo=IST)
    with pytest.raises(ValueError):p.add_snapshot(snap(cp,-1),checkpoint_timestamp=cp)
def test_option_source_restart_continuity():
    t=datetime(2026,9,18,10,7,tzinfo=IST);s=LiveOptionMinuteSourceV1('CE',previous_timestamp=t);assert s.process(CompletedOptionMinute('CE',t+timedelta(minutes=1),100,102,99,101)).allowed;bad=s.process(CompletedOptionMinute('CE',t+timedelta(minutes=3),101,103,100,102));assert not bad.allowed and bad.reason=='OPTION_1M_GAP'
