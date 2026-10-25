import sys,copy
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from mapping import draft,place_ack,cancel_ack,cancel_draft,DisabledMutations,match,Blocked
AT='2026-10-26T09:25:00+05:30'
def contract():return dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
def request(**kw):return draft(contract(),request_id='fixture1',side='BUY',lots=1,as_of=AT,**kw)
def snapshot():return dict(status='READ_ONLY_CAPTURED',account_scope='FIXTURE',account_identity_verified=True,generated_at=AT,completed_at=AT,production_execution_enabled=False,entry_permission=False,
    orders=[dict(order_id='order-1',instrument='NSE_FO|12345',product='I',side='BUY',quantity=65,filled=0,pending=65,status='OPEN')],trades=[])
def check(s):return match(request(),s,'order-1',expected_account_scope='FIXTURE',as_of=AT)
def test_market_payload_v3_single_leg():
    r=request();b=r['body'];assert b['market_protection']==-1 and b['price']==0 and b['quantity']==65 and b['slice'] is False and b['product']=='I'
    assert len(b['tag'])<=40 and r['submission_enabled'] is False
@pytest.mark.parametrize('v',[0,26,True,-2])
def test_invalid_market_protection(v):
    with pytest.raises(Blocked):request(market_protection=v)
def test_limit_explicit_normalized_tick():
    assert request(order_type='LIMIT',limit_price='100.05',normalized_tick_rupees='.05')['body']['price']==100.05

def test_limit_tick_not_inferred_from_raw_metadata():
    with pytest.raises(Blocked):request(order_type='LIMIT',limit_price='100.05')
def test_limit_off_tick_rejected():
    with pytest.raises(Blocked):request(order_type='LIMIT',limit_price='100.03',normalized_tick_rupees='.05')
def test_expired_contract_blocks():
    c=contract();c['expiry']='2026-10-25'
    with pytest.raises(Blocked):draft(c,request_id='f',side='BUY',lots=1,as_of=AT)
def test_freeze_quantity_blocks_no_slicing():
    with pytest.raises(Blocked):draft(contract(),request_id='f',side='BUY',lots=100,as_of=AT)
def test_ack_not_fill():
    r=place_ack(dict(status='success',data=dict(order_ids=['order-1'])))
    assert r['status']=='ACKNOWLEDGED_NOT_FILLED' and not r['fill_confirmed'] and not r['retry_allowed']
@pytest.mark.parametrize('ids',[[],['a','b'],['bad id'],None])
def test_ambiguous_ack_no_retry(ids):
    r=place_ack(dict(status='success',data=dict(order_ids=ids)));assert not r['retry_allowed'] and not r['fill_confirmed']
def test_provider_error_not_automatically_safe_to_retry():assert place_ack(dict(status='error'))['status']=='UNKNOWN_REQUIRES_RECONCILIATION'
def test_cancel_ack_never_proves_flat():
    r=cancel_ack(dict(status='success',data=dict(order_id='order-1')),'order-1');assert not r['flat_confirmed'] and not r['retry_allowed']
def test_cancel_wrong_id_unknown():assert cancel_ack(dict(status='success',data=dict(order_id='other')),'order-1')['status']=='CANCEL_OUTCOME_UNKNOWN_RECONCILE'
def test_cancel_draft_only():assert cancel_draft('order-1')['documented_method']=='DELETE'
@pytest.mark.parametrize('method',['submit','cancel','modify'])
def test_environment_cannot_enable_mutations(monkeypatch,method):
    monkeypatch.setenv('UPSTOX_LIVE_EXECUTION_ENABLED','1')
    with pytest.raises(Blocked,match='DISABLED_IN_CODE'):getattr(DisabledMutations(),method)(request())
def test_known_order_fields_match_not_ownership():
    r=check(snapshot());assert r['status']=='REQUEST_FIELDS_MATCH_READ_ONLY_OWNERSHIP_UNVERIFIED' and not r['ownership_verified'] and not r['entry_permission']
def test_missing_order_not_rejected_or_retried():
    s=snapshot();s['orders']=[];r=check(s);assert r['status']=='ORDER_NOT_FOUND_ACCEPTANCE_UNRESOLVED' and not r['retry_allowed']
def test_tag_cannot_adopt_another_id():
    s=snapshot();s['orders'][0].update(order_id='other',tag=request()['body']['tag']);assert check(s)['status']=='ORDER_NOT_FOUND_ACCEPTANCE_UNRESOLVED'
def test_filled_order_reconstructed_from_executions():
    s=snapshot();s['orders'][0].update(filled=65,pending=0,status='FILLED');s['trades']=[dict(order_id='order-1',trade_id='t1',instrument='NSE_FO|12345',product='I',side='BUY',quantity=65,price='100')]
    r=check(s);assert r['average_fill_price']=='100' and r['filled_quantity']==65 and r['flat_confirmed'] is False

def test_partial_cancel_not_flat():
    s=snapshot();s['orders'][0].update(filled=20,pending=0,status='CANCELLED');s['trades']=[dict(order_id='order-1',trade_id='t1',instrument='NSE_FO|12345',product='I',side='BUY',quantity=20,price='100')]
    assert check(s)['flat_confirmed'] is False

def test_missing_fill_blocks():
    s=snapshot();s['orders'][0].update(filled=65,pending=0,status='FILLED')
    with pytest.raises(Blocked):check(s)
def test_order_identity_mismatch_blocks():
    s=snapshot();s['orders'][0]['instrument']='NSE_FO|99999'
    with pytest.raises(Blocked):check(s)
def test_account_mismatch_blocks():
    s=snapshot();s['account_scope']='OTHER'
    with pytest.raises(Blocked):check(s)
def test_stale_capture_blocks():
    with pytest.raises(Blocked):match(request(),snapshot(),'order-1',expected_account_scope='FIXTURE',as_of='2026-10-26T09:25:31+05:30')
def test_draft_tampering_blocks():
    r=request();r['body']['quantity']=130
    with pytest.raises(Blocked):match(r,snapshot(),'order-1',expected_account_scope='FIXTURE',as_of=AT)
