from datetime import datetime
from market_lab.vwap_trend_day_profile_v1 import bucket5,aggregate
def test_bucket5(): assert bucket5(datetime.fromisoformat('2026-08-25T14:27:00+05:30')).strftime('%H:%M')=='14:25'
def test_timing_cross():
 rows=[]
 for i in range(10):
  ts=datetime.fromisoformat(f'2026-08-25T09:{20+i:02d}:00+05:30'); px=100 if i<5 else 102; rows.append(dict(timestamp=ts,open=px,high=px,low=px,close=px,volume=1,vwap=101,source_vwap=101))
 bars=aggregate(rows); assert bars[0]['candle_close_time']=='09:25'; assert bars[1]['cross']=='CROSS_ABOVE'
def test_acceptance():
 rows=[]
 for i in range(15):
  ts=datetime.fromisoformat(f'2026-08-25T09:{20+i:02d}:00+05:30'); rows.append(dict(timestamp=ts,open=102,high=102,low=102,close=102,volume=1,vwap=101,source_vwap=101))
 bars=aggregate(rows); assert bars[0]['accept_2cp'] and bars[0]['accept_3cp'] and not bars[0]['accept_4cp']
