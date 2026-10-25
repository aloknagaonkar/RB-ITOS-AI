import sys,copy
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from matcher import evaluate,Blocked
AT='2026-10-26T09:25:00+05:30'
def fixtures(state='FILLED',reflected='6500',cash='93500'):
    order=dict(order_id='fixture-order',instrument='FIXTURE|CE',product='I',side='BUY',quantity=65,filled=65,pending=0,status='FILLED')
    snap=dict(evidence_mode='OFFLINE_FIXTURE',account_scope='FIXTURE',snapshot_id='snap1',observed_at=AT,complete=True,coherent=True,
        available_cash=cash,orders=[order],positions=[dict(instrument='FIXTURE|CE',product='I',quantity=65)],unrelated_cash_activity=False)
    row=dict(reservation_id='r1',account_scope='FIXTURE',reserved_amount='6600',order_id='fixture-order',instrument='FIXTURE|CE',product='I',quantity=65,state=state)
    proof=dict(reservation_id='r1',account_scope='FIXTURE',snapshot_id='snap1',order_id='fixture-order',kind='EXPLICIT_OFFLINE_ATTRIBUTION_ASSERTION',reflected_amount=reflected)
    return snap,[row],[proof]
def call(v):return evaluate(*v,as_of=AT)
def test_full_reflected_premium_deducts_only_unreflected_buffer():
    r=call(fixtures());assert r['status']=='MATCHED_OFFLINE_FIXTURE'
    assert r['full_local_holds']=='6600.00' and r['unreflected_hold_deduction']=='100.00' and r['capacity_preview']=='46650.00'
    assert r['broker_cash_addback']=='0.00' and not r['entry_permission']
def test_no_proof_retains_full_hold_and_blocks():
    s,rows,_=fixtures();r=call((s,rows,[]))
    assert r['status']=='REVIEW_REQUIRED' and r['unreflected_hold_deduction']=='6600.00' and r['new_entry_eligibility_blocked']
def test_partial_reflection_remainder_not_double_counted():
    s,rows,p=fixtures('PARTIAL','2000','98000');s['orders'][0].update(filled=20,pending=45,status='PARTIAL');s['positions'][0]['quantity']=20
    r=call((s,rows,p));assert r['full_local_holds']=='6600.00' and r['unreflected_hold_deduction']=='4600.00'
def test_unknown_overrides_positive_proof():
    r=call(fixtures('UNKNOWN'));assert r['status']=='REVIEW_REQUIRED' and r['explicitly_reflected_overlap']=='0'
def test_pending_cancel_not_release():
    r=call(fixtures('CANCEL_PENDING'));assert r['reservations'][0]['release_amount']=='0' and r['full_local_holds']=='6600.00'
def test_pending_exit_not_release():assert call(fixtures('EXIT_PENDING'))['full_local_holds']=='6600.00'
def test_cancelled_partial_fill_still_exposure_hold():
    s,rows,p=fixtures('PARTIAL','2000','98000');s['orders'][0].update(filled=20,pending=0,status='CANCELLED');s['positions'][0]['quantity']=20
    assert call((s,rows,p))['full_local_holds']=='6600.00'
def test_flat_without_exit_proof_cannot_release():
    s,rows,p=fixtures('TERMINAL_FLAT');s['positions'][0]['quantity']=0
    r=call((s,rows,p));assert r['full_local_holds']=='6600.00' and r['status']=='REVIEW_REQUIRED'
def test_verified_terminal_flat_fixture_recommends_release():
    s,rows,p=fixtures('TERMINAL_FLAT');s['positions'][0]['quantity']=0;p[0].update(all_related_orders_terminal=True,all_exit_fills_verified=True)
    r=call((s,rows,p));assert r['full_local_holds']=='0.00' and r['reservations'][0]['release_amount']=='6600.00'
def test_nonzero_position_blocks_release():
    s,rows,p=fixtures('TERMINAL_FLAT');p[0].update(all_related_orders_terminal=True,all_exit_fills_verified=True)
    assert call((s,rows,p))['full_local_holds']=='6600.00'
@pytest.mark.parametrize('field,value',[('account_scope','OTHER'),('snapshot_id','older'),('order_id','other')])
def test_proof_scope_mismatch(field,value):
    s,rows,p=fixtures();p[0][field]=value
    assert call((s,rows,p))['status']=='REVIEW_REQUIRED'
def test_reflection_over_reservation_blocks():assert call(fixtures(reflected='7000'))['status']=='REVIEW_REQUIRED'
def test_unrelated_order_invalidates_reflection():
    s,rows,p=fixtures();o=copy.deepcopy(s['orders'][0]);o['order_id']='external';s['orders'].append(o)
    r=call((s,rows,p));assert r['unreflected_hold_deduction']=='6600.00' and r['new_entry_eligibility_blocked']
def test_external_cash_change_blocks():
    s,rows,p=fixtures();s['unrelated_cash_activity']=True
    assert call((s,rows,p))['unreflected_hold_deduction']=='6600.00'
def test_unmapped_position_blocks():
    s,rows,p=fixtures();s['positions'].append(dict(instrument='OTHER',product='I',quantity=1))
    assert call((s,rows,p))['status']=='REVIEW_REQUIRED'
def test_noncoherent_snapshot_rejected():
    s,rows,p=fixtures();s['coherent']=False
    with pytest.raises(Blocked):call((s,rows,p))
def test_stale_snapshot_rejected():
    with pytest.raises(Blocked):evaluate(*fixtures(),as_of='2026-10-26T09:25:31+05:30')
def test_future_snapshot_rejected():
    with pytest.raises(Blocked):evaluate(*fixtures(),as_of='2026-10-26T09:24:59+05:30')
def test_live_collector_records_never_used_as_fixture_proof():
    s,rows,p=fixtures();s['evidence_mode']='LIVE_READ_ONLY_ACCOUNT_PINNED'
    with pytest.raises(Blocked,match='OFFLINE_FIXTURES_ONLY'):call((s,rows,p))
def test_same_order_cannot_cover_two_reservations():
    s,rows,p=fixtures();r=copy.deepcopy(rows[0]);r['reservation_id']='r2';rows.append(r)
    with pytest.raises(Blocked):call((s,rows,p))
def test_ambiguous_zero_cash_is_not_spend_permission():
    r=call(fixtures(cash='0',reflected='0'));assert r['capacity_preview']=='0' or r['capacity_preview']=='0.00'
    assert not r['entry_permission']
def test_repeat_evaluation_is_deterministic_no_mutation():
    v=fixtures();original=copy.deepcopy(v);a=call(v);b=call(v)
    assert a==b and v==original
@pytest.mark.parametrize('value',[True,'NaN','Infinity',-1])
def test_invalid_cash_rejected(value):
    v=fixtures();v[0]['available_cash']=value
    with pytest.raises(Blocked):call(v)
def test_reserved_before_submit_deducts_full_local_hold():
    s,rows,p=fixtures('RESERVED');s['orders']=[];s['positions']=[];rows[0]['order_id']=None
    r=call((s,rows,[]));assert r['unreflected_hold_deduction']=='6600.00'
