import sys,copy
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from registry import Registry,Blocked
from provider_mapping import draft
AT='2026-10-26T09:25:00+05:30';SCOPE='OFFLINE_ACCOUNT'
def request(rid='entry1',side='BUY'):
    c=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
    return draft(c,request_id=rid,side=side,lots=1,as_of=AT)
def prepare(r,req=None,signal='signal1',parent=None):return r.prepare(req or request(),signal_id=signal,signal_at=AT,direction='BULLISH',parent_id=parent)
def ack(oid='OFFLINE-B1'):return dict(status='success',data=dict(order_ids=[oid]))
@pytest.fixture
def registry(tmp_path):return Registry(tmp_path/'intents.sqlite',SCOPE,'OFFLINE_FIXTURE')
def snapshot():
    return dict(snapshot_id='s1',observed_at='2026-10-26T09:26:00+05:30',account_scope=SCOPE,evidence_mode='OFFLINE_FIXTURE',complete=True,
        orders=[dict(order_id='OFFLINE-B1',instrument='NSE_FO|12345',product='I',side='BUY',quantity=65,filled=20,pending=45,status='PARTIAL')],
        trades=[dict(order_id='OFFLINE-B1',trade_id='t1',instrument='NSE_FO|12345',product='I',side='BUY',quantity=20,price='100',filled_at=AT)],
        positions=[dict(instrument='NSE_FO|12345',product='I',quantity=20)])
def test_intent_persists_before_ack(registry):
    row=prepare(registry);assert row['state']=='OFFLINE_INTENT_REGISTERED'
    assert registry.status(as_of=AT)['receipts']==[]
def test_prepare_retry_same_plan(registry):
    prepare(registry);assert prepare(registry)['idempotent_replay'] and len(registry.status(as_of=AT)['intents'])==1

def test_changed_request_under_same_id_blocks(registry):
    prepare(registry)
    with pytest.raises(Blocked):prepare(registry,request(side='SELL'))
def test_duplicate_signal_new_id_blocks(registry):
    prepare(registry)
    with pytest.raises(Blocked):prepare(registry,request('entry2'))
def test_known_ack_binds_offline_only(registry):
    prepare(registry);r=registry.bind_fixture_ack('entry1','receipt1',ack(),at=AT)
    assert r['status']=='OFFLINE_ACK_BOUND_NOT_FILLED'
def test_ack_retry_does_not_duplicate_binding(registry):
    prepare(registry);registry.bind_fixture_ack('entry1','receipt1',ack(),at=AT);registry.bind_fixture_ack('entry1','receipt1',ack(),at=AT)
    assert len(registry.status(as_of=AT)['receipts'])==1

def test_ack_before_intent_rejected(registry):
    with pytest.raises(Blocked):registry.bind_fixture_ack('missing','receipt1',ack(),at=AT)
def test_split_ack_rejected(registry):
    prepare(registry)
    with pytest.raises(Blocked):registry.bind_fixture_ack('entry1','receipt1',dict(status='success',data=dict(order_ids=['a','b'])),at=AT)
def test_binding_conflict_rejected(registry):
    prepare(registry);registry.bind_fixture_ack('entry1','receipt1',ack(),at=AT)
    with pytest.raises(Blocked):registry.bind_fixture_ack('entry1','receipt2',ack('OTHER'),at=AT)
def test_restart_preserves_bindings(registry):
    prepare(registry);registry.bind_fixture_ack('entry1','receipt1',ack(),at=AT)
    again=Registry(registry.path,SCOPE,'OFFLINE_FIXTURE');assert len(again.status(as_of=AT)['receipts'])==1

def test_account_mode_cannot_change(registry):
    with pytest.raises(Blocked):Registry(registry.path,SCOPE,'LIVE_READ_ONLY')
    with pytest.raises(Blocked):Registry(registry.path,'OTHER','OFFLINE_FIXTURE')
def test_partial_fill_reconciles_existing_ownership_engine(registry):
    prepare(registry);registry.bind_fixture_ack('entry1','receipt1',ack(),at=AT);s=snapshot()
    r=registry.reconcile_fixture(s,as_of=s['observed_at']);assert r['status']=='RECONCILED_OFFLINE_FIXTURE' and r['positions'][0]['remaining']==20

def test_unknown_acceptance_missing_order_stays_review(registry):
    prepare(registry);s=snapshot();s.update(orders=[],trades=[],positions=[])
    r=registry.reconcile_fixture(s,as_of=s['observed_at']);assert r['status']=='REVIEW_REQUIRED'
def test_unmapped_external_exit_stays_review(registry):
    prepare(registry);registry.bind_fixture_ack('entry1','receipt1',ack(),at=AT);s=snapshot();registry.reconcile_fixture(s,as_of=s['observed_at'])
    s=copy.deepcopy(s);s['snapshot_id']='s2';s['orders'][0].update(status='CANCELLED',pending=0)
    s['orders'].append(dict(order_id='EXTERNAL',instrument='NSE_FO|12345',product='I',side='SELL',quantity=20,filled=20,pending=0,status='FILLED'))
    s['trades'].append(dict(order_id='EXTERNAL',trade_id='ext1',instrument='NSE_FO|12345',product='I',side='SELL',quantity=20,price='100',filled_at=AT));s['positions'][0]['quantity']=0
    assert registry.reconcile_fixture(s,as_of=s['observed_at'])['status']=='REVIEW_REQUIRED'
def test_stale_proof_not_current_position_evidence(registry):
    prepare(registry);registry.bind_fixture_ack('entry1','receipt1',ack(),at=AT);s=snapshot();registry.reconcile_fixture(s,as_of=s['observed_at'])
    r=registry.status(as_of='2026-10-26T09:27:00+05:30');assert r['offline_ownership']['state']['status']=='STALE'
def test_exit_requires_parent(registry):
    with pytest.raises(Blocked):prepare(registry,request('exit1','SELL'),parent='missing')
def test_fixture_ack_cannot_bind_live(tmp_path):
    r=Registry(tmp_path/'live.sqlite','LIVE_PINNED_SCOPE','LIVE_READ_ONLY');prepare(r)
    with pytest.raises(Blocked,match='FIXTURE_ACK'):r.bind_fixture_ack('entry1','r',ack(),at=AT)
    with pytest.raises(Blocked,match='PROVENANCE'):r.bind_live_ack('entry1',ack())
    with pytest.raises(Blocked,match='SUBMISSION_DISABLED'):r.submit(request())
def test_live_drafts_stay_draft_only(tmp_path):
    r=Registry(tmp_path/'live.sqlite','LIVE_PINNED_SCOPE','LIVE_READ_ONLY');prepare(r)
    assert prepare(r)['idempotent_replay'] and r.status(as_of=AT)['intents'][0]['state']=='DRAFT_ONLY'
def test_live_input_rejected_by_fixture_registry(registry):
    s=snapshot();s['evidence_mode']='LIVE_READ_ONLY_ACCOUNT_PINNED'
    with pytest.raises(Blocked):registry.reconcile_fixture(s,as_of=AT)

def signed_capture():
    from market_lab.hilega_production_account_adapter_v1 import sign,MODEL,LIVE
    pin=dict(scope='PINNED_TEST_SCOPE',key='11'*32)
    capture=dict(model=MODEL,evidence_mode=LIVE,account_scope=pin['scope'],snapshot_id='test-cap1',generated_at=AT,completed_at=AT,
        session_date=AT[:10],status='READ_ONLY_CAPTURED',account_identity_verified=True,production_execution_enabled=False,
        entry_permission=False,orders_sent=False,diagnostics=dict(status='EMPTY_ACCOUNT_SNAPSHOT_ONLY',issues=[]),orders=[],trades=[],positions=[])
    capture['signature']=sign(capture,pin);return capture,pin

def test_signed_capture_persists_without_ownership_claim(tmp_path):
    cap,pin=signed_capture();r=Registry(tmp_path/'live.sqlite',pin['scope'],'LIVE_READ_ONLY')
    result=r.record_live_capture(cap,pin,as_of=AT);r.record_live_capture(cap,pin,as_of=AT)
    assert result['status']=='EMPTY_ACCOUNT_READ_ONLY_BASELINE' and not result['ownership_verified']
    assert r.status(as_of=AT)['live_capture_count']==1

def test_tampered_capture_rejected(tmp_path):
    from market_lab.hilega_production_account_adapter_v1 import AdapterBlocked
    cap,pin=signed_capture();r=Registry(tmp_path/'live.sqlite',pin['scope'],'LIVE_READ_ONLY');cap['snapshot_id']='changed'
    with pytest.raises(AdapterBlocked):r.record_live_capture(cap,pin,as_of=AT)

def test_signed_capture_same_id_conflict_rejected(tmp_path):
    from market_lab.hilega_production_account_adapter_v1 import sign
    cap,pin=signed_capture();r=Registry(tmp_path/'live.sqlite',pin['scope'],'LIVE_READ_ONLY');r.record_live_capture(cap,pin,as_of=AT)
    cap['diagnostics']['issues']=['FIXTURE_CHANGED'];cap.pop('signature');cap['signature']=sign(cap,pin)
    with pytest.raises(Blocked):r.record_live_capture(cap,pin,as_of=AT)
