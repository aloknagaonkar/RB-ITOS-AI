"""Run on Ubuntu VM only. Synthetic tests do not prove market/strategy parity."""
from datetime import datetime,timedelta
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import study
import core

DAY='2026-10-26'
def stamp(hm):return DAY+'T'+hm+':00+05:30'
def dt(hm):return datetime.fromisoformat(stamp(hm))
def rows(n=10):
    return [dict(timestamp=(dt('09:15')+timedelta(minutes=i)).isoformat(),
        open=100+i,high=102+i,low=99+i,close=101+i,volume=1) for i in range(n)]

@pytest.mark.parametrize('interval,count,close',[(1,6,101),(3,2,103),(5,1,105)])
def test_completed_bar_aggregation(interval,count,close):
    bars=core.aggregate(rows(),DAY,interval,dt('09:21'))
    assert len(bars)==count
    assert bars[0].close==close


def test_three_minute_anchor_ohlc_and_volume():
    bars=core.aggregate(rows(),DAY,3,dt('09:21'))
    assert [b.ts.strftime('%H:%M') for b in bars]==['09:15','09:18']
    assert (bars[0].open,bars[0].high,bars[0].low,bars[0].close,bars[0].volume)==(100,104,99,103,3)


def test_partial_three_minute_bar_excluded():
    bars=core.aggregate(rows(),DAY,3,dt('09:20'))
    assert len(bars)==1


def test_no_partial_three_minute_at_cutoff():
    bars=core.aggregate(rows(375),DAY,3,dt('14:55'))
    assert bars[-1].ts+timedelta(minutes=3)==dt('14:54')

@pytest.mark.parametrize('interval',[1,3,5])
def test_missing_minute_is_blocked(interval):
    raw=rows();del raw[1]
    with pytest.raises(ValueError,match='MISSING_MINUTE'):
        core.aggregate(raw,DAY,interval,dt('09:21'))

@pytest.mark.parametrize('kind',['duplicate','date','timezone','ohlc','nan','zero','seconds','volume'])
def test_invalid_input_is_blocked(kind):
    raw=rows()
    if kind=='duplicate':raw.append(raw[0])
    if kind=='date':raw[0]['timestamp']='2026-10-23T09:15:00+05:30'
    if kind=='timezone':raw[0]['timestamp']='2026-10-26T09:15:00'
    if kind=='ohlc':raw[0]['high']=90
    if kind=='nan':raw[0]['close']=float('nan')
    if kind=='zero':raw[0]['open']=0
    if kind=='seconds':raw[0]['timestamp']='2026-10-26T09:15:01+05:30'
    if kind=='volume':raw[0]['volume']=-1
    with pytest.raises(ValueError):core.validate_rows(raw,DAY)

@pytest.fixture(params=[1,3])
def variant(request,tmp_path):
    interval=request.param;installed,_=study.verify_sources()
    p,l=study.isolated(tmp_path/'copy',installed,interval)
    yield interval,p,l
    study.cleanup(interval)


def test_variants_preserve_rules_and_namespace(variant):
    interval,p,l=variant
    assert p is not core.policy5
    assert p.VERSION==core.policy5.VERSION
    assert p.RULES['confirmation_interval_minutes']==interval
    assert core.policy5.RULES['confirmation_interval_minutes']==5
    assert p.RULES['bullish_signal_gap_min']==2 and p.RULES['bullish_full_wma_min']==2
    assert p.RULES['cutoff_IST']=='14:55'
    assert p.StrategyEvent is not core.policy5.StrategyEvent


def test_frame_closes_at_selected_boundary(variant):
    interval,p,l=variant
    bar=core.aggregate(rows(),DAY,interval,dt('09:21'))[0]
    snapshot=SimpleNamespace(rsi9=50,ema3_rsi=45,wma21_rsi=40)
    frame=p.PriceFrames().complete(bar,snapshot,snapshot)
    assert datetime.fromisoformat(frame['available_at'])==dt('09:15')+timedelta(minutes=interval)


def test_followup_rejects_wrong_spacing(variant):
    interval,p,l=variant
    at=dt('10:15');signal=dict(time=at-timedelta(minutes=interval),due=at,close=100,midpoint=99)
    frame=dict(available_at=at.isoformat(),close=101)
    result=p.followup_check('BULLISH',signal,frame,at)
    assert not any('IMMEDIATE_NEXT' in r for r in result['reasons'])
    signal['time']=at-timedelta(minutes=interval+1)
    assert any('IMMEDIATE_NEXT' in r for r in p.followup_check('BULLISH',signal,frame,at)['reasons'])


def test_conversion_keeps_current_exit_and_reversal(variant):
    interval,p,l=variant
    source=Path(p.__file__).read_text()
    assert 'current.wma21_rsi>40' in source
    assert 'FULLY_CONFIRMED_OPPOSITE_BULLISH' in source
    assert 'timedelta(minutes=5)' not in source
    assert 'at.minute%5' not in source
    assert 'minute=at-timedelta(minutes=1)' in source


def alert(hm,side='BULLISH',**kw):return dict(time=stamp(hm),direction=side,price=100,stage='ENTRY',**kw)
def control(hm='10:05',side='BULLISH'):
    return dict(audit=[dict(time=stamp(hm),entries=[dict(time=stamp(hm),direction=side,price=105)])])


def test_early_entry_matches_next_boundary_with_price_advantage():
    r=study.match_alerts([alert('10:02')],control(),[])[0]
    assert r['lead_minutes']==3 and r['price_advantage_points']==5
    assert r['classification']=='CONFIRMED_NEXT_5M_BOUNDARY'


def test_bearish_price_advantage_sign():
    r=study.match_alerts([alert('10:02','BEARISH')],control(side='BEARISH'),[])[0]
    assert r['price_advantage_points']==-5


def test_boundary_alert_never_counts_as_early():
    r=study.match_alerts([alert('10:00')],control(),[])[0]
    assert not r['off_5m_boundary'] and r['matched_5m_entry'] is None


def test_same_timestamp_confirmation_is_not_early():
    r=study.match_alerts([alert('10:05')],control(),[])[0]
    assert r['lead_minutes'] is None


def test_one_baseline_entry_not_reused():
    r=study.match_alerts([alert('10:01'),alert('10:02')],control(),[])
    assert sum(x['matched_5m_entry'] is not None for x in r)==1
    assert r[0]['matched_5m_entry']==stamp('10:05')


def test_later_five_minute_entry_outside_primary_window_unmatched():
    r=study.match_alerts([alert('10:01')],control(hm='10:10'),[])[0]
    assert r['matched_5m_entry'] is None


def test_opposite_alert_invalidates_earlier_direction():
    r=study.match_alerts([alert('10:01'),alert('10:03','BEARISH')],control(),[])
    assert r[0]['classification']=='INVALIDATED_BEFORE_5M_CONFIRMATION'

@pytest.mark.parametrize('exit_hm',['10:04','10:05'])
def test_exit_before_or_at_five_minute_confirmation_invalidates(exit_hm):
    r=study.match_alerts([alert('10:02',valid_until=stamp(exit_hm))],control(),[])[0]
    assert r['matched_5m_entry'] is None


def test_opposite_five_minute_entry_reported():
    r=study.match_alerts([alert('10:02')],control(side='BEARISH'),[])[0]
    assert r['classification']=='OPPOSITE_5M_ENTRY'


def test_agreement_requires_simultaneous_active_owners():
    one=dict(audit=[dict(time=stamp('10:01'),owner='BULLISH',frame={'close':100}),dict(time=stamp('10:02'),owner='NONE',frame={'close':101})])
    three=dict(audit=[dict(time=stamp('10:03'),owner='BULLISH',frame={'close':102})])
    assert study.agreement(one,three)==[]


def test_agreement_starts_at_later_confirmation_not_earlier_one():
    one=dict(audit=[dict(time=stamp('10:01'),owner='BULLISH',frame={'close':100})])
    three=dict(audit=[dict(time=stamp('10:03'),owner='BULLISH',frame={'close':102})])
    r=study.agreement(one,three)
    assert len(r)==1 and r[0]['time']==stamp('10:03')


def test_setup_discarded_on_own_boundary_has_no_lifetime():
    result=dict(trades=[],audit=[dict(time=stamp('10:02'),pending={})])
    r=study.with_lifetime([dict(time=stamp('10:02'),direction='BULLISH',stage='SETUP')],result)
    assert r[0]['valid_until']==stamp('10:02')


def parity_fixture():
    fields=('open','high','low','close','ema10','previous_ema10','rsi9','ema3_rsi','wma21_rsi','previous_rsi9','previous_ema3_rsi','previous_wma21_rsi','seeded_bar_count')
    audit=[];records=[];at=dt('09:20')
    while at<=dt('14:55'):
        frame={k:50 for k in fields};stamp_=at.isoformat()
        audit.append(dict(time=stamp_,frame=dict(frame)))
        records.append(dict(stage='DIRECTIONAL_DECISION',payload=dict(decision_timestamp=stamp_,price_ema_frame=dict(frame),event_details=[],strategy_version=core.policy5.VERSION)))
        at+=timedelta(minutes=5)
    records.append(dict(stage='DIRECTIONAL_SESSION_CUTOFF',payload=dict(decision_timestamp=stamp('14:55'))))
    return dict(audit=audit,trades=[],open_trade=None),records


def test_full_empty_session_parity_requires_actual_frames():
    r,records=parity_fixture()
    proof=core.parity(r,records,dt('14:55'))
    assert proof['status']=='PASS' and proof['checked_boundaries']==68

@pytest.mark.parametrize('change',['missing','frame','version','cutoff','seedcount','duplicate'])
def test_recorded_parity_blocks_incomplete_or_changed_evidence(change):
    r,records=parity_fixture()
    if change=='missing':records.pop(0)
    if change=='frame':records[0]['payload']['price_ema_frame']=None
    if change=='version':records[0]['payload']['strategy_version']='old'
    if change=='cutoff':records.pop()
    if change=='seedcount':records[0]['payload']['price_ema_frame']['seeded_bar_count']+=1
    if change=='duplicate':
        import copy
        extra=copy.deepcopy(records[0]);extra['payload']['price_ema_frame']['close']+=1;records.append(extra)
    assert core.parity(r,records,dt('14:55'))['status']=='FAIL'


def test_trade_mismatch_blocks_parity_even_when_indicators_match():
    r,records=parity_fixture()
    r['trades']=[dict(direction='BULLISH',entry_time=stamp('10:00'),entry_price=100,exit_time=stamp('10:05'),exit_price=105,points=5)]
    proof=core.parity(r,records,dt('14:55'))
    assert 'ENTRY_MISMATCH' in proof['issues'] and 'EXIT_MISMATCH' in proof['issues']

@pytest.mark.parametrize('supply_recent',[False,True])
def test_recent_warmup_required_and_cache_refresh_readonly(tmp_path,supply_recent):
    import hashlib,json,zipfile
    def day_rows(day):
        return [dict(r,timestamp=day+r['timestamp'][10:]) for r in rows(375)]
    archive=tmp_path/'input.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('candles/2026-10-21.json',json.dumps(dict(candles=day_rows('2026-10-21'))))
        z.writestr('today-audit.json','[]')
    session=tmp_path/'session.json'
    session.write_text(json.dumps(dict(session_date=DAY,underlying='NSE_INDEX|Nifty 50',candles=rows(375))))
    before=hashlib.sha256(archive.read_bytes()).hexdigest()
    cache=tmp_path/'cache';cache.mkdir()
    if supply_recent:
        for d in ('2026-10-22','2026-10-23'):
            (cache/(d+'.json')).write_text(json.dumps(dict(session_date=d,candles=day_rows(d))))
        data,warm,records,added=study.load_inputs(archive,session,[cache])
        assert [d for d,_ in warm]==['2026-10-21','2026-10-22','2026-10-23']
        assert len(added)==2
    else:
        with pytest.raises(ValueError,match='MISSING_RECENT_WARMUP'):
            study.load_inputs(archive,session,[cache])
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==before


def test_historical_post_close_prints_excluded_and_logged():
    raw=rows(375)
    raw += [dict(raw[-1],timestamp=stamp('15:39')),dict(raw[-1],timestamp=stamp('15:59'))]
    regular,excluded=study.regular_warmup(raw,DAY)
    assert len(regular)==375 and excluded==[stamp('15:39'),stamp('15:59')]
    assert len(raw)==377  # source untouched


def test_target_post_close_prints_still_rejected():
    raw=rows(375)+[dict(rows()[0],timestamp=stamp('15:39'))]
    with pytest.raises(ValueError,match='OUTSIDE_REGULAR_SESSION:2026-10-26'):
        core.validate_rows(raw,DAY)


def test_warmup_filter_does_not_hide_missing_regular_minute():
    raw=rows(375);del raw[10]
    raw += [dict(raw[-1],timestamp=stamp('15:39'))]
    regular,excluded=study.regular_warmup(raw,DAY)
    with pytest.raises(ValueError,match='MISSING_MINUTE'):
        core.aggregate(regular,DAY,1,dt('15:30'))


def test_warmup_filter_does_not_hide_invalid_dates_or_duplicates():
    raw=rows()+[dict(rows()[0],timestamp='2026-10-23T15:39:00+05:30')]
    with pytest.raises(ValueError,match='SESSION_DATE_MISMATCH'):
        study.regular_warmup(raw,DAY)
    raw=rows()+[dict(rows()[0],timestamp=stamp('15:39'))]*2
    with pytest.raises(ValueError,match='DUPLICATE_MINUTE'):
        study.regular_warmup(raw,DAY)
