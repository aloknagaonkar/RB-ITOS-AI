import pytest
from datetime import datetime,timedelta
from market_lab.hilega_execution_port_v1 import availability
from market_lab.hilega_execution_port_v1.port import ClosedPort,PortBlocked
AT=datetime.fromisoformat('2026-10-26T09:25:00+05:30')
CONTRACT=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY');monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    clock=[AT-timedelta(seconds=1)];p=ClosedPort(tmp_path/'port',mode='OFFLINE_FIXTURE',clock=lambda:clock[0])
    p.fund_synthetic('100000');p.resume_next_fresh();clock[0]=AT
    return p,clock

def enter(env):return env[0].enter(signal_id='fresh',signal_at=AT.isoformat(),contract=CONTRACT)
def fill(oid,side,quantity,when,tid):return dict(order_id=oid,trade_id=tid,instrument='NSE_FO|12345',product='I',side=side,quantity=quantity,price='100',filled_at=when.isoformat())
def snapshot(port,sid,when,trades):
    orders=[];positions={}
    for o in port.adapter.transport.orders():
        orders.append(dict(order_id=o['order_id'],instrument=o['instrument'],product=o['product'],side=o['side'],quantity=o['quantity'],filled=o['filled'],pending=0 if o['status'] in {'FILLED','CANCELLED','REJECTED'} else o['quantity']-o['filled'],status=o['status']))
        k=(o['instrument'],o['product']);positions[k]=positions.get(k,0)+(o['filled'] if o['side']=='BUY' else -o['filled'])
    return dict(evidence_mode='OFFLINE_FIXTURE',account_scope=port.adapter.store.scope,complete=True,snapshot_id=sid,observed_at=when.isoformat(),orders=orders,trades=trades,positions=[dict(instrument=k[0],product=k[1],quantity=v) for k,v in positions.items()])

def complete(env):
    p,clock=env;r=enter(env);cid=r['controller_id'];oid=p.adapter.status()['requests'][0]['order_id']
    p.fixture_fill(cid,20);p.cancel_entry(cid);trades=[fill(oid,'BUY',20,clock[0],'buy1')]
    p.reconcile_offline(snapshot(p,'partial',clock[0],trades));clock[0]+=timedelta(seconds=5)
    p.prepare_fixture_exit(cid,request_id='exit1',quantity=20,contract=CONTRACT);p.fixture_fill('exit1',20)
    sell=next(x['order_id'] for x in p.adapter.status()['requests'] if x['request_id']=='exit1')
    trades.append(fill(sell,'SELL',20,clock[0],'sell1'));p.reconcile_offline(snapshot(p,'flat',clock[0],trades));return cid

def test_consolidated_full_cycle_and_exactly_once_release(env):
    p,_=env;cid=complete(env)
    r=p.release_offline(cid,snapshot_id='flat',request_id='release1')
    assert r['release_applied'] and p.status()['release_consumer']['held_cents']==0
    assert p.release_offline(cid,snapshot_id='flat',request_id='release1')['idempotent_replay']
    assert p.status()['controller']['control']['mode']=='PAUSED' and p.status()['simulator_fill_count']==0

def test_closed_gate_runs_no_token_or_network(env,tmp_path):
    clock=env[1];clock[0]=AT-timedelta(seconds=1);p=ClosedPort(tmp_path/'closed',mode='LIVE_CLOSED',clock=lambda:clock[0])
    p.fund_synthetic('100000');p.resume_next_fresh();clock[0]=AT
    r=p.enter(signal_id='closed',signal_at=AT.isoformat(),contract=CONTRACT)
    assert r['adapter_result']['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE'
    assert not p.status()['adapter']['attempts'] and p.status()['controller']['allocation']['held_total']=='0.00'

def test_pause_vetoes_entry(env):
    p,_=env;p.pause()
    with pytest.raises(Exception):enter(env)
    assert not p.status()['adapter']['attempts']

def test_unknown_acceptance_retains_hold_and_blocks(env):
    p,_=env;p.adapter.transport.timeout_after=True;enter(env)
    assert p.status()['controller']['allocation']['held_total']=='6600.00'
    assert p.status()['controller']['control']['mode']=='PAUSED'
    with pytest.raises(Exception):p.resume_next_fresh()

def test_reopen_recovers_paused_without_second_post(env):
    p,clock=env;enter(env);directory=p.directory
    recovered=ClosedPort.open(directory,clock=lambda:clock[0])
    assert recovered.status()['controller']['control']['mode']=='PAUSED'
    assert len(recovered.adapter.transport.orders())==1 and recovered.status()['controller']['allocation']['held_total']=='6600.00'

def test_stale_proof_rejects_first_release(env):
    p,clock=env;cid=complete(env);clock[0]+=timedelta(seconds=31)
    with pytest.raises(Exception):p.release_offline(cid,snapshot_id='flat',request_id='release1')
    assert p.status()['release_consumer']['held_cents']==660000

def test_fresh_directory_and_explicit_modes_required(env):
    p,_=env
    with pytest.raises(PortBlocked):ClosedPort(p.directory,mode='OFFLINE_FIXTURE')
    with pytest.raises(PortBlocked):ClosedPort(p.directory/'other',mode='LIVE')

def test_availability_does_not_claim_active_routing():
    r=availability();assert r['production_execution_enabled'] is False and r['live_routing_implemented'] is False

def test_invalid_contract_after_prepare_pauses_and_retains(env):
    p,_=env;c=dict(CONTRACT);c.pop('expiry')
    with pytest.raises(Exception):p.enter(signal_id='fresh',signal_at=AT.isoformat(),contract=c)
    assert p.status()['controller']['control']['mode']=='PAUSED' and not p.status()['adapter']['attempts']

def test_offline_evidence_cannot_be_used_in_closed_http_port(env,tmp_path):
    p=ClosedPort(tmp_path/'closed2',mode='LIVE_CLOSED')
    with pytest.raises(PortBlocked):p.reconcile_offline({})

def test_legacy_resume_not_bypassed_after_offline_settlement(env):
    p,_=env;cid=complete(env);p.release_offline(cid,snapshot_id='flat',request_id='release1')
    with pytest.raises(Exception):p.resume_next_fresh()
    assert p.status()['controller']['control']['mode']=='PAUSED'
