from datetime import datetime,timedelta
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import pytest
import strategy as s

def frame(**kw):
    f=dict(low=98,high=105,close=104,ema9=100,vwap=101);f.update(kw);return f

def test_bull_rejects_both():assert s.checks(frame())['bullish_entry']
def test_bear_rejects_both():assert s.checks(frame(high=105,close=98))['bearish_entry']
def test_touch_is_not_pierce():
    assert not s.checks(frame(low=100))['bullish_entry']
    assert not s.checks(frame(high=101,close=98))['bearish_entry']
def test_close_between_lines_not_entry():assert not any(s.checks(frame(close=100.5))[k] for k in ['bullish_entry','bearish_entry'])
def test_close_equality_not_entry():assert not s.checks(frame(close=101))['bullish_entry']
def test_exit_requires_strict_close_beyond_ema():
    assert s.exit_condition('BULLISH',frame(close=99))
    assert s.exit_condition('BEARISH',frame(close=101))
    for side in ['BULLISH','BEARISH']:assert not s.exit_condition(side,frame(close=100))
def test_ema9_and_ohlc4_volume_vwap():
    bars=[dict(open=100,high=104,low=98,close=102,volume=10),dict(open=102,high=110,low=100,close=108,volume=30)]
    f=s.indicators(bars)
    assert f[0]['ema9']==102 and f[1]['ema9']==pytest.approx(103.2)
    assert f[0]['vwap']==101
    assert f[1]['vwap']==pytest.approx((101*10+105*30)/40)
    assert f[1]['vwap_source_ohlc4']==105

def test_zero_volume_not_fabricated():
    f=s.indicators([dict(open=100,high=101,low=99,close=100,volume=0)])[0]
    assert f['vwap'] is None and not s.checks(f)['bullish_entry']

def dataset():
    at=datetime(2026,10,26,9,15,tzinfo=s.IST);rows=[]
    bars=[(100,101,99,100),(100,105,98,104),(103,104,98,99),(98,99,97,98)]
    for i in range(125):
        o,h,l,c=bars[i] if i<len(bars) else (98,99,97,98)
        for j in range(3):rows.append(dict(timestamp=(at+timedelta(minutes=i*3+j)).isoformat(),open=o,high=h,low=l,close=c,volume=1))
    return dict(session_date='2026-10-26',contract=dict(instrument_type='FUT',instrument_key='TEST',trading_symbol='TEST FUT',expiry='2026-10-27'),candles=rows)

def test_next_open_fills_and_exit_priority():
    r=s.replay(dataset());t=r['trades'][0]
    assert t['direction']=='BULLISH'
    assert t['entry_signal']['available_at'].endswith('09:21:00+05:30')
    assert t['entry_time'].endswith('09:21:00+05:30') and t['entry_price']==103
    assert t['exit_time'].endswith('09:24:00+05:30') and t['exit_price']==98 and t['points']==-5
    assert r['audit'][2]['checks']['bearish_entry']
    assert 'ENTRY_NOT_ADDED_WHILE_POSITION_ACTIVE' in r['audit'][2]['actions']
    assert r['audit'][3]['executions'][0]['action']=='EXIT_AT_NEXT_3M_OPEN'
    assert len(r['frames'])==125

def test_future_data_cannot_change_early_decisions():
    d=dataset();a=s.replay(d)
    for row in d['candles'][60:]:
        for k in ['open','high','low','close']:row[k]+=100
    b=s.replay(d)
    assert a['audit'][:20]==b['audit'][:20]

def test_reject_missing_and_negative_volume():
    d=dataset();d['candles'].pop()
    with pytest.raises(ValueError):s.validate(d)
    d=dataset();d['candles'][0]['volume']=-1
    with pytest.raises(ValueError):s.validate(d)

def test_session_end_closure_and_no_overlap():
    r=s.replay(dataset())
    for a,b in zip(r['trades'],r['trades'][1:]):assert a['exit_time']<=b['entry_time']
    for t in r['trades']:assert t['giveback']>=0
    assert all(t['entry_time']<'2026-10-26T15:30:00+05:30' for t in r['trades'])
