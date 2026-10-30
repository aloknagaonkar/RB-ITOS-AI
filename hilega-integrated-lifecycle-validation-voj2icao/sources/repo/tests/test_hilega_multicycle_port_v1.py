from datetime import datetime,timedelta
import json
import pytest
from market_lab.hilega_execution_port_v1.port import ClosedPort
AT=datetime.fromisoformat('2026-10-26T09:25:00+05:30')
C1=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
C2=dict(C1,instrument_key='NSE_FO|54321',instrument_type='PE')
@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY');monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    clock=[AT-timedelta(seconds=1)];p=ClosedPort(tmp_path/'port',mode='OFFLINE_FIXTURE',clock=lambda:clock[0]);p.fund_synthetic('100000');p.resume_next_fresh();clock[0]=AT
    return dict(port=p,clock=clock,trades=[],counter=0)

def snapshot(e,key):
    p=e['port'];orders=[];positions={}
    for o in p.adapter.transport.orders():
        orders.append(dict(order_id=o['order_id'],instrument=o['instrument'],product=o['product'],side=o['side'],quantity=o['quantity'],filled=o['filled'],pending=0 if o['status'] in {'FILLED','CANCELLED','REJECTED'} else o['quantity']-o['filled'],status=o['status']))
        pair=(o['instrument'],o['product']);positions[pair]=positions.get(pair,0)+(o['filled'] if o['side']=='BUY' else -o['filled'])
    return dict(evidence_mode='OFFLINE_FIXTURE',account_scope=p.adapter.store.scope,snapshot_id=key,observed_at=e['clock'][0].isoformat(),complete=True,orders=orders,trades=list(e['trades']),positions=[dict(instrument=k[0],product=k[1],quantity=v) for k,v in positions.items()])
def explicit_fill(e,rid,quantity,tid):
    p=e['port'];p.fixture_fill(rid,quantity)
    row=next(x for x in p.adapter.store.requests() if x['request_id']==rid);b=row['draft']['body']
    e['trades'].append(dict(order_id=row['order_id'],trade_id=tid,instrument=b['instrument_token'],product=b['product'],side=b['transaction_type'],quantity=quantity,price='100',filled_at=e['clock'][0].isoformat()))
def start(e,n,contract=C1):
    p=e['port'];r=p.enter(signal_id='signal-'+str(n),signal_at=e['clock'][0].isoformat(),contract=contract);return r['controller_id']
def finish(e,cid,n,contract=C1,*,pending=False):
    p=e['port'];explicit_fill(e,cid,20,'buy-'+str(n));p.cancel_entry(cid)
    p.reconcile_offline(snapshot(e,'partial-'+str(n)));e['clock'][0]+=timedelta(seconds=2)
    p.prepare_fixture_exit(cid,request_id='exit-'+str(n),quantity=20,contract=contract)
    if pending:
        p.reconcile_offline(snapshot(e,'pending-'+str(n)));return
    explicit_fill(e,'exit-'+str(n),20,'sell-'+str(n));p.reconcile_offline(snapshot(e,'flat-'+str(n)))
    return p.release_offline(cid,snapshot_id='flat-'+str(n),request_id='release-'+str(n))
def first(e):
    cid=start(e,1);finish(e,cid,1);return cid

def test_two_complete_cycles_with_explicit_resume_and_new_signals(env):
    e=env;p=e['port'];first(e)
    assert p.status()['controller']['control']['mode']=='PAUSED'
    p.resume_next_fresh();e['clock'][0]+=timedelta(seconds=1)
    cid=start(e,2,C2);finish(e,cid,2,C2)
    state=p.status();assert len(state['release_consumer']['receipts'])==2 and state['release_consumer']['held_cents']==0
    assert len(p.adapter.transport.orders())==4 and state['simulator_fill_count']==0 and state['controller']['control']['mode']=='PAUSED'

def test_pending_sell_blocks_resume_and_opposite_entry(env):
    e=env;p=e['port'];cid=start(e,1);finish(e,cid,1,pending=True)
    with pytest.raises(Exception):p.resume_next_fresh()
    with pytest.raises(Exception):start(e,2,C2)
    assert len(p.adapter.transport.orders())==2 and p.status()['controller']['allocation']['held_total']=='6600.00'

def test_pause_during_exit_requires_fresh_explicit_resume(env):
    e=env;p=e['port'];cid=start(e,1);finish(e,cid,1,pending=True);old=p.status()['controller']['control']
    p.pause();explicit_fill(e,'exit-1',20,'sell-1');p.reconcile_offline(snapshot(e,'flat-1'));p.release_offline(cid,snapshot_id='flat-1',request_id='release-1')
    assert p.status()['controller']['control']['mode']=='PAUSED' and len(p.adapter.transport.orders())==2
    with pytest.raises(Exception):p.resume_next_fresh(expected_version=old['version'],session_date=old['session_date'])
    p.resume_next_fresh();e['clock'][0]+=timedelta(seconds=1);start(e,2,C2)
    assert len(p.adapter.transport.orders())==3

def test_pre_resume_or_same_boundary_signal_not_replayed(env):
    e=env;p=e['port'];first(e);prior_signal=e['clock'][0].isoformat();p.resume_next_fresh()
    with pytest.raises(Exception):p.enter(signal_id='stale-continuation',signal_at=prior_signal,contract=C2)
    assert len(p.adapter.transport.orders())==2

def test_reopen_requires_new_snapshot_before_resume(env):
    e=env;p=e['port'];first(e);directory=p.directory
    e['port']=p=ClosedPort.open(directory,clock=lambda:e['clock'][0])
    with pytest.raises(Exception):p.resume_next_fresh()
    assert p.status()['controller']['control']['mode']=='PAUSED'
    e['clock'][0]+=timedelta(seconds=1);p.reconcile_offline(snapshot(e,'post-restart-fresh'))
    p.resume_next_fresh();e['clock'][0]+=timedelta(seconds=1);start(e,2,C2)
    assert len(p.adapter.transport.orders())==3

def test_duplicate_old_snapshot_is_not_restart_freshness(env):
    e=env;p=e['port'];first(e);old=snapshot(e,'flat-1')
    e['port']=p=ClosedPort.open(p.directory,clock=lambda:e['clock'][0]);p.reconcile_offline(old)
    with pytest.raises(Exception):p.resume_next_fresh()
    assert len(p.adapter.transport.orders())==2

def test_stale_ownership_blocks_resume_even_after_new_cash(env):
    e=env;p=e['port'];first(e);e['clock'][0]+=timedelta(seconds=31);p.fund_synthetic('100000')
    with pytest.raises(Exception):p.resume_next_fresh()
    assert len(p.adapter.transport.orders())==2 and p.status()['controller']['control']['mode']=='PAUSED'

def test_missing_release_receipt_blocks_next_cycle(env):
    e=env;p=e['port'];first(e)
    with p.controller.store.db() as d:d.execute('DELETE FROM broker_fixture_release_receipts')
    with pytest.raises(Exception):p.resume_next_fresh()
    assert len(p.adapter.transport.orders())==2

def test_changed_settlement_source_blocks_resume(env):
    e=env;p=e['port'];first(e)
    with p.controller.store.db() as d:
        r=json.loads(d.execute('SELECT data FROM broker_fixture_settlements').fetchone()[0]);r['source_fingerprint']='changed'
        d.execute('UPDATE broker_fixture_settlements SET data=?',(json.dumps(r),))
    with pytest.raises(Exception):p.resume_next_fresh()
    assert len(p.adapter.transport.orders())==2

def test_unknown_second_entry_never_resubmits_or_reuses_prior_release(env):
    e=env;p=e['port'];first(e);p.resume_next_fresh();e['clock'][0]+=timedelta(seconds=1)
    p.adapter.transport.timeout_after=True;cid=start(e,2,C2)
    with pytest.raises(Exception):p.resume_next_fresh()
    with pytest.raises(Exception):start(e,2,C2)
    assert len(p.adapter.transport.orders())==3 and p.status()['controller']['allocation']['held_total']=='6600.00'
    assert len(p.status()['release_consumer']['receipts'])==1

def test_recover_method_requires_new_snapshot(env):
    e=env;p=e['port'];first(e);p.recover()
    with pytest.raises(Exception):p.resume_next_fresh()
    e['clock'][0]+=timedelta(seconds=1);p.reconcile_offline(snapshot(e,'fresh-after-recover'));p.resume_next_fresh()
    assert p.status()['controller']['control']['mode']=='ARMED'

def test_no_automatic_entry_after_release_or_evidence_refresh(env):
    e=env;p=e['port'];first(e);e['clock'][0]+=timedelta(seconds=1);p.reconcile_offline(snapshot(e,'fresh-flat-observation'))
    assert p.status()['controller']['control']['mode']=='PAUSED' and len(p.adapter.transport.orders())==2

def test_stale_projection_while_armed_pauses_before_new_entry(env):
    e=env;p=e['port'];first(e);p.resume_next_fresh();e['clock'][0]+=timedelta(seconds=31);p.fund_synthetic('100000')
    with pytest.raises(Exception):start(e,2,C2)
    assert p.status()['controller']['control']['mode']=='PAUSED' and len(p.adapter.transport.orders())==2

def test_rejected_ownership_evidence_pauses_without_releasing_more(env):
    e=env;p=e['port'];first(e);p.resume_next_fresh();e['clock'][0]+=timedelta(seconds=1)
    bad=snapshot(e,'bad-new-evidence');bad['positions'][0]['quantity']=65
    r=p.reconcile_offline(bad)
    assert r['reconciliation']['status']=='REVIEW_REQUIRED' and p.status()['controller']['control']['mode']=='PAUSED'
    assert len(p.status()['release_consumer']['receipts'])==1 and len(p.adapter.transport.orders())==2
