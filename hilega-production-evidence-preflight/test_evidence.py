"""Synthetic signed records only. No live provenance or trading approval claimed."""
import copy
import json
import sqlite3
from datetime import datetime,timedelta
import pytest
from evidence import MODEL,MODE,FLAGS,validate,evaluate,Blocked
from market_lab.hilega_production_account_adapter_v1 import sign
from market_lab.hilega_production_foundation.core import Store,encode
from market_lab.hilega_production_bridge_health_v1 import MODEL as HEALTH_MODEL

T=datetime.fromisoformat('2026-10-26T09:25:00+05:30')
PIN=dict(scope='UPSTOX:'+'b'*64,key='11'*32)


def ts(seconds=0):return (T+timedelta(seconds=seconds)).isoformat()


def resign(bundle):
    bundle.pop('signature',None)
    bundle['signature']=sign(bundle,PIN)
    return bundle


def resign_cash(bundle):
    cash=bundle['cash_capture'];cash.pop('signature',None);cash['signature']=sign(cash,PIN)
    return resign(bundle)


def bundle():
    funds=dict(cash_available_to_trade='100000',cash_margin_used='0',
               field='data.available_to_trade.cash_available_to_trade.total')
    cash=dict(model='HILEGA_READ_ONLY_CASH_OBSERVATION_V1',evidence_mode=MODE,
        snapshot_id='synthetic-cash',account_scope=PIN['scope'],account_identity_verified=True,
        status='READ_ONLY_CAPTURED',started_at=ts(1),completed_at=ts(2),session_date='2026-10-26',
        production_execution_enabled=False,orders_sent=False,entry_permission=False,
        funds_before=copy.deepcopy(funds),funds_after=copy.deepcopy(funds),
        funds_changed_during_capture=False,orders=[],trades=[],positions=[],
        diagnostics=dict(issues=[]),account_position_rows_complete=True)
    cash['signature']=sign(cash,PIN)
    contracts=[]
    for strike in (24950,25000,25050):
        for side in ('CE','PE'):
            contracts.append(dict(instrument_key='NSE_FO|'+str(strike*10+(1 if side=='CE' else 2)),
                underlying_key='NSE_INDEX|Nifty 50',instrument_type=side,segment='NSE_FO',exchange='NSE',
                expiry='2026-10-27',strike_price=strike,lot_size=65,minimum_lot=65,
                freeze_quantity=1800,tick_size=5))
    quotes={'underlying':dict(instrument_token='NSE_INDEX|Nifty 50',last_price=25000,timestamp=ts(2))}
    for c in contracts:
        if c['strike_price']==25000:
            quotes[c['instrument_key']]=dict(instrument_token=c['instrument_key'],last_price=100,
                timestamp=ts(2),last_trade_time=ts(2),volume=10000,
                depth=dict(buy=[dict(price=99.95,quantity=130)],sell=[dict(price=100,quantity=130)]))
    result=dict(model=MODEL,evidence_mode=MODE,snapshot_id='synthetic-bundle',account_scope=PIN['scope'],
        started_at=ts(),completed_at=ts(3),session_date='2026-10-26',profile_verified_before_and_after=True,
        market_before=dict(exchange='NSE',status='NORMAL_OPEN'),market_after=dict(exchange='NSE',status='NORMAL_OPEN'),
        cash_before_market=copy.deepcopy(funds),cash_after_market=copy.deepcopy(funds),cash_capture=cash,
        spot_initial=25000,contracts=contracts,quotes=quotes,**FLAGS)
    return resign(result)


@pytest.fixture
def env(tmp_path):
    controller=tmp_path/'controller.sqlite';adapter=tmp_path/'adapter.sqlite'
    store=Store(controller)
    store.save_control(dict(mode='ARMED',version=3,session_date='2026-10-26',reconciled=True,
                           last_reconciled_at=ts(),resumed_at=ts(-1)))
    health=dict(model=HEALTH_MODEL,required=True,run_id='synthetic-lease',pid=1,phase='RUNNING',
                heartbeat_at=ts(2),source_at=ts(),session_date='2026-10-26')
    with store.db() as db:db.execute('INSERT INTO sim_bridge_health VALUES(1,?)',(encode(health),))
    with sqlite3.connect(adapter) as db:
        db.executescript('CREATE TABLE meta(id INTEGER PRIMARY KEY,data TEXT); CREATE TABLE requests(id TEXT); CREATE TABLE attempts(id TEXT); CREATE TABLE receipts(id TEXT);')
        db.execute('INSERT INTO meta VALUES(1,?)',(encode(dict(scope=PIN['scope'],mode='LIVE_CLOSED')),))
    return dict(store=store,controller=controller,adapter=adapter,bundle=bundle())


def assess(env,**changes):
    args=dict(direction='BULLISH',as_of=ts(3),controller_db=env['controller'],adapter_db=env['adapter'],
              expected_version=3,bridge_run_id='synthetic-lease',signal_at=ts())
    args.update(changes)
    return evaluate(env['bundle'],PIN,**args)


def option_quote(b):
    return next(v for v in b['quotes'].values() if v['instrument_token'].startswith('NSE_FO|'))


def test_both_directions_bound_to_signed_metadata_and_quotes(env):
    plans=validate(env['bundle'],PIN,as_of=ts(3))
    assert {p['direction'] for p in plans}=={'BULLISH','BEARISH'}
    assert all(p['evidence_checks_passed'] and p['quantity']==65 for p in plans)
    assert all(p['proposed_cost_cents']==660000 for p in plans)
    assert all(p['bundle_fingerprint'] and p['contract_fingerprint'] and p['quote_fingerprint'] for p in plans)
    assert all(p['executable_request_created'] is False and p['tick_units_verified'] is False for p in plans)


def test_preflight_pass_has_no_authority(env):
    result=assess(env)
    assert result['status']=='READ_ONLY_PREFLIGHT_CHECKS_PASS'
    for key in FLAGS:assert result[key] is False
    assert result['production_ready'] is False


def test_source_databases_unchanged(env):
    before=[env[k].read_bytes() for k in ('controller','adapter')]
    assess(env)
    assert before==[env[k].read_bytes() for k in ('controller','adapter')]


def test_outer_signature_tamper(env):
    env['bundle']['spot_initial']=25001
    assert assess(env)['reasons']==['BUNDLE_SIGNATURE_INVALID']


def test_nested_signature_checked(env):
    env['bundle']['cash_capture']['funds_after']['cash_available_to_trade']='1'
    resign(env['bundle'])
    assert assess(env)['reasons']==['CAPTURE_SIGNATURE_INVALID']


def test_cross_account_outer(env):
    env['bundle']['account_scope']='other';resign(env['bundle'])
    assert assess(env)['reasons']==['BUNDLE_ACCOUNT_SCOPE_MISMATCH']


def test_cross_account_cash(env):
    env['bundle']['cash_capture']['account_scope']='other';resign_cash(env['bundle'])
    assert assess(env)['reasons']==['ACCOUNT_SCOPE_UNVERIFIED']


def test_synthetic_mode_cannot_pass_as_live(env):
    env['bundle']['evidence_mode']='EXPLICIT_STAGED_FIXTURE';resign(env['bundle'])
    assert assess(env)['reasons']==['LIVE_SIGNED_BUNDLE_REQUIRED']


@pytest.mark.parametrize('at',[ts(31),ts(2),(T+timedelta(days=1)).isoformat()])
def test_stale_future_or_wrong_session_bundle(env,at):
    assert assess(env,as_of=at)['status']=='BLOCKED'


def test_closed_market_is_not_cleared(env):
    env['bundle']['market_after']['status']='CLOSED';resign(env['bundle'])
    assert 'MARKET_NOT_NORMAL_OPEN' in assess(env)['reasons']


def test_zero_cash_is_capacity_blocker_not_failure_to_capture(env):
    b=env['bundle']
    for funds in (b['cash_before_market'],b['cash_after_market'],b['cash_capture']['funds_before'],b['cash_capture']['funds_after']):
        funds['cash_available_to_trade']='0'
    resign_cash(b)
    result=assess(env)
    assert result['status']=='NOT_CLEARED' and 'NO_CASH_CAPACITY' in result['reasons']


def test_market_sweep_cash_drift(env):
    env['bundle']['cash_after_market']['cash_available_to_trade']='99999';resign(env['bundle'])
    assert assess(env)['reasons']==['FUNDS_CHANGED_DURING_BUNDLE']


def test_account_exposure_blocks_new_preview(env):
    b=env['bundle'];b['cash_capture']['positions']=[dict(instrument='NSE_FO|1',product='I',quantity=65)]
    resign_cash(b)
    assert 'ACCOUNT_EXPOSURE_OWNERSHIP_UNVERIFIED' in assess(env)['reasons']


def test_unsigned_preview_not_accepted(env):
    env['bundle']={'status':'READ_ONLY_CHECKS_PASS'}
    assert assess(env)['status']=='BLOCKED'


def test_duplicate_atm_contract(env):
    b=env['bundle'];b['contracts'].append(copy.deepcopy(b['contracts'][2]));resign(b)
    assert assess(env)['status']=='BLOCKED'


def test_missing_option_quote(env):
    b=env['bundle'];key=option_quote(b)['instrument_token'];del b['quotes'][key];resign(b)
    assert assess(env)['status']=='BLOCKED'


def test_atm_changed(env):
    b=env['bundle'];b['quotes']['underlying']['last_price']=25030;resign(b)
    assert assess(env)['reasons']==['ATM_CHANGED_DURING_BUNDLE']


def test_stale_underlying(env):
    b=env['bundle'];b['quotes']['underlying']['timestamp']=ts(-20);resign(b)
    assert 'UNDERLYING_QUOTE_STALE_OR_FUTURE' in assess(env)['reasons']


@pytest.mark.parametrize('change,reason',[
    ('stale','QUOTE_STALE_OR_FUTURE'),('old_trade','LAST_TRADE_STALE_OR_FUTURE'),
    ('wide','SPREAD_ABOVE_PREVIEW_LIMIT'),('depth','BEST_ASK_DEPTH_BELOW_QUANTITY'),
    ('volume','ZERO_VOLUME'),('crossed','CROSSED_BOOK')])
def test_quote_quality(env,change,reason):
    b=env['bundle'];q=option_quote(b)
    if change=='stale':q['timestamp']=ts(-20)
    elif change=='old_trade':q['last_trade_time']=ts(-90)
    elif change=='wide':q['depth']['buy'][0]['price']=90
    elif change=='depth':q['depth']['sell'][0]['quantity']=1
    elif change=='volume':q['volume']=0
    elif change=='crossed':q['depth']['buy'][0]['price']=101
    resign(b)
    assert reason in assess(env)['reasons']


def test_paused_controller_does_not_hide_good_evidence(env):
    c=env['store'].control();c['mode']='PAUSED';env['store'].save_control(c)
    result=assess(env)
    assert result['evidence_checks_passed'] is True
    assert result['control_checks_passed'] is False and 'CONTROLLER_PAUSED' in result['reasons']


def test_wrong_control_version(env):
    assert 'CONTROL_VERSION_MISMATCH' in assess(env,expected_version=2)['reasons']


def test_pending_stop(env):
    with env['store'].db() as db:db.execute('UPDATE sim_stop_state SET generation=1 WHERE id=1')
    assert 'DURABLE_STOP_PENDING' in assess(env)['reasons']


def test_stale_reconciliation(env):
    c=env['store'].control();c['last_reconciled_at']=ts(-40);env['store'].save_control(c)
    assert 'CONTROLLER_RECONCILIATION_STALE_OR_FUTURE' in assess(env)['reasons']


def test_wrong_bridge_lease(env):
    assert 'BRIDGE_LEASE_MISMATCH' in assess(env,bridge_run_id='wrong')['reasons']


def test_pre_resume_signal(env):
    assert 'PRE_RESUME_SIGNAL_NOT_ELIGIBLE' in assess(env,signal_at=ts(-1))['reasons']


@pytest.mark.parametrize('table',['requests','attempts','receipts'])
def test_existing_adapter_activity_retained_for_review(env,table):
    with sqlite3.connect(env['adapter']) as db:db.execute('INSERT INTO '+table+' VALUES(?)',('synthetic',))
    assert 'EXISTING_ADAPTER_ACTIVITY_REQUIRES_REVIEW' in assess(env)['reasons']


def test_adapter_fixture_scope_rejected(env):
    with sqlite3.connect(env['adapter']) as db:
        db.execute('UPDATE meta SET data=?',(encode(dict(scope=PIN['scope'],mode='OFFLINE_FIXTURE')),))
    assert assess(env)['reasons']==['ADAPTER_SCOPE_OR_MODE_MISMATCH']


def test_missing_database_is_not_created(env):
    env['adapter'].unlink()
    assert assess(env)['status']=='BLOCKED'
    assert not env['adapter'].exists()


def test_collector_uses_expected_read_paths_and_signs_bundle(monkeypatch):
    import collect
    from types import SimpleNamespace
    from evidence import dependencies
    b=bundle();calls=[];rules,_=dependencies()
    class Clock:
        count=0
        @classmethod
        def now(cls,tz):
            value=T+timedelta(seconds=0 if cls.count==0 else 3)
            cls.count+=1
            return value.astimezone(tz)
    class Account:
        def __init__(self,token):assert token=='SYNTHETIC_TEST_TOKEN'
        def get(self,name):
            assert name in {'profile','funds'}
            calls.append(name)
            return PIN['scope'] if name=='profile' else copy.deepcopy(b['cash_before_market'])
    class Market:
        def __init__(self,token):assert token=='SYNTHETIC_TEST_TOKEN'
        def get(self,name,keys=None):
            assert name in {'market','quotes','contracts'}
            calls.append(name)
            if name=='market':return dict(exchange='NSE',status='NORMAL_OPEN')
            if name=='contracts':return copy.deepcopy(b['contracts'])
            return {k:copy.deepcopy(v) for k,v in b['quotes'].items() if v['instrument_token'] in keys}
    def match(profile,pin):assert profile==pin['scope']
    monkeypatch.setattr(collect,'datetime',Clock)
    monkeypatch.setattr(collect,'Client',Account)
    monkeypatch.setattr(collect,'matches',match)
    monkeypatch.setattr(collect,'collectors',lambda:(rules,SimpleNamespace(MarketClient=Market),
        SimpleNamespace(capture=lambda account,pin:copy.deepcopy(b['cash_capture'])),
        SimpleNamespace(funds=lambda value:value)))
    result=collect.capture('SYNTHETIC_TEST_TOKEN',PIN)
    assert all(p['evidence_checks_passed'] for p in validate(result,PIN,as_of=ts(3)))
    assert calls.count('profile')==2 and calls.count('funds')==2
    assert calls.count('market')==2 and calls.count('quotes')==2 and calls.count('contracts')==1


def test_capture_only_cli_needs_no_strategy_signal(env,monkeypatch,capsys,tmp_path):
    from evidence import load,ROOT
    module=load(ROOT/'hilega-production-evidence-preflight/run.py','preflight_cli_test')
    output=tmp_path/'capture-only'
    monkeypatch.setattr(module,'dotenv_values',lambda path:{'UPSTOX_ACCESS_TOKEN':'SYNTHETIC_TEST_TOKEN'})
    monkeypatch.delenv('UPSTOX_ACCESS_TOKEN',raising=False)
    monkeypatch.delenv('HILEGA_PRODUCTION_BROKER_READ_TOKEN',raising=False)
    monkeypatch.setattr(module,'read_pin',lambda path:PIN)
    monkeypatch.setattr(module,'capture',lambda token,pin:copy.deepcopy(env['bundle']))
    monkeypatch.setattr(module,'utcnow',lambda:T+timedelta(seconds=3))
    monkeypatch.setattr('sys.argv',['run.py','--capture-only','--output',str(output)])
    assert module.main()==0
    public=json.loads(capsys.readouterr().out)
    assert public['controller_checks_performed'] is False
    assert 'preparation_preview' not in public and 'controls' not in public
    assert PIN['scope'] not in json.dumps(public) and PIN['key'] not in json.dumps(public)
    assert (output/'evidence.json').is_file() and (output/'report.json').is_file()


def test_cli_existing_output_is_not_modified(env,monkeypatch,capsys,tmp_path):
    from evidence import load,ROOT
    module=load(ROOT/'hilega-production-evidence-preflight/run.py','preflight_cli_existing_test')
    output=tmp_path/'existing';output.mkdir();(output/'keep.txt').write_text('untouched')
    monkeypatch.setattr('sys.argv',['run.py','--capture-only','--output',str(output)])
    assert module.main()==2
    assert sorted(p.name for p in output.iterdir())==['keep.txt']
