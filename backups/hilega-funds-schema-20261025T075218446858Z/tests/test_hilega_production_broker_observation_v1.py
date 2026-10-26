"""Offline fixtures only. Never call broker or submit orders."""
import copy,json
from datetime import datetime,timedelta,timezone
import pytest
from market_lab import hilega_production_broker_observation_v1 as b

AT=datetime(2026,10,25,7,30,tzinfo=timezone.utc)
def fixtures():
    return {'profile':{'status':'success','data':{'user_id':'must-not-leak'}},
      'orders':{'status':'success','data':[]},'trades':{'status':'success','data':[]},
      'positions':{'status':'success','data':[]},'funds':{'status':'success','data':{'available_to_trade':{
        'total':99999,'cash_available_to_trade':{'total':10000.03,'margin_used':{'total':2000}},
        'pledge_available_to_trade':{'total':80000}}}}}
def snapshot():return b.collect(fixtures().__getitem__,AT)
def order(**kw):
    return dict(order_id='o1',instrument_token='NSE_FO|1',product='I',transaction_type='BUY',
                status='open',quantity=65,filled_quantity=20,pending_quantity=45,average_price=100,**kw)
def trade():
    return dict(trade_id='t1',order_id='o1',instrument_token='NSE_FO|1',product='I',transaction_type='BUY',quantity=20,average_price=100)
def checked(o=None,t=None,p=None):
    f=fixtures();f['orders']['data']=o or [];f['trades']['data']=t or [];f['positions']['data']=p or []
    return {n:b.sanitize(f[n],n) for n in b.PATHS}
@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_OBSERVE','0')
    class OfflineOpener:
        def open(self,*a,**kw):pytest.fail('NETWORK_FORBIDDEN_IN_TEST')
    monkeypatch.setattr(b,'build_opener',lambda *a:OfflineOpener())

def test_disabled_does_not_read(monkeypatch,tmp_path):
    assert b.display(tmp_path/'missing',AT)['status']=='NOT_ENABLED'
def test_missing_cache_unknown(monkeypatch,tmp_path):
    monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_OBSERVE','1')
    d=b.display(tmp_path/'missing',AT);assert d['positions'] is None and not d['broker_connected']
def test_fresh_empty_snapshot(monkeypatch,tmp_path):
    monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_OBSERVE','1')
    p=tmp_path/'snap';b.write_snapshot(snapshot(),p);d=b.display(p,AT)
    assert d['status']=='LIVE_READ_ONLY' and d['positions']==[]
    assert d['ownership']=='NOT_MAPPED' and d['live_pnl'] is None
@pytest.mark.parametrize('seconds',[-1,91,86400])
def test_stale_or_future_hides_values(monkeypatch,tmp_path,seconds):
    monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_OBSERVE','1')
    p=tmp_path/'snap';b.write_snapshot(snapshot(),p);d=b.display(p,AT+timedelta(seconds=seconds))
    assert d['status']=='STALE' and d['positions'] is None and d['funds'] is None

def test_fixture_mode_rejected(monkeypatch,tmp_path):
    monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_OBSERVE','1')
    s=snapshot();s['evidence_mode']='OFFLINE_FIXTURE';p=tmp_path/'snap';b.write_snapshot(s,p)
    assert b.display(p,AT)['status']=='UNAVAILABLE'
def test_corrupt_cache_unknown(monkeypatch,tmp_path):
    monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_OBSERVE','1');p=tmp_path/'snap';p.write_text('{')
    assert b.display(p,AT)['positions'] is None

def test_cash_excludes_pledge_and_does_not_subtract_used_twice():
    c=b.sanitize(fixtures()['funds'],'funds')
    assert c['cash_available_to_trade']==10000.03 and c['half_cash_preview']=='5000.01'
    assert not c['allocation_approved'] and c['mapping_status']=='PENDING_ACCOUNT_COMPARISON'
@pytest.mark.parametrize('value',[None,True,float('nan'),float('inf'),'1000'])
def test_invalid_cash_rejected(value):
    f=fixtures()['funds'];f['data']['available_to_trade']['cash_available_to_trade']['total']=value
    assert b.sanitize(f,'funds')['status']=='FAIL'
def test_negative_cash_no_spend():
    f=fixtures()['funds'];f['data']['available_to_trade']['cash_available_to_trade']['total']=-50
    assert b.sanitize(f,'funds')['half_cash_preview']=='0.00'
def test_no_v2_margin_fallback():
    assert b.sanitize({'status':'success','data':{'equity':{'available_margin':10000}}},'funds')['status']=='FAIL'
def test_profile_details_removed():
    assert b.sanitize(fixtures()['profile'],'profile')=={'status':'PASS'}
def test_access_block_stops_remaining_gets():
    calls=[]
    def get(n):calls.append(n);return b.failure('HTTP_403',True,'CLOUDFLARE_1010')
    s=b.collect(get,AT)
    assert calls==['profile'] and s['halt'] and s['checks']['positions']['status']=='FAIL'
def test_transient_failure_not_halted():
    def get(n):return b.failure('NETWORK_OR_TIMEOUT') if n=='orders' else fixtures()[n]
    s=b.collect(get,AT);assert not s['halt'] and s['connection_status']=='FAIL'
def test_partial_fills_consistent():
    d=b.fill_diagnostics(checked([order()],[trade()]))
    assert d['status']=='CONSISTENT_ACCOUNT_SNAPSHOT' and d['position_fill_linkage']=='NOT_VALIDATED'
def test_duplicate_trade_not_double_counted():
    d=b.fill_diagnostics(checked([order()],[trade(),trade()]))
    assert d['issues']==['DUPLICATE_TRADE_ID']
def test_missing_fill_blocks_consistency():
    assert 'ORDER_FILL_TOTAL_MISMATCH' in b.fill_diagnostics(checked([order()]))['issues']
def test_identity_mismatch():
    t=trade();t['product']='D'
    assert 'TRADE_ORDER_IDENTITY_MISMATCH' in b.fill_diagnostics(checked([order()],[t]))['issues']
def test_unmatched_trade():
    assert 'TRADE_WITHOUT_ORDER' in b.fill_diagnostics(checked(t=[trade()]))['issues']
def test_duplicate_order():
    assert 'DUPLICATE_ORDER_ID' in b.fill_diagnostics(checked([order(),order()],[trade()]))['issues']
def test_position_not_inferred_from_daily_fills():
    p=dict(instrument_token='NSE_FO|1',product='I',quantity=100)
    d=b.fill_diagnostics(checked([order()],[trade()],[p]))
    assert d['ownership']=='NOT_MAPPED' and not d['application_state_updated']
def test_unknown_positions_not_flat():
    c=checked();c['positions']=b.failure('HTTP_403',True)
    assert b.fill_diagnostics(c)['status']=='UNKNOWN'
def test_invalid_quantities():
    o=order();o['filled_quantity']=100
    assert b.sanitize(dict(status='success',data=[o]),'orders')['status']=='FAIL'
def test_provider_text_not_persisted():
    c=b.sanitize({'status':'error','error':'SECRET_RESPONSE','message':'TOKEN'},'orders')
    assert 'SECRET_RESPONSE' not in json.dumps(c) and 'TOKEN' not in json.dumps(c)
def test_invalid_endpoint_rejected():
    with pytest.raises(ValueError):b.Client('token').get('place_order')
def test_cached_fields_revalidated(monkeypatch,tmp_path):
    monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_OBSERVE','1')
    s=snapshot();s['checks']['positions']['rows']=[{'instrument_token':'x','product':'I','quantity':True}]
    p=tmp_path/'snap';b.write_snapshot(s,p);d=b.display(p,AT)
    assert not d['broker_connected'] and d['positions'] is None

def test_workspace_keeps_real_and_simulator_separate(monkeypatch,tmp_path):
    from market_lab import hilega_production_workspace_v1 as w
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY')
    monkeypatch.setenv('HILEGA_PRODUCTION_SIM_DB',str(tmp_path/'sim.sqlite'))
    monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_OBSERVE','1')
    p=tmp_path/'snap';s=snapshot();s['generated_at']=b.now().isoformat();s['session_date']=b.now().astimezone(b.ZoneInfo('Asia/Kolkata')).date().isoformat()
    b.write_snapshot(s,p);monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_SNAPSHOT',str(p))
    r=w.report()
    assert r['broker_observation']['broker_connected']
    assert not r['broker_connected'] and r['available_cash'] is None
    assert not r['production_execution_enabled'] and not r['strategy_worker_controlled']
    assert all(x['status']=='NOT_VALIDATED' for x in r['readiness_checks'])

def test_missing_token_monitor_does_not_use_network(monkeypatch,tmp_path):
    import asyncio
    monkeypatch.delenv('HILEGA_PRODUCTION_BROKER_READ_TOKEN',raising=False)
    monkeypatch.delenv('UPSTOX_ACCESS_TOKEN',raising=False)
    p=tmp_path/'snap';monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_SNAPSHOT',str(p))
    asyncio.run(b.monitor())
    assert json.loads(p.read_text())['halt'] is True

def test_request_is_allowlisted_get_and_identifies_application(monkeypatch):
    requests=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):return b'{"status":"success","data":{}}'
    class Opener:
        def open(self,r,timeout):requests.append(r);return Response()
    monkeypatch.setattr(b,'build_opener',lambda *a:Opener())
    c=b.Client('SECRET');c.get('funds')
    r=requests[0]
    assert r.get_method()=='GET' and r.full_url=='https://api.upstox.com/v3/user/get-funds-and-margin'
    assert r.get_header('Api-version')=='3.0' and 'RB-ITOS-AI' in r.get_header('User-agent')
