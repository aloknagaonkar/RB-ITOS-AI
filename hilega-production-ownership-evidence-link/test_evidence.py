import copy
import pytest
from evidence import EvidenceLink,Blocked
from support import dependencies,snapshot,fill,prepare_fixture_exit
AT='2026-10-26T09:25:00+05:30'
END='2026-10-26T09:25:05+05:30'
@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY');monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    fixtures=dependencies();s,b,clock,link,entry,contract=fixtures.build(tmp_path/'fixture')
    link.dispatch_prepared(entry['id'],contract,as_of=AT)
    proof=EvidenceLink(link,tmp_path/'fixture/evidence.sqlite');proof.register_entry(entry['id'])
    return s,b,link,entry,proof

def partial(env):
    s,b,link,entry,p=env;a=link.adapter;oid=a.status()['requests'][0]['order_id'];a.transport.fill(oid,20);a.cancel(entry['id'])
    trades=[fill(oid,'BUY',20,at=AT,trade_id='t1')]
    data=snapshot(a,sid='partial',at=AT,trades=trades);r=p.reconcile(data,as_of=AT);return trades,data,r

def finish(env):
    trades,_,_=partial(env);s,b,link,entry,p=env
    prepare_fixture_exit(link,'exit1',20,at=END);p.register_exit('exit1',entry['id'],as_of=END)
    link.adapter.submit('exit1');oid=next(x['order_id'] for x in link.adapter.status()['requests'] if x['request_id']=='exit1')
    link.adapter.transport.fill(oid,20);trades.append(fill(oid,'SELL',20,at=END,trade_id='t2'))
    data=snapshot(link.adapter,sid='flat',at=END,trades=trades)
    return data,p.reconcile(data,as_of=END)

def test_partial_cancel_retains_hold_and_reports_remaining(env):
    trades,data,r=partial(env)
    assert r['reconciliation']['status']=='RECONCILED_OFFLINE_FIXTURE'
    assert r['reconciliation']['positions'][0]['remaining']==20
    assert r['assessment']['release_assessment_controller_ids']==[]
    assert env[0].status()['allocation']['held_total']=='6600.00'

def test_exit_fills_and_flat_position_allow_assessment_only(env):
    data,r=finish(env)
    assert r['reconciliation']['positions'][0]['remaining']==0
    assert r['assessment']['release_assessment_controller_ids']==[env[3]['id']]
    assert r['assessment']['reservations_released'] is False and r['controller_updated'] is False
    assert env[0].status()['allocation']['held_total']=='6600.00' and not env[1].fills()

def test_missing_trade_never_establishes_ownership(env):
    trades,data,_=partial(env);data=copy.deepcopy(data);data['snapshot_id']='missing-fill';data['trades']=[]
    r=env[4].reconcile(data,as_of=AT)
    assert r['reconciliation']['status']=='REVIEW_REQUIRED' and not r['assessment']['release_assessment_controller_ids']

def test_position_mismatch_blocks_release(env):
    data,_=finish(env);data=copy.deepcopy(data);data['snapshot_id']='wrong-position';data['positions'][0]['quantity']=20
    r=env[4].reconcile(data,as_of=END)
    assert r['reconciliation']['status']=='REVIEW_REQUIRED' and not r['assessment']['release_assessment_controller_ids']

def test_duplicate_snapshot_idempotent_without_releasing(env):
    data,_=finish(env);r=env[4].reconcile(data,as_of=END)
    assert r['reconciliation']['status']=='IDEMPOTENT_REPLAY'
    assert env[0].status()['allocation']['held_total']=='6600.00'

def test_stale_proof_cannot_assess_release(env):
    finish(env);r=env[4].assess(as_of='2026-10-26T09:25:36+05:30')
    assert not r['release_assessment_controller_ids']

def test_oversized_exit_reference_rejected(env):
    partial(env);prepare_fixture_exit(env[2],'too-big',65,at=END)
    with pytest.raises(Blocked,match='EXCEEDS_VERIFIED'):env[4].register_exit('too-big',env[3]['id'],as_of=END)

def test_unmapped_order_activity_requires_review(env):
    trades,data,_=partial(env);data=copy.deepcopy(data);data['snapshot_id']='external'
    data['orders'].append(dict(order_id='EXTERNAL',instrument='NSE_FO|12345',product='I',side='SELL',quantity=20,filled=0,pending=20,status='OPEN'))
    r=env[4].reconcile(data,as_of=AT)
    assert r['reconciliation']['status']=='REVIEW_REQUIRED'

def test_live_snapshot_cannot_be_relabelled_by_link(env):
    trades,data,_=partial(env);data['evidence_mode']='LIVE_READ_ONLY_ACCOUNT_PINNED'
    with pytest.raises(Blocked,match='EXPLICIT_OFFLINE'):env[4].reconcile(data,as_of=AT)

def test_receipt_provenance_tampering_blocks_binding(env):
    a=env[2].adapter
    with a.store.tx() as d:d.execute('DELETE FROM receipts')
    with pytest.raises(Blocked,match='DURABLE_PLACE_RECEIPT'):env[4].bind_receipts()

def test_restart_preserves_bindings_but_does_not_fabricate_controller_fills(env):
    data,_=finish(env);p=EvidenceLink(env[2],env[4].path)
    assert p.assess(as_of=END)['release_assessment_controller_ids']==[env[3]['id']]
    assert not env[1].fills() and env[0].status()['control']['mode']=='PAUSED'

def test_changed_same_snapshot_rejected(env):
    trades,data,_=partial(env);data['trades'][0]['price']='101'
    r=env[4].reconcile(data,as_of=AT)
    assert r['reconciliation']['status']=='REVIEW_REQUIRED'

def test_unacknowledged_entry_remains_unknown(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY');monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    f=dependencies();s,b,clock,link,entry,contract=f.build(tmp_path/'unknown');link.adapter.transport.timeout_after=True
    link.dispatch_prepared(entry['id'],contract,as_of=AT);p=EvidenceLink(link,tmp_path/'unknown/evidence.sqlite');p.register_entry(entry['id'])
    data=snapshot(link.adapter,sid='unknown',at=AT,trades=[]);r=p.reconcile(data,as_of=AT)
    assert r['reconciliation']['status']=='REVIEW_REQUIRED' and not r['assessment']['release_assessment_controller_ids']
    assert s.status()['allocation']['held_total']=='6600.00'
