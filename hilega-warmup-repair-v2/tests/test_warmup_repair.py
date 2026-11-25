"""VM tests: exact session coverage, recovery, shared warmup and stale display."""
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace as Obj
import pytest
from market_lab.hilega_three_minute_v1 import warmup as w
from market_lab.hilega_three_minute_v1.lifecycle_view import current_view


def raw(day, count=None):
    start=datetime.combine(day,datetime.min.time(),tzinfo=w.IST).replace(
        hour=14 if day==w.SPECIAL else 9,minute=20 if day==w.SPECIAL else 15)
    return [dict(timestamp=(start+timedelta(minutes=i)).isoformat(),
                 open=100.,high=102.,low=99.,close=101.,volume=10)
            for i in range(count if count is not None else (70 if day==w.SPECIAL else 375))]


def cache(root,day,rows=None):
    root.mkdir(parents=True,exist_ok=True)
    path=root/(str(day)+'.json')
    path.write_text(json.dumps(dict(session_date=str(day),underlying=w.UNDERLYING,
                                   candles=raw(day) if rows is None else rows)))
    return path


@pytest.mark.parametrize('day,last',[
    ('2026-11-23','2026-11-20'),('2026-11-09','2026-11-08'),
    ('2026-11-11','2026-11-09'),('2026-10-21','2026-10-19')])
def test_exchange_sessions_not_calendar_age(day,last):
    result=w.required_sessions(date.fromisoformat(day))
    assert len(result)==20 and str(result[-1])==last
    assert result==sorted(set(result))


@pytest.mark.parametrize('day',['2026-11-07','2026-11-10','2026-11-24','2027-01-04'])
def test_unreviewed_year_and_closed_target_rejected(day):
    with pytest.raises(ValueError):w.required_sessions(date.fromisoformat(day))


def test_special_session_23_complete_regular_grid_bars():
    bars=w.warmup_bars(raw(w.SPECIAL),w.SPECIAL)
    assert len(bars)==23
    assert bars[0].ts.strftime('%H:%M')=='14:21'
    assert bars[-1].ts.strftime('%H:%M')=='15:27'
    assert sum(b.volume for b in bars)==69*10


def test_regular_session_125_bars():
    assert len(w.warmup_bars(raw(date(2026,11,20)),date(2026,11,20)))==125


@pytest.mark.parametrize('mutation', ['missing','duplicate','wrong_date','naive','nan','inverted','bad_volume'])
def test_bad_candle_evidence_cannot_pass(mutation):
    day=date(2026,11,20);rows=raw(day)
    if mutation=='missing':rows.pop(30)
    elif mutation=='duplicate':rows[30]=dict(rows[29])
    elif mutation=='wrong_date':rows[-1]['timestamp']='2026-11-19T15:29:00+05:30'
    elif mutation=='naive':rows[0]['timestamp']='2026-11-20T09:15:00'
    elif mutation=='nan':rows[0]['close']=float('nan')
    elif mutation=='inverted':rows[0]['high']=90.
    else:rows[0]['volume']=-1
    with pytest.raises(ValueError):w.validate_rows(rows,day)


def test_seventy_minutes_not_accepted_on_regular_day():
    with pytest.raises(ValueError):w.validate_rows(raw(date(2026,11,20),70),date(2026,11,20))


def test_partial_special_session_rejected():
    with pytest.raises(ValueError):w.validate_rows(raw(w.SPECIAL)[:-1],w.SPECIAL)


def test_exact_utc_times_normalize_to_ist():
    day=date(2026,11,20);rows=raw(day)
    from datetime import timezone
    for r in rows:r['timestamp']=datetime.fromisoformat(r['timestamp']).astimezone(timezone.utc).isoformat()
    assert w.validate_rows(rows,day)==raw(day)


def test_520_old_sessions_do_not_satisfy_recent_coverage(tmp_path):
    target=date(2026,11,23)
    with pytest.raises(ValueError,match='RECENT_WARMUP_MISSING'):
        w.load_warmup({'2026-10-30':cache(tmp_path,date(2026,10,30))},target)


def test_recovery_writes_only_dedicated_cache_and_is_reused(tmp_path):
    target=date(2026,11,23);calls=[]
    class Source:
        def historical_candles(self,instrument,day):
            assert instrument==w.UNDERLYING
            calls.append(day)
            return [Obj(**{**r,'timestamp':datetime.fromisoformat(r['timestamp'])}) for r in raw(day)]
    original=cache(tmp_path/'original',date(2026,10,30));before=original.read_bytes()
    fresh=tmp_path/'verified'
    warm,report=w.load_warmup({'2026-10-30':original},target,source=Source(),fresh_root=fresh)
    assert original.read_bytes()==before and report['freshness_verified']
    assert report['warmup_last']=='2026-11-20'
    assert set(calls)==set(w.required_sessions(target))-{date(2026,10,30)}
    index={'2026-10-30':original,**{p.stem:p for p in fresh.glob('????-??-??.json')}}
    calls.clear()
    _,report=w.load_warmup(index,target,source=Source(),fresh_root=fresh)
    assert not calls and not report['recovered_sessions']
    assert len(w.validate_supplied_warmup(warm,target))==len(warm)


def test_empty_missing_expected_day_is_not_treated_as_holiday(tmp_path):
    class Source:
        def historical_candles(self,*args):return []
    with pytest.raises(ValueError,match='COVERAGE_INVALID'):
        w.load_warmup({},date(2026,11,23),source=Source(),fresh_root=tmp_path)
    assert not list(tmp_path.glob('*.json'))


def test_fetch_error_does_not_expose_provider_strings(tmp_path):
    class Source:
        def historical_candles(self,*args):raise RuntimeError('TOKEN_PRIVATE_SENTINEL')
    with pytest.raises(ValueError) as error:
        w.load_warmup({},date(2026,11,23),source=Source(),fresh_root=tmp_path)
    assert 'TOKEN_PRIVATE_SENTINEL' not in str(error.value)


def test_recording_source_records_recovery_before_return():
    day=w.SPECIAL;calls=[]
    class Source:
        upstream=Obj(historical_candles=lambda *args:[Obj(**{**r,'timestamp':datetime.fromisoformat(r['timestamp'])}) for r in raw(day)])
        def _call(self,kind,args,callback):
            calls.append((kind,args));return callback()
    assert len(w.fetch_session(Source(),day))==70
    assert calls==[('warmup',{'date':'2026-11-08'})]


def test_wrong_instrument_metadata_rejected(tmp_path):
    day=date(2026,11,20);path=cache(tmp_path,day)
    body=json.loads(path.read_text());body['underlying']='OTHER';path.write_text(json.dumps(body))
    with pytest.raises(ValueError,match='IDENTITY'):w.read_session(path,day)


def test_invalid_dedicated_cache_bytes_are_archived_before_repair(tmp_path):
    day=date(2026,11,20);path=tmp_path/(str(day)+'.json');path.write_bytes(b'broken')
    w.save_session(tmp_path,day,raw(day))
    assert len(w.read_session(path,day))==375
    assert [p.read_bytes() for p in tmp_path.glob('*.previous-*')]==[b'broken']


def test_symlink_cache_rejected(tmp_path):
    day=date(2026,11,20);actual=cache(tmp_path/'outside',day)
    link=tmp_path/'link.json';link.symlink_to(actual)
    with pytest.raises(ValueError,match='REGULAR'):w.read_session(link,day)


@pytest.mark.parametrize('change',['missing','duplicate','future'])
def test_direct_replay_cannot_bypass_freshness(change):
    target=date(2026,11,23)
    warm=[(str(d),raw(d)) for d in w.required_sessions(target)]
    if change=='missing':warm.pop()
    elif change=='duplicate':warm.append(warm[0])
    else:warm.append((str(target),raw(target)))
    with pytest.raises(ValueError):w.validate_supplied_warmup(warm,target)


def test_legacy_active_is_not_today_active_and_no_exit_is_invented():
    trade=dict(direction='BULLISH',signal_bar='2026-11-19T14:00:00+05:30',
               strategy_version='old',status='ACTIVE',exit_reason=None,
               legs=[dict(realized_points=None,exit_timestamp=None,current_points=14.35)])
    original=dict(trades=[trade],active_count=1)
    value=current_view(original,'2026-11-23','new')
    assert value['active_count']==0 and value['unresolved_historical_count']==1
    output=value['trades'][0]
    assert output['status']=='UNRESOLVED_HISTORICAL' and output['recorded_status']=='ACTIVE'
    assert output['legs'][0]['realized_points'] is None and output['exit_reason'] is None
    assert original['trades'][0]['status']=='ACTIVE'


def test_today_current_policy_position_remains_active():
    source=dict(trades=[dict(direction='BEARISH',signal_bar='2026-11-23T10:51:00+05:30',
                            strategy_version='new',status='ACTIVE')])
    assert current_view(source,'2026-11-23','new')['active_count']==1


def test_today_older_policy_position_remains_explicitly_unresolved():
    source=dict(trades=[dict(direction='BULLISH',signal_bar='2026-11-23T09:15:00+05:30',
                            strategy_version='old',status='PENDING_EXACT_EXIT')])
    result=current_view(source,'2026-11-23','new')
    assert result['pending_exit_count']==0 and result['unresolved_historical_count']==1
    assert result['trades'][0]['recorded_status']=='PENDING_EXACT_EXIT'


def test_real_live_bootstrap_and_replay_share_validated_inputs(tmp_path,monkeypatch):
    import math
    from market_lab.hilega_three_minute_v1 import hilega_combined_replay_v1 as replay
    from market_lab.hilega_three_minute_v1 import hilega_alignment_dual_exit_live_v1 as live_module
    from market_lab import hilega_manual_exit_strategy_v1 as manual
    target=date(2026,11,23)
    def market_rows(day):
        rows=raw(day)
        for i,r in enumerate(rows):
            price=25000+50*math.sin(i/18)+i/10
            r.update(open=price,high=price+3,low=price-3,close=price+1)
        return rows
    warm=[(str(d),market_rows(d)) for d in w.required_sessions(target)]
    index={d:cache(tmp_path/'cache',date.fromisoformat(d),rows) for d,rows in warm}
    current=market_rows(target)
    source=Obj(nifty_intraday_1m=lambda **kw:[Obj(**{**r,'timestamp':datetime.fromisoformat(r['timestamp'])}) for r in current])
    live=live_module.HilegaAlignmentDualExitLiveCoordinator(market_sources=source,option_expiry=None,
        step_audit_path=tmp_path/'audit.jsonl',health_path=tmp_path/'health.jsonl')
    captured=[];callbacks=[]
    monkeypatch.setattr(live_module,'cache_index',lambda:index)
    monkeypatch.setattr(manual,'apply_manual_control',lambda *a,**kw:False)
    monkeypatch.setattr(manual,'after_bootstrap',lambda *a,**kw:None)
    monkeypatch.setattr(live,'_restore_audited_option_state',lambda **kw:{})
    live._audit=lambda now,stage,status,payload=None,**kw:captured.append((stage,status,payload))
    live._health=lambda *a,**kw:None
    live._start_option=lambda **kw:callbacks.append(('ENTRY',kw['direction'],kw['now'].isoformat()))
    live._close_option=lambda **kw:callbacks.append(('EXIT',kw['direction'],kw['exit_boundary'].isoformat()))
    at=datetime(2026,11,23,15,30,tzinfo=w.IST)
    live.bootstrap(at.replace(hour=9,minute=15))
    live._consume(source.nifty_intraday_1m(),at,recovered=False)
    live.process_cutoff(at,intraday=source.nifty_intraday_1m())
    result=replay.replay(str(target),current,warm)
    actual=[]
    for stage,status,payload in captured:
        if stage not in {'DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF'}:continue
        for event in payload.get('event_details',[]):
            actual.append(('ENTRY' if event['event_type'] in live_module.ENTRY_TYPES else 'EXIT',
                'BEARISH' if 'BEARISH' in event['event_type'] else 'BULLISH',event['event_time'],event['price']))
    expected=[]
    for row in result['audit']:
        for event in row.get('transitions',[]):
            expected.append(('ENTRY' if event['event']=='ENTRY_ACTIVE' else 'EXIT',
                             event['direction'],row['checkpoint'],event['price']))
    assert actual==expected and actual
    assert callbacks==[e[:3] for e in expected]
    assert live.gate.owner=='NONE' and live.gate.locked
    boot=[p for stage,status,p in captured if stage=='DIRECTIONAL_LIVE_BOOTSTRAP'][-1]
    assert boot['warmup_coverage']['warmup_last']=='2026-11-20'
    assert boot['warmup_coverage']['freshness_verified'] is True


def test_live_bootstrap_fails_before_current_processing_when_history_is_stale(tmp_path,monkeypatch):
    from market_lab.hilega_three_minute_v1 import hilega_alignment_dual_exit_live_v1 as module
    calls=[]
    live=module.HilegaAlignmentDualExitLiveCoordinator(
        market_sources=Obj(nifty_intraday_1m=lambda **kw:calls.append('current')),
        option_expiry=None,step_audit_path=tmp_path/'audit',health_path=tmp_path/'health')
    monkeypatch.setattr(module,'cache_index',lambda:{})
    with pytest.raises(ValueError,match='WARMUP_FETCH_FAILED'):
        live.bootstrap(datetime(2026,11,23,9,18,tzinfo=w.IST))
    assert not calls and live._bootstrapped_date is None
